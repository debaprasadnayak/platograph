"""OneLake shortcut extractor — maps cross-workspace shortcuts to SHORTCUT_TO edges."""

from __future__ import annotations

import json
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class OneLakeShortcutExtractor(BaseExtractor):
    supported_extensions: list[str] = [".shortcut.json", ".json"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        # Shortcut files may appear as .shortcut.json or inside .Lakehouse/shortcuts/
        if not (
            path.name.endswith(".shortcut.json")
            or (path.parent.name == "shortcuts" and path.suffix == ".json")
        ):
            return nodes, edges

        try:
            raw = json.loads(path.read_text())
        except Exception:
            return nodes, edges

        shortcut_name = raw.get("name", path.stem)
        rel = self.relative_path(path, project_root)
        sc_id = self.make_node_id("fabric_shortcut", shortcut_name)
        nodes.append(
            Node(
                id=sc_id,
                name=shortcut_name,
                type=NodeType.FABRIC_SHORTCUT,
                file_path=rel,
            )
        )

        # Target can be another lakehouse, ADLS, S3, etc.
        target = raw.get("target", {})
        target_path: str = (
            target.get("oneLake", {}).get("path", "")
            or target.get("adlsGen2", {}).get("location", "")
            or target.get("s3", {}).get("location", "")
            or ""
        )
        if target_path:
            target_id = self.make_node_id("external_system", target_path[:80])
            nodes.append(
                Node(
                    id=target_id,
                    name=target_path[:80],
                    type=NodeType.EXTERNAL_SYSTEM,
                    layer=DataLayer.SOURCE,
                    metadata={"shortcut_target": target_path},
                )
            )
            edges.append(Edge(sc_id, target_id, EdgeType.SHORTCUT_TO, "EXTRACTED"))

        return nodes, edges
