"""Azure Data Factory pipeline JSON extractor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class AdfExtractor(BaseExtractor):
    PIPELINE_NODE_TYPE: NodeType = NodeType.ADF_PIPELINE
    ACTIVITY_NODE_TYPE: NodeType = NodeType.ADF_ACTIVITY
    supported_extensions: list[str] = [".json"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw: dict[str, Any] = json.loads(path.read_text())
        except Exception:
            return nodes, edges

        props = raw.get("properties", {})
        if "activities" not in props:
            return nodes, edges

        rel = self.relative_path(path, project_root)
        pipeline_name = raw.get("name", path.stem)
        pipeline_id = self.make_node_id(self.PIPELINE_NODE_TYPE.value, pipeline_name)

        nodes.append(
            Node(
                id=pipeline_id,
                name=pipeline_name,
                type=self.PIPELINE_NODE_TYPE,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
                description=props.get("description"),
            )
        )

        activity_id_map: dict[str, str] = {}

        for activity in props.get("activities", []):
            if not isinstance(activity, dict):
                continue
            act_name: str = activity.get("name", "unknown")
            act_id = self.make_node_id(self.ACTIVITY_NODE_TYPE.value, pipeline_name, act_name)
            activity_id_map[act_name] = act_id

            act_meta = self._activity_metadata(activity)
            nodes.append(
                Node(
                    id=act_id,
                    name=act_name,
                    type=self.ACTIVITY_NODE_TYPE,
                    layer=DataLayer.ORCHESTRATION,
                    metadata=act_meta,
                )
            )
            edges.append(Edge(pipeline_id, act_id, EdgeType.CONTAINS, "EXTRACTED"))

            # Lineage edges for Copy activities
            self._copy_lineage(activity, act_id, nodes, edges)

            # ExecutePipeline → TRIGGERS
            if activity.get("type") == "ExecutePipeline":
                ref_name = (activity.get("typeProperties", {}).get("pipeline", {}).get("referenceName") or "")
                if ref_name:
                    ref_id = self.make_node_id(self.PIPELINE_NODE_TYPE.value, ref_name)
                    nodes.append(
                        Node(id=ref_id, name=ref_name, type=self.PIPELINE_NODE_TYPE, layer=DataLayer.ORCHESTRATION)
                    )
                    edges.append(Edge(act_id, ref_id, EdgeType.TRIGGERS, "EXTRACTED"))

        # dependsOn → PRECEDES
        for activity in props.get("activities", []):
            act_name = activity.get("name", "")
            act_id = activity_id_map.get(act_name, "")
            for dep in activity.get("dependsOn", []):
                dep_name = dep.get("activity", "") if isinstance(dep, dict) else str(dep)
                dep_id = activity_id_map.get(dep_name, "")
                if dep_id and act_id:
                    edges.append(Edge(dep_id, act_id, EdgeType.PRECEDES, "EXTRACTED"))

        return nodes, edges

    def _activity_metadata(self, activity: dict[str, Any]) -> dict[str, Any]:
        meta: dict[str, Any] = {"activity_type": activity.get("type", "")}
        props = activity.get("typeProperties", {})
        nb = props.get("notebook", {}).get("referenceName") or props.get("notebookPath", "")
        if nb:
            meta["notebook_path"] = nb
        return meta

    def _copy_lineage(
        self,
        activity: dict[str, Any],
        act_id: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        if activity.get("type") != "Copy":
            return
        props = activity.get("typeProperties", {})
        source_ds = (props.get("source", {}).get("datasetSettings", {}).get("type") or
                     props.get("source", {}).get("type", ""))
        sink_ds = (props.get("sink", {}).get("datasetSettings", {}).get("type") or
                   props.get("sink", {}).get("type", ""))
        if source_ds:
            src_id = self.make_node_id("adf_dataset", source_ds)
            nodes.append(Node(id=src_id, name=source_ds, type=NodeType.ADF_DATASET))
            edges.append(Edge(act_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))
        if sink_ds:
            snk_id = self.make_node_id("adf_dataset", sink_ds)
            nodes.append(Node(id=snk_id, name=sink_ds, type=NodeType.ADF_DATASET))
            edges.append(Edge(act_id, snk_id, EdgeType.WRITES_TO, "EXTRACTED"))
