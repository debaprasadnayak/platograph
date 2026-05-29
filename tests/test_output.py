"""Tests for output modules."""

from __future__ import annotations

import tempfile
from pathlib import Path

from datagraph.graph import DataGraph
from datagraph.models import Node, Edge, NodeType, EdgeType, DataLayer


def _node(nid: str, name: str, ntype: NodeType, layer: DataLayer) -> Node:
    return Node(id=nid, name=name, type=ntype, layer=layer)


def _make_graph() -> DataGraph:
    g = DataGraph()
    g.add_node(_node("raw.orders", "orders", NodeType.TABLE, DataLayer.RAW))
    g.add_node(_node("silver.orders", "silver_orders", NodeType.TABLE, DataLayer.SILVER))
    g.add_edge(Edge(source_id="raw.orders", target_id="silver.orders", type=EdgeType.READS_FROM))
    return g


def test_json_export():
    from datagraph.output import json_export
    g = _make_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        p = json_export.export(g, Path(tmpdir))
        assert p.exists()
        import json
        data = json.loads(p.read_text())
        assert "nodes" in data
        assert len(data["nodes"]) == 2


def test_mermaid_export():
    from datagraph.output import mermaid
    g = _make_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        p = mermaid.export_lineage(g, d)
        assert p.exists()
        content = p.read_text()
        assert "flowchart LR" in content


def test_report_export():
    from datagraph.output import report
    g = _make_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        p = report.export(g, d, project_name="test_project")
        assert p.exists()
        content = p.read_text()
        assert "Platograph Lineage Report" in content
        assert "test_project" in content
