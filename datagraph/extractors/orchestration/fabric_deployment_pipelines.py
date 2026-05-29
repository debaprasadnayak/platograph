"""Fabric Deployment Pipeline extractor."""

from __future__ import annotations

import json
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class FabricDeploymentPipelineExtractor(BaseExtractor):
    supported_extensions: list[str] = [".json"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw = json.loads(path.read_text())
        except Exception:
            return nodes, edges

        if not isinstance(raw, dict):
            return nodes, edges

        # Detect Fabric deployment pipeline JSON
        if "stages" not in raw and raw.get("type") != "DeploymentPipeline":
            return nodes, edges

        rel = self.relative_path(path, project_root)
        dp_name = raw.get("name", path.stem)
        dp_id = self.make_node_id("fabric_deployment_pipeline", dp_name)

        nodes.append(
            Node(
                id=dp_id,
                name=dp_name,
                type=NodeType.FABRIC_DEPLOYMENT_PIPELINE,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
            )
        )

        prev_stage_id: str | None = None
        for stage in raw.get("stages", []):
            if not isinstance(stage, dict):
                continue
            stage_name = stage.get("displayName", stage.get("name", "stage"))
            stage_id = self.make_node_id("fabric_deployment_stage", dp_name, stage_name)
            nodes.append(
                Node(
                    id=stage_id,
                    name=stage_name,
                    type=NodeType.FABRIC_DEPLOYMENT_STAGE,
                    layer=DataLayer.ORCHESTRATION,
                    metadata={"order": stage.get("order", 0)},
                )
            )
            edges.append(Edge(dp_id, stage_id, EdgeType.CONTAINS, "EXTRACTED"))
            if prev_stage_id:
                edges.append(Edge(prev_stage_id, stage_id, EdgeType.PROMOTED_TO, "EXTRACTED"))
            prev_stage_id = stage_id

        return nodes, edges
