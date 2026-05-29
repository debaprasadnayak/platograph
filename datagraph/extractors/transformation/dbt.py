"""dbt Core project extractor.

Handles: dbt_project.yml, models/**/*.sql, models/**/*.yml,
         sources/*.yml, macros/**/*.sql, seeds/*.csv
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_REF_RE = re.compile(r"ref\(['\"](\w+)['\"]\)")
_SOURCE_RE = re.compile(r"source\(['\"](\w+)['\"],\s*['\"](\w+)['\"]\)")


@register
class DbtExtractor(BaseExtractor):
    """Scans a dbt Core project rooted at project_root."""

    supported_extensions: list[str] = []  # directory-level

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        dbt_project_yml = path / "dbt_project.yml"
        if not dbt_project_yml.exists():
            return nodes, edges

        raw = yaml.safe_load(dbt_project_yml.read_text()) or {}
        project_name: str = raw.get("name", path.name)

        layer_paths: dict[str, list[str]] = {
            "source": ["sources", "raw", "landing"],
            "bronze": ["bronze", "ingestion"],
            "silver": ["silver", "staging", "intermediate"],
            "gold": ["gold", "marts", "aggregates"],
            "datamart": ["datamart"],
            "reporting": ["reporting"],
        }

        # ── Models ────────────────────────────────────────────────────
        for sql_file in (path / "models").rglob("*.sql"):
            rel = self.relative_path(sql_file, path)
            layer = self.infer_layer_from_path(rel, layer_paths)
            model_name = sql_file.stem
            node_id = self.make_node_id("dbt_model", project_name, model_name)
            node = Node(
                id=node_id,
                name=model_name,
                type=NodeType.DBT_MODEL,
                layer=layer,
                file_path=str(sql_file.relative_to(project_root)),
            )
            nodes.append(node)

            sql_text = sql_file.read_text()
            for match in _REF_RE.finditer(sql_text):
                dep_name = match.group(1)
                dep_id = self.make_node_id("dbt_model", project_name, dep_name)
                edges.append(Edge(node_id, dep_id, EdgeType.DEPENDS_ON, "EXTRACTED"))

            for match in _SOURCE_RE.finditer(sql_text):
                src_schema, src_table = match.group(1), match.group(2)
                src_id = self.make_node_id("source_table", src_schema, src_table)
                src_node = Node(
                    id=src_id,
                    name=f"{src_schema}.{src_table}",
                    type=NodeType.SOURCE_TABLE,
                    layer=DataLayer.SOURCE,
                )
                nodes.append(src_node)
                edges.append(Edge(node_id, src_id, EdgeType.READS_FROM, "EXTRACTED"))

        # ── YAML schema: descriptions + tests ──────────────────────────
        for yml_file in (path / "models").rglob("*.yml"):
            self._parse_schema_yml(yml_file, project_name, nodes, edges, project_root)

        for yml_file in (path / "models").rglob("*.yaml"):
            self._parse_schema_yml(yml_file, project_name, nodes, edges, project_root)

        # ── Sources ────────────────────────────────────────────────────
        for yml_file in path.rglob("sources*.yml"):
            self._parse_sources_yml(yml_file, nodes, project_root)

        # ── Seeds ──────────────────────────────────────────────────────
        seeds_dir = path / "seeds"
        if seeds_dir.exists():
            for csv_file in seeds_dir.rglob("*.csv"):
                seed_id = self.make_node_id("dbt_seed", project_name, csv_file.stem)
                nodes.append(
                    Node(
                        id=seed_id,
                        name=csv_file.stem,
                        type=NodeType.DBT_SEED,
                        layer=DataLayer.SOURCE,
                        file_path=str(csv_file.relative_to(project_root)),
                    )
                )

        # ── Macros ─────────────────────────────────────────────────────
        macros_dir = path / "macros"
        if macros_dir.exists():
            for sql_file in macros_dir.rglob("*.sql"):
                macro_id = self.make_node_id("dbt_macro", project_name, sql_file.stem)
                nodes.append(
                    Node(
                        id=macro_id,
                        name=sql_file.stem,
                        type=NodeType.DBT_MACRO,
                        layer=DataLayer.UNKNOWN,
                        file_path=str(sql_file.relative_to(project_root)),
                    )
                )

        return nodes, edges

    def _parse_schema_yml(
        self,
        yml_file: Path,
        project_name: str,
        nodes: list[Node],
        edges: list[Edge],
        project_root: Path,
    ) -> None:
        try:
            raw = yaml.safe_load(yml_file.read_text()) or {}
        except Exception:
            return
        for model in raw.get("models", []):
            model_name: str = model.get("name", "")
            model_id = self.make_node_id("dbt_model", project_name, model_name)
            # Enrich description
            desc: str | None = model.get("description")
            if desc:
                nodes.append(
                    Node(id=model_id, name=model_name, type=NodeType.DBT_MODEL, description=desc)
                )
            # Tests
            for col in model.get("columns", []):
                for test in col.get("tests", []):
                    test_name = test if isinstance(test, str) else list(test.keys())[0]
                    test_id = self.make_node_id(
                        "dbt_test", project_name, model_name, col.get("name", ""), test_name
                    )
                    nodes.append(
                        Node(id=test_id, name=f"{model_name}.{test_name}", type=NodeType.DBT_TEST)
                    )
                    edges.append(Edge(model_id, test_id, EdgeType.TESTED_BY, "EXTRACTED"))

    def _parse_sources_yml(
        self, yml_file: Path, nodes: list[Node], project_root: Path
    ) -> None:
        try:
            raw = yaml.safe_load(yml_file.read_text()) or {}
        except Exception:
            return
        for source in raw.get("sources", []):
            schema = source.get("name", "")
            for table in source.get("tables", []):
                table_name = table.get("name", "")
                src_id = self.make_node_id("source_table", schema, table_name)
                nodes.append(
                    Node(
                        id=src_id,
                        name=f"{schema}.{table_name}",
                        type=NodeType.SOURCE_TABLE,
                        layer=DataLayer.SOURCE,
                        description=table.get("description"),
                    )
                )
