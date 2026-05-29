"""Power BI extractor — model.bim (Tabular Model JSON) and .pbip format."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_M_TABLE_RE = re.compile(r'Source\s*=\s*Databricks\.(?:Query|Tables)\([^,\)]*,\s*"([^"]+)"')
_PQ_TABLE_REF_RE = re.compile(r'(?:catalog|schema|table)\s*=\s*"([^"]+)"', re.IGNORECASE)


@register
class PowerBiExtractor(BaseExtractor):
    supported_extensions: list[str] = [".bim", ".json"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        name = path.stem
        if path.suffix == ".bim" or path.name == "model.bim":
            return self._parse_bim(path, project_root)

        # .pbip project — look for model.bim sibling
        if path.suffix == ".pbip":
            bim_path = path.parent / path.stem / "model.bim"
            if bim_path.exists():
                return self._parse_bim(bim_path, project_root)

        return nodes, edges

    def _parse_bim(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw: dict[str, Any] = json.loads(path.read_text())
        except Exception:
            return nodes, edges

        model = raw.get("model", raw)
        dataset_name = path.parent.name or path.stem
        rel = self.relative_path(path, project_root)

        ds_id = self.make_node_id("pbi_dataset", dataset_name)
        nodes.append(
            Node(
                id=ds_id,
                name=dataset_name,
                type=NodeType.PBI_DATASET,
                layer=DataLayer.REPORTING,
                file_path=rel,
            )
        )

        for table in model.get("tables", []):
            if not isinstance(table, dict):
                continue
            tbl_name: str = table.get("name", "")
            tbl_id = self.make_node_id("pbi_table", dataset_name, tbl_name)
            nodes.append(
                Node(id=tbl_id, name=tbl_name, type=NodeType.PBI_TABLE, layer=DataLayer.REPORTING)
            )
            edges.append(Edge(ds_id, tbl_id, EdgeType.CONTAINS, "EXTRACTED"))

            # Parse Power Query M expression for source table references
            for partition in table.get("partitions", []):
                pq_expr = (partition.get("source", {}).get("expression") or "")
                if isinstance(pq_expr, list):
                    pq_expr = "\n".join(pq_expr)
                for m in _M_TABLE_RE.finditer(pq_expr):
                    src_name = m.group(1)
                    src_id = self.make_node_id("table", src_name)
                    nodes.append(Node(id=src_id, name=src_name, type=NodeType.TABLE))
                    edges.append(Edge(tbl_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

            # Measures
            for measure in table.get("measures", []):
                if not isinstance(measure, dict):
                    continue
                measure_name: str = measure.get("name", "")
                m_id = self.make_node_id("pbi_measure", dataset_name, tbl_name, measure_name)
                nodes.append(
                    Node(id=m_id, name=measure_name, type=NodeType.PBI_MEASURE, layer=DataLayer.REPORTING)
                )
                edges.append(Edge(tbl_id, m_id, EdgeType.CONTAINS, "EXTRACTED"))

        # Relationships → REFERENCES
        for rel_def in model.get("relationships", []):
            if not isinstance(rel_def, dict):
                continue
            from_tbl = rel_def.get("fromTable", "")
            to_tbl = rel_def.get("toTable", "")
            if from_tbl and to_tbl:
                f_id = self.make_node_id("pbi_table", dataset_name, from_tbl)
                t_id = self.make_node_id("pbi_table", dataset_name, to_tbl)
                edges.append(Edge(f_id, t_id, EdgeType.REFERENCES, "EXTRACTED"))

        return nodes, edges
