"""Fabric Semantic Model extractor — TMDL definition folder."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_ONELAKE_RE = re.compile(r"abfss://[^@]+@onelake\.dfs\.fabric\.microsoft\.com/([^/\s'\"]+)")
_LAKEHOUSE_TABLE_RE = re.compile(r"lakehouseName\s*=\s*[\"']([^\"']+)[\"'].*?tableName\s*=\s*[\"']([^\"']+)[\"']", re.DOTALL)


@register
class FabricSemanticModelExtractor(BaseExtractor):
    supported_extensions: list[str] = []  # directory-level

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        for sm_dir in path.rglob("*.SemanticModel"):
            if not sm_dir.is_dir():
                continue
            self._parse_semantic_model(sm_dir, project_root, nodes, edges)

        return nodes, edges

    def _parse_semantic_model(
        self,
        sm_dir: Path,
        project_root: Path,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        sm_name = sm_dir.stem
        rel = self.relative_path(sm_dir, project_root)
        sm_id = self.make_node_id("fabric_semantic_model", sm_name)

        nodes.append(
            Node(
                id=sm_id,
                name=sm_name,
                type=NodeType.FABRIC_SEMANTIC_MODEL,
                layer=DataLayer.REPORTING,
                file_path=rel,
            )
        )

        # TMDL definition/ folder
        definition_dir = sm_dir / "definition"
        if not definition_dir.exists():
            return

        # Parse each .tmdl table file
        for tmdl_file in definition_dir.rglob("*.tmdl"):
            self._parse_tmdl(tmdl_file, sm_id, sm_name, project_root, nodes, edges)

        # model.bim fallback
        bim_file = sm_dir / "model.bim"
        if bim_file.exists():
            from datagraph.extractors.bi.power_bi import PowerBiExtractor
            pbi = PowerBiExtractor()
            sub_nodes, sub_edges = pbi.safe_extract(bim_file, project_root)
            nodes.extend(sub_nodes)
            edges.extend(sub_edges)

    def _parse_tmdl(
        self,
        tmdl_file: Path,
        sm_id: str,
        sm_name: str,
        project_root: Path,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        text = tmdl_file.read_text(errors="replace")
        rel = self.relative_path(tmdl_file, project_root)

        # Table block
        if not text.strip().startswith("table "):
            return

        table_name = text.splitlines()[0].replace("table ", "").strip()
        tbl_id = self.make_node_id("fabric_semantic_table", sm_name, table_name)
        nodes.append(
            Node(
                id=tbl_id,
                name=table_name,
                type=NodeType.FABRIC_SEMANTIC_TABLE,
                layer=DataLayer.REPORTING,
                file_path=rel,
            )
        )
        edges.append(Edge(sm_id, tbl_id, EdgeType.CONTAINS, "EXTRACTED"))

        # Source references via OneLake URL or lakehouseName pattern
        for m in _ONELAKE_RE.finditer(text):
            src_path = m.group(1)
            src_id = self.make_node_id("fabric_lakehouse", src_path[:80])
            nodes.append(
                Node(id=src_id, name=src_path[:80], type=NodeType.FABRIC_LAKEHOUSE, layer=DataLayer.BRONZE)
            )
            edges.append(Edge(tbl_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

        for m in _LAKEHOUSE_TABLE_RE.finditer(text):
            lh_name, tbl_name_src = m.group(1), m.group(2)
            src_id = self.make_node_id("table", lh_name, tbl_name_src)
            nodes.append(Node(id=src_id, name=f"{lh_name}.{tbl_name_src}", type=NodeType.TABLE))
            edges.append(Edge(tbl_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

        # Measures
        for line in text.splitlines():
            if line.strip().startswith("measure "):
                measure_name = line.strip().removeprefix("measure ").split("=")[0].strip()
                m_id = self.make_node_id("fabric_measure", sm_name, table_name, measure_name)
                nodes.append(
                    Node(id=m_id, name=measure_name, type=NodeType.FABRIC_MEASURE, layer=DataLayer.REPORTING)
                )
                edges.append(Edge(tbl_id, m_id, EdgeType.CONTAINS, "EXTRACTED"))
