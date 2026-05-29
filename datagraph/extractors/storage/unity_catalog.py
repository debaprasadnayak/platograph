"""Unity Catalog extractor — YAML bundle mode (no live API required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType


@register
class UnityCatalogExtractor(BaseExtractor):
    supported_extensions: list[str] = []  # directory-level

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        # Scan all YAML files in the directory tree
        yaml_files: list[Path] = []
        for ext in ("*.yml", "*.yaml"):
            yaml_files.extend(path.rglob(ext))

        for yml_file in yaml_files:
            try:
                raw: dict[str, Any] = yaml.safe_load(yml_file.read_text()) or {}
            except Exception:
                continue
            self._parse_bundle_yaml(raw, nodes, edges, project_root)

        return nodes, edges

    def _parse_bundle_yaml(
        self,
        raw: dict[str, Any],
        nodes: list[Node],
        edges: list[Edge],
        project_root: Path,
    ) -> None:
        resources = raw.get("resources", {})

        # catalogs: → CATALOG nodes
        for cat_name, cat_def in (resources.get("catalogs") or {}).items():
            if not isinstance(cat_def, dict):
                continue
            cat_id = self.make_node_id("catalog", cat_name)
            nodes.append(
                Node(
                    id=cat_id,
                    name=cat_name,
                    type=NodeType.CATALOG,
                    layer=DataLayer.UNKNOWN,
                    description=cat_def.get("comment"),
                    tags=list(cat_def.get("tags", {}).keys()),
                )
            )

        # schemas: → SCHEMA nodes + PART_OF catalog
        for schema_key, schema_def in (resources.get("schemas") or {}).items():
            if not isinstance(schema_def, dict):
                continue
            catalog_name = schema_def.get("catalog_name", "")
            schema_name = schema_def.get("name", schema_key)
            schema_id = self.make_node_id("schema", catalog_name, schema_name)
            nodes.append(
                Node(
                    id=schema_id,
                    name=f"{catalog_name}.{schema_name}",
                    type=NodeType.SCHEMA,
                    description=schema_def.get("comment"),
                )
            )
            if catalog_name:
                cat_id = self.make_node_id("catalog", catalog_name)
                edges.append(Edge(schema_id, cat_id, EdgeType.PART_OF, "EXTRACTED"))

        # volumes: → VOLUME nodes
        for vol_key, vol_def in (resources.get("volumes") or {}).items():
            if not isinstance(vol_def, dict):
                continue
            cat = vol_def.get("catalog_name", "")
            sch = vol_def.get("schema_name", "")
            vname = vol_def.get("name", vol_key)
            vol_id = self.make_node_id("volume", cat, sch, vname)
            nodes.append(
                Node(
                    id=vol_id,
                    name=f"{cat}.{sch}.{vname}",
                    type=NodeType.VOLUME,
                    description=vol_def.get("comment"),
                )
            )

        # quality_monitors / tables in older bundle formats
        for tbl_key, tbl_def in (resources.get("tables") or {}).items():
            if not isinstance(tbl_def, dict):
                continue
            fqn = tbl_def.get("full_name", tbl_key)
            tbl_id = self.make_node_id("table", fqn)
            nodes.append(
                Node(
                    id=tbl_id,
                    name=fqn,
                    type=NodeType.TABLE,
                    description=tbl_def.get("comment"),
                )
            )
