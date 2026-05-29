"""Microsoft Fabric Lakehouse extractor."""

from __future__ import annotations

import json
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class FabricLakehouseExtractor(BaseExtractor):
    supported_extensions: list[str] = []  # directory-level (.Lakehouse items)

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        # Scan for .Lakehouse directories
        for lakehouse_dir in path.rglob("*.Lakehouse"):
            if not lakehouse_dir.is_dir():
                continue
            self._parse_lakehouse(lakehouse_dir, project_root, nodes, edges)

        return nodes, edges

    def _parse_lakehouse(
        self,
        lakehouse_dir: Path,
        project_root: Path,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name = lakehouse_dir.stem
        rel = self.relative_path(lakehouse_dir, project_root)
        lh_id = self.make_node_id("fabric_lakehouse", name)
        metadata: dict = {}

        # Try to read item.metadata.json or .platform
        for meta_file in ["item.metadata.json", ".platform"]:
            meta_path = lakehouse_dir / meta_file
            if meta_path.exists():
                try:
                    meta_raw = json.loads(meta_path.read_text())
                    metadata.update(meta_raw if isinstance(meta_raw, dict) else {})
                except Exception:
                    pass

        nodes.append(
            Node(
                id=lh_id,
                name=name,
                type=NodeType.FABRIC_LAKEHOUSE,
                layer=DataLayer.BRONZE,
                file_path=rel,
                description=metadata.get("description"),
                metadata={"workspace": metadata.get("workspaceId", "")},
            )
        )

        # Parse table definitions if present
        tables_dir = lakehouse_dir / "Tables"
        if tables_dir.exists():
            for tbl_file in tables_dir.rglob("*.json"):
                self._parse_table_def(tbl_file, lh_id, name, project_root, nodes, edges)

    def _parse_table_def(
        self,
        tbl_file: Path,
        lh_id: str,
        lakehouse_name: str,
        project_root: Path,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        try:
            raw = json.loads(tbl_file.read_text())
        except Exception:
            return
        tbl_name = raw.get("name", tbl_file.stem)
        tbl_id = self.make_node_id("table", lakehouse_name, tbl_name)
        nodes.append(
            Node(
                id=tbl_id,
                name=f"{lakehouse_name}.{tbl_name}",
                type=NodeType.TABLE,
                layer=DataLayer.BRONZE,
                file_path=self.relative_path(tbl_file, project_root),
            )
        )
        edges.append(Edge(lh_id, tbl_id, EdgeType.CONTAINS, "EXTRACTED"))
