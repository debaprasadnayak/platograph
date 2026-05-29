"""Python script extractor (non-Airflow, non-DLT .py files)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import Edge, EdgeType, Node, NodeType

_SPARK_READ_RE = re.compile(
    r'spark\.read(?:\.format\(["\'][^"\']+["\']\))?\.(?:table|load)\(["\']([^"\']+)["\']\)'
)
_SPARK_WRITE_RE = re.compile(
    r'\.write(?:Stream)?\.(?:saveAsTable|insertInto)\(["\']([^"\']+)["\']\)'
)


@register
class PythonScriptExtractor(BaseExtractor):
    supported_extensions: list[str] = [".py"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")

        # Skip Airflow DAGs and DLT pipelines (handled by dedicated extractors)
        if "from airflow" in text or "import dlt" in text or "from dlt" in text:
            return nodes, edges

        # Skip Databricks notebook source files (handled by NotebookExtractor)
        if "# Databricks notebook source" in text or "# COMMAND ----------" in text:
            return nodes, edges

        rel = self.relative_path(path, project_root)
        script_id = self.make_node_id("python_script", rel)
        nodes.append(
            Node(
                id=script_id,
                name=path.stem,
                type=NodeType.PYTHON_SCRIPT,
                file_path=rel,
            )
        )

        for match in _SPARK_READ_RE.finditer(text):
            tname = match.group(1)
            t_id = self.make_node_id("table", tname)
            nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
            edges.append(Edge(script_id, t_id, EdgeType.READS_FROM, "EXTRACTED"))

        for match in _SPARK_WRITE_RE.finditer(text):
            tname = match.group(1)
            t_id = self.make_node_id("table", tname)
            nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
            edges.append(Edge(script_id, t_id, EdgeType.WRITES_TO, "EXTRACTED"))

        # dbutils volume operations
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    s = ast.unparse(node)
                    if "dbutils.fs.cp" in s or "dbutils.fs.mv" in s:
                        edges.append(
                            Edge(script_id, self.make_node_id("volume", "dbutils_fs"), EdgeType.WRITES_TO, "INFERRED")
                        )
        except SyntaxError:
            pass

        return nodes, edges
