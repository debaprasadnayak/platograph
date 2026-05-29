"""dbt Cloud job YAML extractor."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_DBT_SELECT_RE = re.compile(r"--select\s+([\w.*+ ]+)")


@register
class DbtCloudJobExtractor(BaseExtractor):
    supported_extensions: list[str] = [".yml", ".yaml"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        except Exception:
            return nodes, edges

        if "jobs" not in raw:
            return nodes, edges

        rel = self.relative_path(path, project_root)

        for job in raw.get("jobs", []):
            if not isinstance(job, dict):
                continue
            job_name: str = job.get("name", "unnamed_dbt_cloud_job")
            job_id = self.make_node_id("dbt_cloud_job", job_name)

            schedule = job.get("schedule", {})
            cron = schedule.get("cron", "") if isinstance(schedule, dict) else ""

            nodes.append(
                Node(
                    id=job_id,
                    name=job_name,
                    type=NodeType.DBT_CLOUD_JOB,
                    layer=DataLayer.ORCHESTRATION,
                    file_path=rel,
                    metadata={
                        "schedule": cron,
                        "environment": job.get("environment", ""),
                        "execute_steps": job.get("execute_steps", []),
                        "dbt_version": job.get("dbt_version", ""),
                    },
                )
            )

            for step in job.get("execute_steps", []):
                if not isinstance(step, str):
                    continue
                for m in _DBT_SELECT_RE.finditer(step):
                    for model_name in m.group(1).split():
                        if not model_name.startswith("+") and "*" not in model_name:
                            model_id = self.make_node_id("dbt_model", model_name)
                            nodes.append(
                                Node(id=model_id, name=model_name, type=NodeType.DBT_MODEL)
                            )
                            edges.append(Edge(job_id, model_id, EdgeType.EXECUTES, "INFERRED"))

        return nodes, edges
