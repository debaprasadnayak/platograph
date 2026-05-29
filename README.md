# Platograph — Data Platform Knowledge Graph

[![CI](https://github.com/debaprasadnayak/platograph/actions/workflows/ci.yml/badge.svg)](https://github.com/debaprasadnayak/platograph/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/platograph)](https://pypi.org/project/platograph/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/platograph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A data-platform-specific alternative to graphify. Scans **Databricks** and **Microsoft Fabric** projects and builds a queryable, visual knowledge graph covering the entire data flow: raw sources → transformations → BI outputs, with full orchestration context.

## Quickstart

```bash
pip install platograph          # or: uv tool install platograph

platograph scan .               # scan current folder
platograph query "what feeds gold.orders_mart?"
platograph schedule gold.orders_mart
platograph impact silver.stg_orders
platograph prs owner/repo       # data-aware PR blast-radius triage
```

## What it produces

```
datagraph-out/
├── graph.json             # full graph — query offline anytime
├── graph.html             # interactive browser viz (lineage + orchestration toggle)
├── LINEAGE_REPORT.md      # narrative summary for AI assistant context
├── lineage.mermaid        # Mermaid lineage diagram
└── orchestration.mermaid  # Mermaid orchestration diagram
```

## Supported sources

| Category | Sources |
|---|---|
| Transformation | dbt Core, Databricks notebooks (.py/.ipynb), Fabric notebooks, Lakeflow/DLT, SQL scripts, Python scripts |
| Storage | Unity Catalog (YAML + live API), Fabric Lakehouse/Warehouse, OneLake shortcuts |
| Orchestration | Databricks Jobs (bundle YAML/API JSON/Terraform), Apache Airflow, ADF, Synapse, dbt Cloud, GitHub Actions, Fabric Pipelines, Fabric Spark Jobs, Fabric Deployment Pipelines |
| BI | Power BI (model.bim/.pbip), Fabric Semantic Models (TMDL) |
| Docs | Markdown |

## CLI reference

```bash
platograph scan [PATH] [--out DIR] [--dialect DIALECT] [--no-viz] [--no-report]
platograph query "question"           # GraphRAG natural-language Q&A
platograph upstream  <node_id>        # all upstream dependencies
platograph downstream <node_id>       # all downstream consumers
platograph impact <node_id>           # full blast-radius analysis
platograph path <source> <target>     # shortest data path
platograph schedule <asset>           # which orchestrator runs this asset?
platograph execution <job>            # topological task order for a job/DAG
platograph install [PATH]             # write CLAUDE.md + AGENTS.md for AI assistants
platograph serve                      # start MCP stdio server
platograph prs <owner/repo>           # open PRs + graph blast radius
```

## MCP Server (AI assistant integration)

```bash
platograph serve   # exposes 9 tools to Claude, Copilot, Cursor, etc.
```

Tools exposed: `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `impact_analysis`, `schedule_for`, `execution_order`, `list_prs`, `pr_impact`

## GraphRAG

Platograph supports LLM-backed Q&A over the graph. Configure one of:

```bash
# Anthropic (default if ANTHROPIC_API_KEY set)
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Azure OpenAI
export AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=https://...

# Databricks Model Serving
export DATABRICKS_HOST=https://... DATABRICKS_TOKEN=dapi...
```

## Databricks App Viewer

```bash
streamlit run apps/datagraph_viewer/main.py
```

Or deploy to Databricks Apps:

```bash
databricks apps deploy platograph-viewer --source-code-path apps/datagraph_viewer
```

## Scheduled scan via Databricks Asset Bundle

```bash
cd bundle
databricks bundle deploy
databricks bundle run platograph_scan_job
```

## Configuration

Copy `.datagraphrc.yaml.example` to `.datagraphrc.yaml` in your project root:

```yaml
project_name: my-data-platform
sql_dialect: databricks    # databricks | tsql | spark | ansi
ignore_paths:
  - .venv
  - node_modules
  - __pycache__
```

## License

MIT
