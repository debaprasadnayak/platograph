"""Apache Airflow DAG extractor.

Supports operator-to-edge mapping, >> chaining, set_downstream/set_upstream.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

_DBT_SELECT_RE = re.compile(r"--select\s+([\w.*+ ]+)")
_DAG_RE = re.compile(r'DAG\(["\']([^"\']+)["\']')
_SCHEDULE_RE = re.compile(r'schedule_interval\s*=\s*["\']([^"\']+)["\']')

# Operator name → (edge_type, metadata_key, target_node_type)
_OPERATOR_MAP: dict[str, tuple[str, str, NodeType | None]] = {
    "DatabricksRunNowOperator":          ("run_by",  "job_name",         NodeType.DATABRICKS_JOB),
    "DatabricksSubmitRunOperator":       ("executes", "notebook_path",   NodeType.NOTEBOOK),
    "DatabricksNotebookOperator":        ("executes", "notebook_path",   NodeType.NOTEBOOK),
    "DatabricksDeltaLivePipelinesRestartOperator": ("triggers", "pipeline_name", NodeType.LAKEFLOW_PIPELINE),
    "TriggerDagRunOperator":             ("triggers", "trigger_dag_id",  NodeType.AIRFLOW_DAG),
}

# Operators that carry dbt --select
_DBT_OPERATORS = {"BashOperator", "DockerOperator", "KubernetesPodOperator"}


@register
class AirflowExtractor(BaseExtractor):
    supported_extensions: list[str] = [".py"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        if "from airflow" not in text and "import airflow" not in text:
            return nodes, edges

        rel = self.relative_path(path, project_root)

        # Find DAG name
        dag_match = _DAG_RE.search(text)
        dag_name = dag_match.group(1) if dag_match else path.stem
        dag_id = self.make_node_id("airflow_dag", dag_name)

        schedule_match = _SCHEDULE_RE.search(text)
        schedule = schedule_match.group(1) if schedule_match else None

        nodes.append(
            Node(
                id=dag_id,
                name=dag_name,
                type=NodeType.AIRFLOW_DAG,
                layer=DataLayer.ORCHESTRATION,
                file_path=rel,
                metadata={"schedule_interval": schedule},
            )
        )

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return nodes, edges

        # Variable name → task node ID map (for >> resolution)
        var_to_task: dict[str, str] = {}

        # ── Task discovery ──────────────────────────────────────────────
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            # Extract variable name(s)
            if isinstance(node, ast.Assign):
                var_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            else:
                var_names = [node.target.id] if isinstance(node.target, ast.Name) else []
                value = node.value

            if not isinstance(value, ast.Call):
                continue
            operator_name = self._get_call_name(value)
            if not operator_name:
                continue

            # Extract task_id kwarg
            task_id_str = self._get_kwarg_str(value, "task_id") or (var_names[0] if var_names else operator_name)
            task_nid = self.make_node_id("airflow_task", dag_name, task_id_str)

            task_meta: dict[str, Any] = {"operator": operator_name}

            # Map known operators
            if operator_name in _OPERATOR_MAP:
                edge_type_str, meta_key, _ = _OPERATOR_MAP[operator_name]
                val = self._get_kwarg_str(value, meta_key) or self._get_kwarg_str(value, "job_name")
                if val:
                    task_meta[meta_key] = val
                # Also check for job_id / trigger_dag_id
                for kw in ["job_id", "trigger_dag_id", "notebook_path", "pipeline_name"]:
                    v2 = self._get_kwarg_str(value, kw)
                    if v2:
                        task_meta[kw] = v2

            # dbt --select in BashOperator
            if operator_name in _DBT_OPERATORS:
                bash_cmd = self._get_kwarg_str(value, "bash_command") or ""
                models = []
                for m in _DBT_SELECT_RE.finditer(bash_cmd):
                    for part in m.group(1).split():
                        if not part.startswith("+") and "*" not in part:
                            models.append(part)
                if models:
                    task_meta["dbt_models"] = models

            # Generic extra kwargs as metadata
            for alias_key in ("adf_pipeline_name", "fabric_pipeline_name"):
                v = self._get_kwarg_str(value, alias_key)
                if v:
                    task_meta[alias_key] = v

            nodes.append(
                Node(
                    id=task_nid,
                    name=task_id_str,
                    type=NodeType.AIRFLOW_TASK,
                    layer=DataLayer.ORCHESTRATION,
                    metadata=task_meta,
                )
            )
            edges.append(Edge(dag_id, task_nid, EdgeType.CONTAINS, "EXTRACTED"))

            for var_name in var_names:
                var_to_task[var_name] = task_nid

        # ── >> / << chaining ────────────────────────────────────────────
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.BinOp):
                self._process_rshift(node.value, var_to_task, edges)
            # set_downstream / set_upstream method calls
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self._process_set_dep(node.value, var_to_task, edges)

        return nodes, edges

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    def _get_call_name(self, call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    def _get_kwarg_str(self, call: ast.Call, key: str) -> str | None:
        for kw in call.keywords:
            if kw.arg == key and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        return None

    def _resolve_var(self, node: ast.expr, var_map: dict[str, str]) -> list[str]:
        """Return task IDs for a Name or List AST node."""
        if isinstance(node, ast.Name):
            tid = var_map.get(node.id)
            return [tid] if tid else []
        if isinstance(node, ast.List):
            result = []
            for elt in node.elts:
                result.extend(self._resolve_var(elt, var_map))
            return result
        return []

    def _process_rshift(
        self,
        binop: ast.BinOp,
        var_map: dict[str, str],
        edges: list[Edge],
    ) -> None:
        if not isinstance(binop.op, ast.RShift):
            # Recurse into nested BinOps: t1 >> t2 >> t3
            if isinstance(binop.left, ast.BinOp):
                self._process_rshift(binop.left, var_map, edges)
            return
        lefts = self._resolve_var(binop.left, var_map)
        rights = self._resolve_var(binop.right, var_map)
        # Recurse left side for chained >>
        if isinstance(binop.left, ast.BinOp):
            self._process_rshift(binop.left, var_map, edges)
            # left side of >> chain resolves to the rightmost task
            lefts = self._resolve_var(binop.left.right, var_map)
        for l in lefts:
            for r in rights:
                edges.append(Edge(l, r, EdgeType.PRECEDES, "EXTRACTED"))

    def _process_set_dep(
        self,
        call: ast.Call,
        var_map: dict[str, str],
        edges: list[Edge],
    ) -> None:
        method = self._get_call_name(call)
        if method not in ("set_downstream", "set_upstream"):
            return
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            return
        caller_id = var_map.get(call.func.value.id)
        if not caller_id or not call.args:
            return
        targets = self._resolve_var(call.args[0], var_map)
        for t in targets:
            if method == "set_downstream":
                edges.append(Edge(caller_id, t, EdgeType.PRECEDES, "EXTRACTED"))
            else:
                edges.append(Edge(t, caller_id, EdgeType.PRECEDES, "EXTRACTED"))
