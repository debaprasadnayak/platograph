"""Lakeflow / Delta Live Tables extractor."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import sqlglot
import sqlglot.expressions as exp

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_DLT_READ_RE = re.compile(r'dlt\.read\(["\']([^"\']+)["\']\)')
_LIVE_TABLE_SQL_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:LIVE\s+TABLE|LIVE\s+VIEW)\s+(\w+)", re.IGNORECASE
)
_LIVE_SOURCE_RE = re.compile(r"FROM\s+LIVE\.(\w+)", re.IGNORECASE)
# Module-level source/output annotations in docstrings
_DOC_SOURCE_RE = re.compile(r"Source:\s*([\w.]+)", re.IGNORECASE)
_DOC_OUTPUT_RE = re.compile(r"Output:\s*([\w.]+)", re.IGNORECASE)
# pyspark.pipelines detection
_PYSPARK_PIPELINES_RE = re.compile(r"from pyspark import pipelines|import pyspark\.pipelines|from pyspark\.pipelines")


@register
class LakeflowExtractor(BaseExtractor):
    supported_extensions: list[str] = [".py", ".sql"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        is_pyspark_pipelines = bool(_PYSPARK_PIPELINES_RE.search(text))
        is_dlt = (
            "import dlt" in text
            or "from dlt" in text
            or bool(_LIVE_TABLE_SQL_RE.search(text))
            or is_pyspark_pipelines
        )
        if not is_dlt:
            return nodes, edges

        rel = self.relative_path(path, project_root)

        if is_pyspark_pipelines:
            # pyspark.pipelines files define individual datasets; the pipeline
            # node comes from the YAML (DatabricksJobsExtractor). Don't create
            # a per-file pipeline wrapper — emit LAKEFLOW_DATASET nodes only.
            self._parse_python_dlt(text, pipeline_id=None, rel=rel, nodes=nodes, edges=edges)
        else:
            pipeline_id = self.make_node_id("lakeflow_pipeline", rel)
            pipeline_node = Node(
                id=pipeline_id,
                name=path.stem,
                type=NodeType.LAKEFLOW_PIPELINE,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
            )
            nodes.append(pipeline_node)

            if path.suffix == ".py":
                self._parse_python_dlt(text, pipeline_id=pipeline_id, rel=rel, nodes=nodes, edges=edges)
            else:
                self._parse_sql_dlt(text, pipeline_id, rel, nodes, edges)

        return nodes, edges

    @staticmethod
    def _resolve_module_constants(tree: ast.Module) -> dict[str, str]:
        """Return a name→value map of simple module-level string assignments.

        Handles direct strings (``CATALOG = "foo"``) and f-strings whose first
        segment is a known constant variable (``BRONZE = f"{CATALOG}.bronze.tbl"``).
        """
        const_map: dict[str, str] = {}
        for stmt in tree.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not stmt.targets or not isinstance(stmt.targets[0], ast.Name):
                continue
            varname = stmt.targets[0].id
            val = stmt.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                const_map[varname] = val.value
            elif isinstance(val, ast.JoinedStr):
                # Reconstruct best-effort: replace Name references from const_map
                parts: list[str] = []
                for piece in val.values:
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        parts.append(piece.value)
                    elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name):
                        parts.append(const_map.get(piece.value.id, ""))
                resolved = "".join(parts)
                if resolved:
                    const_map[varname] = resolved
        return const_map

    def _parse_python_dlt(
        self,
        text: str,
        pipeline_id: str | None,
        rel: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return

        # Build a constant map from module-level assignments to resolve f-string
        # references such as ``BRONZE = f"{CATALOG}.bronze.openmeteo_air_raw"``.
        const_map = self._resolve_module_constants(tree)
        # Collect all resolved strings that look like qualified table names
        # (catalog.schema.table = 3 dot-separated parts)
        qualified_tables: dict[str, str] = {
            var: val
            for var, val in const_map.items()
            if val.count(".") >= 2 and all(part.isidentifier() for part in val.split("."))
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Check for @dlt.table / @dlt.view OR @dp.materialized_view / @dp.streaming_table
            is_dlt_node = any(
                (isinstance(d, ast.Attribute) and d.attr in ("table", "view", "materialized_view", "streaming_table"))
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("table", "view", "materialized_view", "streaming_table"))
                for d in node.decorator_list
            )
            if not is_dlt_node:
                continue

            # Determine output dataset name from decorator name= kwarg or function name
            ds_name = node.name
            fq_output: str | None = None
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "name":
                            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                fq_output = kw.value.value
                                ds_name = fq_output.split(".")[-1]
                            elif isinstance(kw.value, ast.JoinedStr):
                                # Resolve f-string name
                                parts: list[str] = []
                                for piece in kw.value.values:
                                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                                        parts.append(piece.value)
                                    elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name):
                                        parts.append(const_map.get(piece.value.id, ""))
                                fq_output = "".join(parts)
                                ds_name = fq_output.split(".")[-1] if fq_output else node.name

            # Infer layer from function/table name
            layer = DataLayer.SILVER
            fname_lower = node.name.lower()
            fq_lower = (fq_output or "").lower()
            if fname_lower.startswith("gold") or ".gold." in fq_lower:
                layer = DataLayer.GOLD
            elif fname_lower.startswith("bronze") or ".bronze." in fq_lower:
                layer = DataLayer.BRONZE

            ds_id = self.make_node_id("lakeflow_dataset", fq_output or rel + "/" + ds_name)
            ds_node = Node(
                id=ds_id,
                name=ds_name,
                type=NodeType.LAKEFLOW_DATASET,
                layer=layer,
                file_path=rel,
                metadata={"qualified_name": fq_output} if fq_output else {},
            )
            nodes.append(ds_node)
            if pipeline_id:
                edges.append(Edge(pipeline_id, ds_id, EdgeType.CONTAINS, "EXTRACTED"))

            # Find dlt.read() calls inside the function
            func_src = ast.unparse(node)
            for match in _DLT_READ_RE.finditer(func_src):
                src_name = match.group(1)
                src_id = self.make_node_id("lakeflow_dataset", rel, src_name)
                nodes.append(
                    Node(id=src_id, name=src_name, type=NodeType.LAKEFLOW_DATASET, file_path=rel)
                )
                edges.append(Edge(ds_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

            # Use module-level qualified table constants as source tables.
            # Any constant whose resolved value is a different qualified table
            # than the output is treated as a read source.
            for var, fqt in qualified_tables.items():
                if fqt == fq_output:
                    continue  # skip — that's the output, not an input
                tbl_name = fqt.split(".")[-1]
                src_layer = DataLayer.UNKNOWN
                if ".bronze." in fqt.lower():
                    src_layer = DataLayer.BRONZE
                elif ".silver." in fqt.lower():
                    src_layer = DataLayer.SILVER
                src_id = self.make_node_id("lakeflow_dataset", fqt)
                nodes.append(
                    Node(id=src_id, name=tbl_name, type=NodeType.LAKEFLOW_DATASET,
                         layer=src_layer, file_path=rel,
                         metadata={"qualified_name": fqt})
                )
                edges.append(Edge(ds_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

    def _parse_sql_dlt(
        self,
        text: str,
        pipeline_id: str,
        rel: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for match in _LIVE_TABLE_SQL_RE.finditer(text):
            ds_name = match.group(1)
            ds_id = self.make_node_id("lakeflow_dataset", rel, ds_name)
            nodes.append(
                Node(id=ds_id, name=ds_name, type=NodeType.LAKEFLOW_DATASET, file_path=rel)
            )
            edges.append(Edge(pipeline_id, ds_id, EdgeType.CONTAINS, "EXTRACTED"))

        for match in _LIVE_SOURCE_RE.finditer(text):
            src_name = match.group(1)
            src_id = self.make_node_id("lakeflow_dataset", rel, src_name)
            nodes.append(Node(id=src_id, name=src_name, type=NodeType.LAKEFLOW_DATASET, file_path=rel))
