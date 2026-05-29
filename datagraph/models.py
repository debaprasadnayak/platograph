"""Node and Edge data models for the data-platform knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    # ── Source layer ────────────────────────────────────────────────────────
    SOURCE_TABLE = "source_table"
    EXTERNAL_SYSTEM = "external_system"

    # ── Storage / catalog ───────────────────────────────────────────────────
    CATALOG = "catalog"
    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    VOLUME = "volume"

    # ── Databricks transformation ────────────────────────────────────────────
    DBT_MODEL = "dbt_model"
    DBT_MACRO = "dbt_macro"
    DBT_TEST = "dbt_test"
    DBT_SEED = "dbt_seed"
    NOTEBOOK = "notebook"
    SQL_SCRIPT = "sql_script"
    PYTHON_SCRIPT = "python_script"
    LAKEFLOW_PIPELINE = "lakeflow_pipeline"
    LAKEFLOW_DATASET = "lakeflow_dataset"

    # ── Databricks orchestration ─────────────────────────────────────────────
    DATABRICKS_JOB = "databricks_job"
    DATABRICKS_JOB_TASK = "databricks_job_task"

    # ── Airflow orchestration ────────────────────────────────────────────────
    AIRFLOW_DAG = "airflow_dag"
    AIRFLOW_TASK = "airflow_task"

    # ── ADF / Synapse orchestration ──────────────────────────────────────────
    ADF_PIPELINE = "adf_pipeline"
    ADF_ACTIVITY = "adf_activity"
    ADF_DATASET = "adf_dataset"
    SYNAPSE_PIPELINE = "synapse_pipeline"
    SYNAPSE_ACTIVITY = "synapse_activity"

    # ── dbt Cloud / CI orchestration ─────────────────────────────────────────
    DBT_CLOUD_JOB = "dbt_cloud_job"
    GITHUB_ACTION_WORKFLOW = "github_action_workflow"
    GITHUB_ACTION_STEP = "github_action_step"

    # ── Microsoft Fabric transformation ──────────────────────────────────────
    FABRIC_NOTEBOOK = "fabric_notebook"
    FABRIC_SPARK_JOB = "fabric_spark_job"
    FABRIC_DATAFLOW = "fabric_dataflow"

    # ── Microsoft Fabric storage ──────────────────────────────────────────────
    FABRIC_LAKEHOUSE = "fabric_lakehouse"
    FABRIC_WAREHOUSE = "fabric_warehouse"
    FABRIC_SHORTCUT = "fabric_shortcut"

    # ── Microsoft Fabric orchestration ───────────────────────────────────────
    FABRIC_PIPELINE = "fabric_pipeline"
    FABRIC_PIPELINE_ACTIVITY = "fabric_pipeline_activity"
    FABRIC_DEPLOYMENT_PIPELINE = "fabric_deployment_pipeline"
    FABRIC_DEPLOYMENT_STAGE = "fabric_deployment_stage"

    # ── Microsoft Fabric BI ───────────────────────────────────────────────────
    FABRIC_SEMANTIC_MODEL = "fabric_semantic_model"
    FABRIC_SEMANTIC_TABLE = "fabric_semantic_table"
    FABRIC_MEASURE = "fabric_measure"

    # ── Power BI ──────────────────────────────────────────────────────────────
    PBI_DATASET = "pbi_dataset"
    PBI_TABLE = "pbi_table"
    PBI_MEASURE = "pbi_measure"
    PBI_REPORT = "pbi_report"

    # ── Documentation ─────────────────────────────────────────────────────────
    DOC_FILE = "doc_file"


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

class EdgeType(str, Enum):
    # Lineage
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    DEPENDS_ON = "depends_on"
    REFERENCES = "references"
    TESTED_BY = "tested_by"
    DOCUMENTED_BY = "documented_by"

    # Structural
    CONTAINS = "contains"
    PART_OF = "part_of"

    # Orchestration
    EXECUTES = "executes"
    PRECEDES = "precedes"
    TRIGGERS = "triggers"
    SCHEDULED_BY = "scheduled_by"
    RUN_BY = "run_by"

    # Fabric-specific
    SHORTCUT_TO = "shortcut_to"
    PROMOTED_TO = "promoted_to"


# ---------------------------------------------------------------------------
# Data layers
# ---------------------------------------------------------------------------

class DataLayer(str, Enum):
    SOURCE = "source"
    RAW = "raw"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    DATAMART = "datamart"
    REPORTING = "reporting"
    ORCHESTRATION = "orchestration"
    SEMANTIC_MODEL = "semantic_model"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Node and Edge dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A node in the data-platform knowledge graph."""

    id: str                        # Stable: "nodetype::qualified_name"
    name: str
    type: NodeType
    layer: DataLayer = DataLayer.UNKNOWN
    file_path: str | None = None
    line_number: int | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def merge_from(self, other: "Node") -> None:
        """Non-destructively merge a later-discovered node into this one."""
        if other.description and not self.description:
            self.description = other.description
        if other.layer != DataLayer.UNKNOWN and self.layer == DataLayer.UNKNOWN:
            self.layer = other.layer
        self.tags = list(set(self.tags + other.tags))
        self.metadata.update({k: v for k, v in other.metadata.items() if k not in self.metadata})


@dataclass
class Edge:
    """A directed relationship in the data-platform knowledge graph."""

    source_id: str
    target_id: str
    type: EdgeType
    confidence: str = "EXTRACTED"   # EXTRACTED | INFERRED | AMBIGUOUS
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LINEAGE_EDGE_TYPES: frozenset[str] = frozenset({
    EdgeType.READS_FROM.value,
    EdgeType.WRITES_TO.value,
    EdgeType.DEPENDS_ON.value,
    EdgeType.REFERENCES.value,
    EdgeType.TESTED_BY.value,
    EdgeType.SHORTCUT_TO.value,
})

ORCHESTRATION_EDGE_TYPES: frozenset[str] = frozenset({
    EdgeType.EXECUTES.value,
    EdgeType.PRECEDES.value,
    EdgeType.TRIGGERS.value,
    EdgeType.SCHEDULED_BY.value,
    EdgeType.RUN_BY.value,
    EdgeType.CONTAINS.value,
    EdgeType.PROMOTED_TO.value,
})

ORCHESTRATOR_NODE_TYPES: frozenset[NodeType] = frozenset({
    NodeType.DATABRICKS_JOB,
    NodeType.AIRFLOW_DAG,
    NodeType.ADF_PIPELINE,
    NodeType.SYNAPSE_PIPELINE,
    NodeType.DBT_CLOUD_JOB,
    NodeType.GITHUB_ACTION_WORKFLOW,
    NodeType.FABRIC_PIPELINE,
    NodeType.FABRIC_DEPLOYMENT_PIPELINE,
})

TASK_NODE_TYPES: frozenset[NodeType] = frozenset({
    NodeType.DATABRICKS_JOB_TASK,
    NodeType.AIRFLOW_TASK,
    NodeType.ADF_ACTIVITY,
    NodeType.SYNAPSE_ACTIVITY,
    NodeType.FABRIC_PIPELINE_ACTIVITY,
})
