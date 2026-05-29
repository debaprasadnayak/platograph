"""Tests for orchestration extractors."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_databricks_jobs_extractor():
    from datagraph.extractors.orchestration.databricks_jobs import DatabricksJobsExtractor

    ext = DatabricksJobsExtractor()
    bundle_root = FIXTURES / "sample_databricks_bundle"
    nodes, edges = ext.extract(bundle_root / "databricks.yml", bundle_root)

    node_names = {n.name for n in nodes}
    types = {n.type.value for n in nodes}
    assert len(nodes) > 0, f"No nodes extracted, types={types}"
    assert any("etl" in name.lower() or "my" in name.lower() for name in node_names), node_names


def test_airflow_extractor():
    from datagraph.extractors.orchestration.airflow import AirflowExtractor

    ext = AirflowExtractor()
    nodes, edges = ext.extract(FIXTURES / "sample_airflow_dag.py", FIXTURES)

    node_names = {n.name for n in nodes}
    assert any("sample" in name.lower() and "dag" in name.lower() for name in node_names), node_names


def test_adf_extractor():
    from datagraph.extractors.orchestration.adf import AdfExtractor

    ext = AdfExtractor()
    nodes, edges = ext.extract(FIXTURES / "sample_adf_pipeline.json", FIXTURES)

    node_names = {n.name for n in nodes}
    assert any("SampleCopyPipeline" in name or "copy" in name.lower() for name in node_names), node_names
