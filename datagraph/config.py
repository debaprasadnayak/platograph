"""Pydantic settings and config loader for Platograph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LayerPaths(BaseModel):
    source: list[str] = ["sources", "raw", "landing"]
    bronze: list[str] = ["bronze", "ingestion", "staging_raw"]
    silver: list[str] = ["silver", "staging", "intermediate"]
    gold: list[str] = ["gold", "marts", "aggregates"]
    datamart: list[str] = ["datamart", "dm_", "wide_"]
    reporting: list[str] = ["reporting", "powerbi", "bi", "semantic_model"]


class ExtractorFlags(BaseModel):
    dbt: bool = True
    sql: bool = True
    notebooks: bool = True
    lakeflow: bool = True
    unity_catalog: bool = True
    fabric_notebooks: bool = True
    fabric_lakehouse: bool = True
    fabric_warehouse: bool = True
    fabric_pipelines: bool = True
    fabric_spark_jobs: bool = True
    fabric_semantic_model: bool = True
    onelake_shortcuts: bool = True
    power_bi: bool = True
    python: bool = True
    markdown: bool = True
    databricks_jobs: bool = True
    airflow: bool = True
    adf: bool = True
    synapse: bool = True
    dbt_cloud: bool = True
    github_actions: bool = False
    fabric_deployment_pipelines: bool = True


class LlmEnrichmentConfig(BaseModel):
    enabled: bool = False
    model: str = "claude-sonnet-4-20250514"
    enrich_types: list[str] = ["doc_file", "notebook", "airflow_dag"]


class RagConfig(BaseModel):
    backend: str = "auto"   # auto | anthropic | openai | databricks | azure_openai | ollama
    top_k: int = 10
    hop_depth: int = 2


class DataGraphConfig(BaseModel):
    project_name: str = "my_data_platform"
    sql_dialect: str = "databricks"
    layer_paths: LayerPaths = LayerPaths()
    extractors: ExtractorFlags = ExtractorFlags()
    scan_paths: list[str] = ["."]
    ignore_paths: list[str] = [
        "node_modules", ".venv", "target", "dbt_packages", ".git", "__pycache__",
    ]
    output_dir: str = "datagraph-out"
    max_viz_nodes: int = 300
    max_mermaid_nodes: int = 50
    databricks_path_prefixes_to_strip: list[str] = ["/Workspace", "/Repos", "/Users"]
    airflow_operator_aliases: dict[str, str] = {}
    llm_enrichment: LlmEnrichmentConfig = LlmEnrichmentConfig()
    rag: RagConfig = RagConfig()

    @field_validator("sql_dialect")
    @classmethod
    def validate_dialect(cls, v: str) -> str:
        allowed = {"databricks", "spark", "tsql", "ansi", "bigquery", "snowflake", "duckdb"}
        if v not in allowed:
            raise ValueError(f"sql_dialect must be one of {allowed}")
        return v

    def layer_for_path(self, path: str) -> str:
        """Infer DataLayer name from a relative path string."""
        lower = path.lower()
        for layer, patterns in self.layer_paths.model_dump().items():
            for pattern in patterns:
                if pattern in lower:
                    return layer
        return "unknown"


def load_config(project_root: Path) -> DataGraphConfig:
    """Load `.datagraphrc.yaml` from project root or return defaults."""
    rc_path = project_root / ".datagraphrc.yaml"
    if not rc_path.exists():
        return DataGraphConfig()
    raw: dict[str, Any] = yaml.safe_load(rc_path.read_text()) or {}
    return DataGraphConfig.model_validate(raw)
