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


@register
class LakeflowExtractor(BaseExtractor):
    supported_extensions: list[str] = [".py", ".sql"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        is_dlt = "import dlt" in text or "from dlt" in text or bool(_LIVE_TABLE_SQL_RE.search(text))
        if not is_dlt:
            return nodes, edges

        rel = self.relative_path(path, project_root)
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
            self._parse_python_dlt(text, pipeline_id, rel, nodes, edges)
        else:
            self._parse_sql_dlt(text, pipeline_id, rel, nodes, edges)

        return nodes, edges

    def _parse_python_dlt(
        self,
        text: str,
        pipeline_id: str,
        rel: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Check for @dlt.table or @dlt.view decorator
            is_dlt_node = any(
                (isinstance(d, ast.Attribute) and d.attr in ("table", "view"))
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("table", "view"))
                for d in node.decorator_list
            )
            if not is_dlt_node:
                continue

            # Determine dataset name from decorator name= kwarg or function name
            ds_name = node.name
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            ds_name = kw.value.value

            ds_id = self.make_node_id("lakeflow_dataset", rel, ds_name)
            ds_node = Node(
                id=ds_id,
                name=ds_name,
                type=NodeType.LAKEFLOW_DATASET,
                layer=DataLayer.SILVER,
                file_path=rel,
            )
            nodes.append(ds_node)
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
