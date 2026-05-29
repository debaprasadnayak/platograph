"""Microsoft Fabric Warehouse extractor."""

from __future__ import annotations

import json
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class FabricWarehouseExtractor(BaseExtractor):
    supported_extensions: list[str] = []

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        for wh_dir in path.rglob("*.Warehouse"):
            if not wh_dir.is_dir():
                continue
            name = wh_dir.stem
            rel = self.relative_path(wh_dir, project_root)
            wh_id = self.make_node_id("fabric_warehouse", name)
            nodes.append(
                Node(
                    id=wh_id,
                    name=name,
                    type=NodeType.FABRIC_WAREHOUSE,
                    layer=DataLayer.GOLD,
                    file_path=rel,
                )
            )

            # Parse SQL scripts inside the warehouse item
            for sql_file in wh_dir.rglob("*.sql"):
                from datagraph.extractors.transformation.sql import SqlExtractor
                sql_ext = SqlExtractor(dialect="tsql")
                sub_nodes, sub_edges = sql_ext.safe_extract(sql_file, project_root)
                nodes.extend(sub_nodes)
                edges.extend(sub_edges)
                # Link warehouse → sql script
                if sub_nodes:
                    edges.append(Edge(wh_id, sub_nodes[0].id, EdgeType.CONTAINS, "EXTRACTED"))

        return nodes, edges
