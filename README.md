# Platograph — Data Platform Knowledge Graph

A data-platform-specific alternative to graphify. Scans **Databricks** and **Microsoft Fabric** projects and builds a queryable, visual knowledge graph covering the entire data flow: raw sources → transformations → BI outputs, with full orchestration context.

## Quickstart

```bash
uv tool install platograph   # or: pip install platograph

platograph scan .            # scan current folder
platograph query "what feeds gold.orders_mart?"
platograph schedule gold.orders_mart
platograph impact silver.stg_orders
platograph prs               # data-aware PR blast-radius triage
```

## What it produces

```
datagraph-out/
├── graph.json           # full graph — query offline anytime
├── graph.html           # interactive browser viz (lineage + orchestration toggle)
├── LINEAGE_REPORT.md    # narrative summary for AI assistant context
├── lineage.mermaid      # Mermaid lineage diagram
└── orchestration.mermaid
```

## Supported sources

| Category | Sources |
|---|---|
| Transformation | dbt Core, Databricks notebooks (.py/.ipynb), Fabric notebooks, Lakeflow/DLT, SQL scripts, Python scripts |
| Storage | Unity Catalog (YAML + live API), Fabric Lakehouse/Warehouse, OneLake shortcuts |
| Orchestration | Databricks Jobs (bundle YAML/API JSON/TF), Apache Airflow, ADF, Synapse, dbt Cloud, GitHub Actions, Fabric Pipelines, Fabric Spark Jobs, Fabric Deployment Pipelines |
| BI | Power BI (model.bim/.pbip), Fabric Semantic Models (TMDL) |
| Docs | Markdown |

## MCP Server

```bash
platograph serve               # exposes tools: query_graph, schedule_for, impact_analysis, ...
```

## License

MIT
