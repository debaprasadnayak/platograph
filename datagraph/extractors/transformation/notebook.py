"""Databricks notebook extractor (.ipynb and .py with # COMMAND ----------)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.extractors.transformation.sql import SqlExtractor
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_SPARK_READ_RE = re.compile(
    r'spark\.read(?:\.format\(["\'][^"\']+["\']\))?\.(?:table|load)\(["\']([^"\']+)["\']\)'
)
_SPARK_WRITE_RE = re.compile(
    r'\.write(?:Stream)?\.(?:saveAsTable|insertInto)\(["\']([^"\']+)["\']\)'
)
_RUN_RE = re.compile(r'%run\s+["\']?([^\s"\']+)["\']?')
_SQL_MAGIC_RE = re.compile(r"^%sql\s*\n(.*?)(?=^%|\Z)", re.MULTILINE | re.DOTALL)


@register
class NotebookExtractor(BaseExtractor):
    supported_extensions: list[str] = [".ipynb", ".py"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        suffix = path.suffix.lower()
        if suffix == ".ipynb":
            return self._extract_ipynb(path, project_root)
        elif suffix == ".py":
            return self._extract_py(path, project_root)
        return nodes, edges

    # ------------------------------------------------------------------
    # .ipynb
    # ------------------------------------------------------------------

    def _extract_ipynb(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            import nbformat  # type: ignore[import-untyped]
            nb = nbformat.read(str(path), as_version=4)
        except Exception:
            return nodes, edges

        rel = self.relative_path(path, project_root)
        nb_id = self.make_node_id("notebook", rel)
        description: str | None = None

        for cell in nb.cells:
            if cell.cell_type == "markdown" and description is None:
                lines = cell.source.strip().splitlines()
                description = lines[0].lstrip("#").strip() if lines else None
            elif cell.cell_type == "code":
                src = cell.source
                self._process_python_cell(src, nb_id, nodes, edges, path, project_root)
                for match in _SQL_MAGIC_RE.finditer(src):
                    sql_src = match.group(1)
                    self._process_sql_block(sql_src, nb_id, nodes, edges, rel)

        nodes.insert(
            0,
            Node(
                id=nb_id,
                name=path.stem,
                type=NodeType.NOTEBOOK,
                file_path=rel,
                description=description,
            ),
        )
        return nodes, edges

    # ------------------------------------------------------------------
    # .py (Databricks notebook source format with # COMMAND ----------)
    # ------------------------------------------------------------------

    def _extract_py(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        # Only treat as notebook if it has Databricks magic markers or % directives
        if "# COMMAND ----------" not in text and not text.startswith("# Databricks notebook source"):
            return nodes, edges

        rel = self.relative_path(path, project_root)
        nb_id = self.make_node_id("notebook", rel)

        cells = re.split(r"# COMMAND ----------", text)
        description: str | None = None
        for cell in cells:
            stripped = cell.strip()
            if stripped.startswith("# MAGIC %md") and description is None:
                lines = stripped.splitlines()
                description = lines[1].lstrip("#").strip() if len(lines) > 1 else None
            elif stripped.startswith("# MAGIC %sql"):
                sql_src = "\n".join(
                    l.removeprefix("# MAGIC ").strip() for l in stripped.splitlines()[1:]
                )
                self._process_sql_block(sql_src, nb_id, nodes, edges, rel)
            elif not stripped.startswith("# MAGIC"):
                self._process_python_cell(stripped, nb_id, nodes, edges, path, project_root)

        nodes.insert(
            0,
            Node(
                id=nb_id,
                name=path.stem,
                type=NodeType.NOTEBOOK,
                file_path=rel,
                description=description,
            ),
        )
        return nodes, edges

    # ------------------------------------------------------------------
    # Cell processing helpers
    # ------------------------------------------------------------------

    def _process_python_cell(
        self,
        src: str,
        nb_id: str,
        nodes: list[Node],
        edges: list[Edge],
        path: Path,
        project_root: Path,
    ) -> None:
        for match in _SPARK_READ_RE.finditer(src):
            tname = match.group(1)
            t_id = self.make_node_id("table", tname)
            nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
            edges.append(Edge(nb_id, t_id, EdgeType.READS_FROM, "EXTRACTED"))

        for match in _SPARK_WRITE_RE.finditer(src):
            tname = match.group(1)
            t_id = self.make_node_id("table", tname)
            nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
            edges.append(Edge(nb_id, t_id, EdgeType.WRITES_TO, "EXTRACTED"))

        for match in _RUN_RE.finditer(src):
            dep_path = match.group(1)
            dep_id = self.make_node_id("notebook", dep_path)
            dep_node = Node(id=dep_id, name=Path(dep_path).stem, type=NodeType.NOTEBOOK, file_path=dep_path)
            nodes.append(dep_node)
            edges.append(Edge(nb_id, dep_id, EdgeType.DEPENDS_ON, "EXTRACTED"))

        # AST walk for spark calls
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    call_str = ast.unparse(node)
                    for m in _SPARK_READ_RE.finditer(call_str):
                        tname = m.group(1)
                        t_id = self.make_node_id("table", tname)
                        nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
                        edges.append(Edge(nb_id, t_id, EdgeType.READS_FROM, "INFERRED"))
        except SyntaxError:
            pass

    def _process_sql_block(
        self,
        sql_src: str,
        nb_id: str,
        nodes: list[Node],
        edges: list[Edge],
        rel: str,
    ) -> None:
        sql_ext = SqlExtractor()
        import tempfile, os  # noqa: E401
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False, mode="w") as tmp:
            tmp.write(sql_src)
            tmp_path = Path(tmp.name)
        try:
            sub_nodes, sub_edges = sql_ext.safe_extract(tmp_path, tmp_path.parent)
            # Re-wire edges from the temp script ID to the notebook ID
            script_id = sql_ext.make_node_id("sql_script", str(tmp_path))
            for n in sub_nodes[1:]:  # skip the script node itself
                nodes.append(n)
            for e in sub_edges:
                src = nb_id if e.source_id == script_id else e.source_id
                tgt = nb_id if e.target_id == script_id else e.target_id
                edges.append(
                    Edge(src, tgt, e.type, e.confidence)
                )
        finally:
            os.unlink(tmp_path)
