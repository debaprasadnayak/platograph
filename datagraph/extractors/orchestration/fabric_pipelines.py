"""Microsoft Fabric Data Pipeline extractor (ADF-compatible JSON schema)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datagraph.extractors.orchestration.adf import AdfExtractor
from datagraph.extractors.base import register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class FabricPipelineExtractor(AdfExtractor):
    PIPELINE_NODE_TYPE = NodeType.FABRIC_PIPELINE
    ACTIVITY_NODE_TYPE = NodeType.FABRIC_PIPELINE_ACTIVITY

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        # Match *.DataPipeline directories or pipeline.json files inside them
        is_fabric_pipeline = (
            ".DataPipeline" in str(path)
            or (path.name == "pipeline-content.json")
        )
        if not is_fabric_pipeline:
            return [], []

        if path.is_dir():
            # Look for the pipeline JSON inside the directory
            for candidate in ["pipeline-content.json", "content.json", "pipeline.json"]:
                candidate_path = path / candidate
                if candidate_path.exists():
                    return super().extract(candidate_path, project_root)
            return [], []

        return super().extract(path, project_root)

    def _activity_metadata(self, activity: dict[str, Any]) -> dict[str, Any]:
        meta = super()._activity_metadata(activity)
        props = activity.get("typeProperties", {})
        act_type = activity.get("type", "")

        # Fabric-specific: InvokeNotebook
        if act_type == "FabricNotebook" or act_type == "InvokeNotebook":
            nb_name = props.get("notebook", {}).get("referenceName", "")
            if nb_name:
                meta["notebook_path"] = nb_name

        # CopyToTable activity → reads from source lakehouse/warehouse
        if act_type == "Copy":
            lh = props.get("source", {}).get("datasetSettings", {}).get("type", "")
            if "Lakehouse" in lh:
                meta["lakehouse_name"] = lh

        return meta
