# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-29

### Added

- Full extractor suite for Databricks + Microsoft Fabric
  - Transformation: dbt Core, SQL scripts, Databricks notebooks (.py/.ipynb), Lakeflow/DLT, Python scripts, Markdown docs
  - Storage: Unity Catalog bundles, Fabric Lakehouse, Fabric Warehouse, OneLake shortcuts
  - Orchestration: Databricks Jobs (bundle YAML / API JSON / Terraform), Apache Airflow, ADF, Azure Synapse, dbt Cloud, GitHub Actions, Fabric Pipelines, Fabric Spark Jobs, Fabric Deployment Pipelines
  - BI: Power BI (model.bim / .pbip), Fabric TMDL Semantic Models
- `DataGraph` core with merge semantics, edge deduplication, cross-reference resolution
- Traversal: `upstream()`, `downstream()`, `impact_analysis()`, `shortest_path()`, `schedule_for()`, `execution_order()`
- Community detection via Louvain clustering
- GraphRAG stack: pluggable embedding backends (Anthropic / OpenAI / Azure / Databricks), hybrid retriever, LLM synthesizer with fallback
- Output formats: `graph.json`, `graph.html` (pyvis interactive), `LINEAGE_REPORT.md`, `lineage.mermaid`, `orchestration.mermaid`
- MCP stdio server with 9 tools (`query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `impact_analysis`, `schedule_for`, `execution_order`, `list_prs`, `pr_impact`)
- Click CLI: `scan`, `query`, `upstream`, `downstream`, `impact`, `path`, `schedule`, `execution`, `install`, `serve`, `prs`
- GitHub PR blast-radius triage (`pr_triage`)
- Streamlit viewer app (`apps/datagraph_viewer/`)
- Databricks Asset Bundle for scheduled scan job (`bundle/`)
- 15 unit tests across graph core, extractors, orchestration, and outputs
- CI/CD pipeline (GitHub Actions): ruff → mypy → bandit → pytest
- `.datagraphrc.yaml` config system (pydantic-settings)
- `platograph install` writes `CLAUDE.md` / `AGENTS.md` for AI assistant integration
