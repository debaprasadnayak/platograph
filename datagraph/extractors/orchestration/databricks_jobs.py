"""Databricks Jobs extractor.

Supports: Asset Bundle YAML, Jobs API JSON export, and Terraform HCL (regex-based).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_TF_JOB_RE = re.compile(r'resource\s+"databricks_job"\s+"(\w+)"', re.MULTILINE)
_TF_NOTEBOOK_RE = re.compile(r'notebook_path\s*=\s*"([^"]+)"')
_TF_SCHEDULE_RE = re.compile(r'quartz_cron_expression\s*=\s*"([^"]+)"')

# dbt --select pattern: extracts model names
_DBT_SELECT_RE = re.compile(r"--select\s+([\w.*+ ]+)")


@register
class DatabricksJobsExtractor(BaseExtractor):
    supported_extensions: list[str] = [".yml", ".yaml", ".json", ".tf"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        suffix = path.suffix.lower()
        if suffix in (".yml", ".yaml"):
            return self._extract_yaml(path, project_root)
        if suffix == ".json":
            return self._extract_json(path, project_root)
        if suffix == ".tf":
            return self._extract_terraform(path, project_root)
        return [], []

    # ------------------------------------------------------------------
    # Asset Bundle YAML
    # ------------------------------------------------------------------

    def _extract_yaml(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        except Exception:
            return nodes, edges

        jobs = raw.get("resources", {}).get("jobs", {})
        if not jobs:
            return nodes, edges

        rel = self.relative_path(path, project_root)
        for job_key, job_def in jobs.items():
            if not isinstance(job_def, dict):
                continue
            self._parse_job(job_key, job_def, rel, nodes, edges)

        return nodes, edges

    # ------------------------------------------------------------------
    # Jobs API JSON export
    # ------------------------------------------------------------------

    def _extract_json(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            raw = json.loads(path.read_text())
        except Exception:
            return nodes, edges

        # Single job export
        if "job_id" in raw and "settings" in raw:
            settings = raw["settings"]
            job_name = settings.get("name", path.stem)
            rel = self.relative_path(path, project_root)
            self._parse_job(job_name, settings, rel, nodes, edges)
            return nodes, edges

        # Bulk export (list)
        if isinstance(raw, list):
            rel = self.relative_path(path, project_root)
            for item in raw:
                if isinstance(item, dict) and "settings" in item:
                    settings = item["settings"]
                    job_name = settings.get("name", f"job_{item.get('job_id', '')}")
                    self._parse_job(job_name, settings, rel, nodes, edges)

        return nodes, edges

    # ------------------------------------------------------------------
    # Terraform HCL (regex-based)
    # ------------------------------------------------------------------

    def _extract_terraform(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []
        text = path.read_text(errors="replace")
        rel = self.relative_path(path, project_root)

        for m in _TF_JOB_RE.finditer(text):
            job_name = m.group(1)
            job_id = self.make_node_id("databricks_job", job_name)
            schedule_m = _TF_SCHEDULE_RE.search(text)
            metadata: dict[str, Any] = {"source_file": rel, "source_format": "terraform"}
            if schedule_m:
                metadata["schedule"] = schedule_m.group(1)
            nodes.append(
                Node(
                    id=job_id,
                    name=job_name,
                    type=NodeType.DATABRICKS_JOB,
                    layer=DataLayer.ORCHESTRATION,
                    file_path=rel,
                    metadata=metadata,
                )
            )
            for nb_m in _TF_NOTEBOOK_RE.finditer(text):
                task_id = self.make_node_id("databricks_job_task", job_name, "tf_task")
                nodes.append(
                    Node(
                        id=task_id,
                        name="tf_task",
                        type=NodeType.DATABRICKS_JOB_TASK,
                        layer=DataLayer.ORCHESTRATION,
                        metadata={"notebook_path": nb_m.group(1)},
                    )
                )
                edges.append(Edge(job_id, task_id, EdgeType.CONTAINS, "EXTRACTED"))

        return nodes, edges

    # ------------------------------------------------------------------
    # Core parser shared by YAML + JSON formats
    # ------------------------------------------------------------------

    def _parse_job(
        self,
        job_name: str,
        job_def: dict[str, Any],
        source_rel: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        job_id = self.make_node_id("databricks_job", job_name)

        schedule = job_def.get("schedule", {})
        cron = schedule.get("quartz_cron_expression") or schedule.get("cron_expression", "")
        tz = schedule.get("timezone_id", "UTC")

        nodes.append(
            Node(
                id=job_id,
                name=job_name,
                type=NodeType.DATABRICKS_JOB,
                layer=DataLayer.ORCHESTRATION,
                file_path=source_rel,
                metadata={
                    "schedule": cron,
                    "schedule_timezone": tz,
                    "source_file": source_rel,
                    "source_format": "bundle_yaml" if source_rel.endswith((".yml", ".yaml")) else "api_json",
                    "task_count": len(job_def.get("tasks", [])),
                    "tags": job_def.get("tags", {}),
                },
            )
        )

        # task name → task node ID for building PRECEDES edges
        task_id_map: dict[str, str] = {}

        for task in job_def.get("tasks", []):
            if not isinstance(task, dict):
                continue
            task_key: str = task.get("task_key", "unknown_task")
            task_id = self.make_node_id("databricks_job_task", job_name, task_key)
            task_id_map[task_key] = task_id

            task_meta = self._task_metadata(task)
            nodes.append(
                Node(
                    id=task_id,
                    name=task_key,
                    type=NodeType.DATABRICKS_JOB_TASK,
                    layer=DataLayer.ORCHESTRATION,
                    metadata=task_meta,
                )
            )
            edges.append(Edge(job_id, task_id, EdgeType.CONTAINS, "EXTRACTED"))

        # PRECEDES edges from depends_on
        for task in job_def.get("tasks", []):
            if not isinstance(task, dict):
                continue
            task_key = task.get("task_key", "")
            current_task_id = task_id_map.get(task_key, "")
            for dep in task.get("depends_on", []):
                dep_key = dep.get("task_key", "") if isinstance(dep, dict) else str(dep)
                dep_task_id = task_id_map.get(dep_key, "")
                if dep_task_id and current_task_id:
                    edges.append(Edge(dep_task_id, current_task_id, EdgeType.PRECEDES, "EXTRACTED"))

    def _task_metadata(self, task: dict[str, Any]) -> dict[str, Any]:
        """Extract type-specific metadata so _resolve_cross_references can link targets."""
        meta: dict[str, Any] = {}

        if "notebook_task" in task:
            nb = task["notebook_task"]
            meta["task_type"] = "notebook_task"
            meta["notebook_path"] = nb.get("notebook_path", "")

        elif "spark_python_task" in task:
            sp = task["spark_python_task"]
            meta["task_type"] = "spark_python_task"
            meta["python_file"] = sp.get("python_file", "")

        elif "python_wheel_task" in task:
            pw = task["python_wheel_task"]
            meta["task_type"] = "python_wheel_task"
            meta["entry_point"] = pw.get("entry_point", "")

        elif "pipeline_task" in task:
            pt = task["pipeline_task"]
            meta["task_type"] = "pipeline_task"
            meta["pipeline_name"] = pt.get("pipeline_name", "") or pt.get("pipeline_id", "")

        elif "dbt_task" in task:
            dt = task["dbt_task"]
            meta["task_type"] = "dbt_task"
            commands = dt.get("commands", [])
            models = []
            for cmd in commands:
                m = _DBT_SELECT_RE.search(cmd)
                if m:
                    selector = m.group(1).strip()
                    # Expand simple wildcard selectors to model name hints
                    for part in selector.split():
                        if not part.startswith("+") and "*" not in part:
                            models.append(part)
            meta["dbt_models"] = models

        elif "sql_task" in task:
            st = task["sql_task"]
            meta["task_type"] = "sql_task"
            meta["sql_file"] = (st.get("file") or {}).get("path", "")

        elif "run_job_task" in task:
            rj = task["run_job_task"]
            meta["task_type"] = "run_job_task"
            meta["run_job_name"] = rj.get("job_name", "") or str(rj.get("job_id", ""))

        return meta
