"""Tests for extractors."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_dbt_extractor():
    from datagraph.extractors.transformation.dbt import DbtExtractor
    from datagraph.graph import DataGraph

    dbt_root = FIXTURES / "sample_dbt_project"
    ext = DbtExtractor()
    nodes, edges = ext.extract(dbt_root, dbt_root)

    node_names = {n.name for n in nodes}
    assert any("stg_orders" in name for name in node_names), f"stg_orders not found in {node_names}"
    assert any("orders_mart" in name for name in node_names), f"orders_mart not found in {node_names}"


def test_notebook_extractor():
    from datagraph.extractors.transformation.notebook import NotebookExtractor

    ext = NotebookExtractor()
    nodes, edges = ext.extract(FIXTURES / "sample_notebook.ipynb", FIXTURES)

    node_names = {n.name for n in nodes}
    assert len(nodes) > 0, f"No nodes extracted from notebook"


def test_sql_extractor():
    from datagraph.extractors.transformation.sql import SqlExtractor

    tmp = Path("/tmp/datagraph_test_sql")
    tmp.mkdir(exist_ok=True)
    (tmp / "test_create.sql").write_text(
        "CREATE TABLE gold.orders_summary AS SELECT order_id FROM silver.orders;"
    )
    ext = SqlExtractor()
    nodes, edges = ext.extract(tmp / "test_create.sql", tmp)

    node_names = {n.name for n in nodes}
    assert any("orders_summary" in name for name in node_names), node_names
