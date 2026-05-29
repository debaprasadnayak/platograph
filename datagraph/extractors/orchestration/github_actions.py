"""GitHub Actions workflow extractor — data-relevant steps only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_DBT_SELECT_RE = re.compile(r"--select\s+([\w.*+ ]+)")
_BUNDLE_RUN_RE = re.compile(r"databricks\s+bundle\s+run\s+(\S+)")
_ADF_RUN_RE = re.compile(r"az\s+datafactory\s+pipeline.*?--name\s+(\S+)")

_DATA_KEYWORDS = frozenset([
    "databricks", "dbt run", "adf", "sqlfluff", "spark-submit",
    "bundle run", "delta", "synapse",
])


@register
class GithubActionsExtractor(BaseExtractor):
    supported_extensions: list[str] = [".yml", ".yaml"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        # Only process .github/workflows files
        if ".github" not in str(path) or "workflows" not in str(path):
            return nodes, edges

        try:
            raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        except Exception:
            return nodes, edges

        # Check data relevance
        raw_text = path.read_text(errors="replace").lower()
        if not any(kw in raw_text for kw in _DATA_KEYWORDS):
            return nodes, edges

        rel = self.relative_path(path, project_root)
        wf_name = raw.get("name", path.stem)
        wf_id = self.make_node_id("github_action_workflow", wf_name)

        # Determine trigger
        on_clause = raw.get("on", {})
        trigger = (
            list(on_clause.keys())[0]
            if isinstance(on_clause, dict)
            else str(on_clause)
        )
        cron = ""
        if isinstance(on_clause, dict) and "schedule" in on_clause:
            schedule_list = on_clause["schedule"]
            if isinstance(schedule_list, list) and schedule_list:
                cron = schedule_list[0].get("cron", "")

        nodes.append(
            Node(
                id=wf_id,
                name=wf_name,
                type=NodeType.GITHUB_ACTION_WORKFLOW,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
                metadata={"trigger": trigger, "schedule": cron},
            )
        )

        for job_name, job_def in (raw.get("jobs") or {}).items():
            if not isinstance(job_def, dict):
                continue
            for i, step in enumerate(job_def.get("steps", [])):
                if not isinstance(step, dict):
                    continue
                step_name = step.get("name", f"step_{i}")
                run_cmd = step.get("run", "")
                uses = step.get("uses", "")
                combined = f"{run_cmd} {uses}".lower()

                if not any(kw in combined for kw in _DATA_KEYWORDS):
                    continue

                step_id = self.make_node_id("github_action_step", wf_name, job_name, step_name)
                step_meta: dict[str, Any] = {"run": run_cmd[:200], "uses": uses}

                # Databricks bundle run <job>
                m = _BUNDLE_RUN_RE.search(run_cmd)
                if m:
                    step_meta["databricks_job_name"] = m.group(1)

                # dbt --select
                for dm in _DBT_SELECT_RE.finditer(run_cmd):
                    models = [
                        p for p in dm.group(1).split()
                        if not p.startswith("+") and "*" not in p
                    ]
                    if models:
                        step_meta["dbt_models"] = models

                # ADF pipeline run
                am = _ADF_RUN_RE.search(run_cmd)
                if am:
                    step_meta["adf_pipeline_name"] = am.group(1)

                nodes.append(
                    Node(
                        id=step_id,
                        name=step_name,
                        type=NodeType.GITHUB_ACTION_STEP,
                        layer=DataLayer.ORCHESTRATION,
                        metadata=step_meta,
                    )
                )
                edges.append(Edge(wf_id, step_id, EdgeType.CONTAINS, "EXTRACTED"))

        return nodes, edges
