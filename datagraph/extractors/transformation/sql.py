"""SQL script extractor using sqlglot for dialect-aware parsing."""

from __future__ import annotations

from pathlib import Path

import sqlglot
import sqlglot.expressions as exp

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class SqlExtractor(BaseExtractor):
    supported_extensions: list[str] = [".sql"]

    def __init__(self, dialect: str = "databricks") -> None:
        self.dialect = dialect

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        rel = self.relative_path(path, project_root)
        script_id = self.make_node_id("sql_script", rel)
        script_node = Node(
            id=script_id,
            name=path.stem,
            type=NodeType.SQL_SCRIPT,
            layer=DataLayer.UNKNOWN,
            file_path=rel,
        )
        nodes.append(script_node)

        try:
            statements = sqlglot.parse(text, dialect=self.dialect, error_level=sqlglot.ErrorLevel.WARN)
        except Exception:
            return nodes, edges

        for stmt in statements:
            if stmt is None:
                continue
            self._process_statement(stmt, script_id, nodes, edges)

        return nodes, edges

    def _table_name(self, table: exp.Table) -> str:
        parts = [p for p in [table.catalog, table.db, table.name] if p]
        return ".".join(parts)

    def _process_statement(
        self,
        stmt: exp.Expression,
        script_id: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        stmt_type = type(stmt)

        # Determine write target
        write_target: str | None = None
        if isinstance(stmt, (exp.Create,)):
            this = stmt.this
            if isinstance(this, exp.Table):
                write_target = self._table_name(this)
            elif isinstance(this, exp.View):
                vt = this.this
                if isinstance(vt, exp.Table):
                    write_target = self._table_name(vt)
                    t_id = self.make_node_id("view", write_target)
                    nodes.append(Node(id=t_id, name=write_target, type=NodeType.VIEW))
                    edges.append(Edge(script_id, t_id, EdgeType.WRITES_TO, "EXTRACTED"))
                    write_target = None
        elif isinstance(stmt, (exp.Insert, exp.Merge)):
            into = stmt.this
            if isinstance(into, exp.Table):
                write_target = self._table_name(into)

        if write_target:
            t_id = self.make_node_id("table", write_target)
            nodes.append(Node(id=t_id, name=write_target, type=NodeType.TABLE))
            edges.append(Edge(script_id, t_id, EdgeType.WRITES_TO, "EXTRACTED"))

        # All FROM / JOIN sources
        for table in stmt.find_all(exp.Table):
            tname = self._table_name(table)
            if not tname or tname == write_target:
                continue
            t_id = self.make_node_id("table", tname)
            nodes.append(Node(id=t_id, name=tname, type=NodeType.TABLE))
            edges.append(Edge(script_id, t_id, EdgeType.READS_FROM, "EXTRACTED"))
