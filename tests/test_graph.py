"""Tests for DataGraph core."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from datagraph.graph import DataGraph
from datagraph.models import Node, Edge, NodeType, EdgeType, DataLayer


def _node(nid: str, name: str, ntype: NodeType, layer: DataLayer, description: str = "") -> Node:
    return Node(id=nid, name=name, type=ntype, layer=layer, description=description or None)


def _make_graph() -> DataGraph:
    g = DataGraph()
    g.add_node(_node("raw.orders", "orders", NodeType.TABLE, DataLayer.RAW))
    g.add_node(_node("silver.orders", "silver_orders", NodeType.TABLE, DataLayer.SILVER))
    g.add_node(_node("gold.orders_summary", "orders_summary", NodeType.TABLE, DataLayer.GOLD))
    # READS_FROM convention: Edge(consumer, source) — consumer has edge pointing to its source.
    # silver reads from raw → silver → raw
    # gold reads from silver → gold → silver
    g.add_edge(Edge(source_id="silver.orders", target_id="raw.orders", type=EdgeType.READS_FROM))
    g.add_edge(Edge(source_id="gold.orders_summary", target_id="silver.orders", type=EdgeType.READS_FROM))
    return g


def test_add_node_merge():
    g = DataGraph()
    g.add_node(_node("t1", "orders", NodeType.TABLE, DataLayer.RAW))
    g.add_node(_node("t1", "orders", NodeType.TABLE, DataLayer.BRONZE, "desc"))
    assert len(g._nodes) == 1
    assert g._nodes["t1"].description == "desc"


def test_dedup_edges():
    g = _make_graph()
    g.add_edge(Edge(source_id="silver.orders", target_id="raw.orders", type=EdgeType.READS_FROM))
    edge_count = sum(
        1 for e in g._edges
        if e.source_id == "silver.orders" and e.target_id == "raw.orders"
    )
    assert edge_count == 1


def test_upstream_downstream():
    g = _make_graph()
    up = g.upstream("gold.orders_summary", 3)
    up_ids = [n.id for n in up]
    assert "raw.orders" in up_ids
    dn = g.downstream("raw.orders", 3)
    dn_ids = [n.id for n in dn]
    assert "gold.orders_summary" in dn_ids


def test_impact_analysis():
    g = _make_graph()
    result = g.impact_analysis("raw.orders")
    affected_ids = [n.id for n in result["transitively_affected"]]
    assert "silver.orders" in affected_ids
    assert "gold.orders_summary" in affected_ids


def test_serialisation_roundtrip():
    g = _make_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir)
        from datagraph.output import json_export
        json_export.export(g, out)
        g2 = DataGraph.load(out / "graph.json")
    assert len(g2._nodes) == len(g._nodes)
    assert len(g2._edges) == len(g._edges)


def test_summary():
    g = _make_graph()
    s = g.summary()
    assert s["nodes"] == 3
    assert s["edges"] == 2
