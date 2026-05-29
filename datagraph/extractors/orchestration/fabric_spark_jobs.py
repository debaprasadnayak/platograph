"""Fabric Spark Job Definition extractor."""

from __future__ import annotations

import json
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class FabricSparkJobExtractor(BaseExtractor):
    supported_extensions: list[str] = []

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        for sjd_dir in path.rglob("*.SparkJobDefinition"):
            if not sjd_dir.is_dir():
                continue
            self._parse_sjd(sjd_dir, project_root, nodes, edges)

        return nodes, edges

    def _parse_sjd(
        self,
        sjd_dir: Path,
        project_root: Path,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name = sjd_dir.stem
        rel = self.relative_path(sjd_dir, project_root)
        sjd_id = self.make_node_id("fabric_spark_job", name)
        metadata: dict = {}

        for meta_file in ["SparkJobDefinitionV1.json", "item.metadata.json"]:
            meta_path = sjd_dir / meta_file
            if meta_path.exists():
                try:
                    metadata = json.loads(meta_path.read_text())
                except Exception:
                    pass

        nodes.append(
            Node(
                id=sjd_id,
                name=name,
                type=NodeType.FABRIC_SPARK_JOB,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
                metadata={
                    "main_class": metadata.get("payload", {}).get("mainClass", ""),
                    "main_file": metadata.get("payload", {}).get("mainJobFile", {}).get("path", ""),
                },
            )
        )

        # Link to Python/notebook if main file is detectable
        main_file = metadata.get("payload", {}).get("mainJobFile", {}).get("path", "")
        if main_file:
            py_id = self.make_node_id("python_script", main_file)
            nodes.append(Node(id=py_id, name=main_file, type=NodeType.PYTHON_SCRIPT, file_path=main_file))
            edges.append(Edge(sjd_id, py_id, EdgeType.EXECUTES, "EXTRACTED"))
