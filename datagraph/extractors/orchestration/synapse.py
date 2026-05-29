"""Azure Synapse Analytics pipeline extractor — inherits from ADF."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datagraph.extractors.orchestration.adf import AdfExtractor
from datagraph.extractors.base import register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class SynapseExtractor(AdfExtractor):
    PIPELINE_NODE_TYPE = NodeType.SYNAPSE_PIPELINE
    ACTIVITY_NODE_TYPE = NodeType.SYNAPSE_ACTIVITY

    # Synapse-specific activity type handlers
    _EXTRA_HANDLERS: dict[str, str] = {
        "SynapseNotebook": "notebook_path",
        "SparkJob": "python_file",
        "SynapseSparkJobDefinitionActivity": "python_file",
    }

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        # Synapse pipeline JSON lives under workspace/pipeline/
        # Detect by directory or by type field
        try:
            raw: dict[str, Any] = json.loads(path.read_text())
        except Exception:
            return [], []

        if not isinstance(raw, dict):
            return [], []

        # Check it's a Synapse pipeline
        is_synapse = (
            "Microsoft.Synapse/workspaces/pipelines" in raw.get("type", "")
            or "properties" in raw
            and path.parts[-2] == "pipeline"
            if len(path.parts) > 1
            else False
        )
        if not is_synapse and raw.get("type", "") != "Microsoft.Synapse/workspaces/pipelines":
            # Fall back to parent ADF detection — Synapse pipeline JSON is ADF-compatible
            pass

        return super().extract(path, project_root)

    def _activity_metadata(self, activity: dict[str, Any]) -> dict[str, Any]:
        meta = super()._activity_metadata(activity)
        act_type = activity.get("type", "")
        props = activity.get("typeProperties", {})

        if act_type in self._EXTRA_HANDLERS:
            key = self._EXTRA_HANDLERS[act_type]
            val = props.get("notebook", {}).get("referenceName", "") or props.get("file", "")
            if val:
                meta[key] = val

        # SqlPoolStoredProcedure
        if act_type == "SqlPoolStoredProcedure":
            meta["stored_proc"] = props.get("storedProcedureName", "")

        return meta
