"""Core DataGraph class: builds and queries the knowledge graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

from datagraph.models import (
    DataLayer,
    Edge,
    EdgeType,
    LINEAGE_EDGE_TYPES,
    Node,
    NodeType,
    ORCHESTRATION_EDGE_TYPES,
    ORCHESTRATOR_NODE_TYPES,
    TASK_NODE_TYPES,
)


class DataGraph:
    """Dual-dimension (lineage + orchestration) directed knowledge graph."""

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        """Add or merge a node. Later additions enrich, never overwrite."""
        if node.id in self._nodes:
            self._nodes[node.id].merge_from(node)
        else:
            self._nodes[node.id] = node
            self._g.add_node(
                node.id,
                name=node.name,
                type=node.type.value,
                layer=node.layer.value,
            )

    def add_edge(self, edge: Edge) -> None:
        """Add an edge, deduplicating by (source, target, type)."""
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            return
        key = (edge.source_id, edge.target_id, edge.type.value)
        for e in self._edges:
            if (e.source_id, e.target_id, e.type.value) == key:
                return
        self._g.add_edge(
            edge.source_id,
            edge.target_id,
            type=edge.type.value,
            confidence=edge.confidence,
        )
        self._edges.append(edge)

    # ------------------------------------------------------------------
    # Cross-extractor second pass
    # ------------------------------------------------------------------

    def resolve_cross_references(self, strip_prefixes: list[str] | None = None) -> None:
        """Link nodes discovered by different extractors using metadata as foreign keys."""
        prefixes = strip_prefixes or ["/Workspace", "/Repos", "/Users"]

        notebook_index = self._build_path_index(NodeType.NOTEBOOK)
        fabric_nb_index = self._build_path_index(NodeType.FABRIC_NOTEBOOK)
        python_index = self._build_path_index(NodeType.PYTHON_SCRIPT)
        pipeline_index = self._build_name_index(NodeType.LAKEFLOW_PIPELINE)
        fabric_pipeline_index = self._build_name_index(NodeType.FABRIC_PIPELINE)
        job_index = self._build_name_index(NodeType.DATABRICKS_JOB)
        dbt_model_index = self._build_name_index(NodeType.DBT_MODEL)
        dag_index = self._build_name_index(NodeType.AIRFLOW_DAG)
        adf_pipeline_index = self._build_name_index(NodeType.ADF_PIPELINE)
        lakehouse_index = self._build_name_index(NodeType.FABRIC_LAKEHOUSE)

        all_nb_indexes = {**notebook_index, **fabric_nb_index}

        for node in list(self._nodes.values()):
            meta = node.metadata

            # Job task → notebook
            if node.type == NodeType.DATABRICKS_JOB_TASK:
                nb_path: str | None = meta.get("notebook_path")
                if nb_path:
                    target_id = self._resolve_path(nb_path, all_nb_indexes, prefixes)
                    if target_id:
                        self.add_edge(Edge(node.id, target_id, EdgeType.EXECUTES, "EXTRACTED"))

                # Job task → lakeflow pipeline
                pipeline_name: str | None = meta.get("pipeline_name")
                if pipeline_name:
                    pid = pipeline_index.get(pipeline_name.lower())
                    if pid:
                        self.add_edge(Edge(node.id, pid, EdgeType.EXECUTES, "EXTRACTED"))

                # Job task → python script
                py_path: str | None = meta.get("python_file")
                if py_path:
                    target_id = self._resolve_path(py_path, python_index, prefixes)
                    if target_id:
                        self.add_edge(Edge(node.id, target_id, EdgeType.EXECUTES, "EXTRACTED"))

                # run_job_task → another job
                run_job_name: str | None = meta.get("run_job_name")
                if run_job_name:
                    jid = job_index.get(run_job_name.lower())
                    if jid:
                        self.add_edge(Edge(node.id, jid, EdgeType.TRIGGERS, "EXTRACTED"))

                # dbt_task → models
                for model_name in meta.get("dbt_models", []):
                    mid = dbt_model_index.get(model_name.lower())
                    if mid:
                        self.add_edge(Edge(node.id, mid, EdgeType.EXECUTES, "EXTRACTED"))

            # Airflow task → databricks job
            if node.type == NodeType.AIRFLOW_TASK:
                job_name: str | None = meta.get("job_name")
                if job_name:
                    jid = job_index.get(job_name.lower())
                    if jid:
                        self.add_edge(Edge(node.id, jid, EdgeType.RUN_BY, "EXTRACTED"))
                trigger_dag: str | None = meta.get("trigger_dag_id")
                if trigger_dag:
                    did = dag_index.get(trigger_dag.lower())
                    if did:
                        self.add_edge(Edge(node.id, did, EdgeType.TRIGGERS, "EXTRACTED"))
                nb_path2: str | None = meta.get("notebook_path")
                if nb_path2:
                    target_id = self._resolve_path(nb_path2, all_nb_indexes, prefixes)
                    if target_id:
                        self.add_edge(Edge(node.id, target_id, EdgeType.EXECUTES, "EXTRACTED"))
                for model_name in meta.get("dbt_models", []):
                    mid = dbt_model_index.get(model_name.lower())
                    if mid:
                        self.add_edge(Edge(node.id, mid, EdgeType.EXECUTES, "EXTRACTED"))
                # Airflow triggers ADF pipeline
                pipeline_ref: str | None = meta.get("adf_pipeline_name")
                if pipeline_ref:
                    pid = adf_pipeline_index.get(pipeline_ref.lower())
                    if pid:
                        self.add_edge(Edge(node.id, pid, EdgeType.TRIGGERS, "INFERRED"))
                # Airflow triggers Fabric pipeline
                fabric_pipe: str | None = meta.get("fabric_pipeline_name")
                if fabric_pipe:
                    fpid = fabric_pipeline_index.get(fabric_pipe.lower())
                    if fpid:
                        self.add_edge(Edge(node.id, fpid, EdgeType.TRIGGERS, "INFERRED"))

            # ADF activity → notebook / pipeline
            if node.type == NodeType.ADF_ACTIVITY:
                nb_path3: str | None = meta.get("notebook_path")
                if nb_path3:
                    target_id = self._resolve_path(nb_path3, all_nb_indexes, prefixes)
                    if target_id:
                        self.add_edge(Edge(node.id, target_id, EdgeType.EXECUTES, "EXTRACTED"))

            # GitHub Actions step → Databricks job
            if node.type == NodeType.GITHUB_ACTION_STEP:
                job_name2: str | None = meta.get("databricks_job_name")
                if job_name2:
                    jid = job_index.get(job_name2.lower())
                    if jid:
                        self.add_edge(Edge(node.id, jid, EdgeType.TRIGGERS, "EXTRACTED"))
                adf_run: str | None = meta.get("adf_pipeline_name")
                if adf_run:
                    pid = adf_pipeline_index.get(adf_run.lower())
                    if pid:
                        self.add_edge(Edge(node.id, pid, EdgeType.TRIGGERS, "EXTRACTED"))
                for model_name in meta.get("dbt_models", []):
                    mid = dbt_model_index.get(model_name.lower())
                    if mid:
                        self.add_edge(Edge(node.id, mid, EdgeType.EXECUTES, "EXTRACTED"))

            # Fabric pipeline activity → fabric notebook / lakehouse
            if node.type == NodeType.FABRIC_PIPELINE_ACTIVITY:
                nb_path4: str | None = meta.get("notebook_path")
                if nb_path4:
                    target_id = self._resolve_path(nb_path4, fabric_nb_index, prefixes)
                    if target_id:
                        self.add_edge(Edge(node.id, target_id, EdgeType.EXECUTES, "EXTRACTED"))
                lakehouse_name: str | None = meta.get("lakehouse_name")
                if lakehouse_name:
                    lid = lakehouse_index.get(lakehouse_name.lower())
                    if lid:
                        self.add_edge(Edge(node.id, lid, EdgeType.READS_FROM, "INFERRED"))

        # CONTAINS: link LAKEFLOW_PIPELINE nodes to LAKEFLOW_DATASET nodes
        # by matching the pipeline name in the dataset's file path segments.
        # This handles pyspark.pipelines scripts whose datasets are discovered
        # independently from the pipeline YAML.
        for pipeline_node in [n for n in self._nodes.values() if n.type == NodeType.LAKEFLOW_PIPELINE]:
            pipe_name_lower = pipeline_node.name.lower()
            for ds_node in [n for n in self._nodes.values() if n.type == NodeType.LAKEFLOW_DATASET]:
                if ds_node.file_path:
                    path_parts = [p.lower() for p in Path(ds_node.file_path).parts]
                    if pipe_name_lower in path_parts:
                        self.add_edge(Edge(pipeline_node.id, ds_node.id, EdgeType.CONTAINS, "INFERRED"))

        # SCHEDULED_BY: for TABLE nodes written by tasks trace back to job/DAG
        self._resolve_scheduled_by()

    def _resolve_scheduled_by(self) -> None:
        """Add SCHEDULED_BY edges from storage nodes to their responsible orchestrators."""
        storage_types = {
            NodeType.TABLE, NodeType.VIEW, NodeType.DBT_MODEL,
            NodeType.LAKEFLOW_DATASET, NodeType.FABRIC_LAKEHOUSE,
        }
        for node in self._nodes.values():
            if node.type not in storage_types:
                continue
            orchestrators = [
                self._nodes[n]
                for n in nx.ancestors(self._g, node.id)
                if self._nodes.get(n) and self._nodes[n].type in ORCHESTRATOR_NODE_TYPES
            ]
            for orch in orchestrators:
                self.add_edge(Edge(node.id, orch.id, EdgeType.SCHEDULED_BY, "INFERRED"))

    def _build_path_index(self, ntype: NodeType) -> dict[str, str]:
        """Map normalised file-path stems → node IDs for a given type."""
        idx: dict[str, str] = {}
        for nid, node in self._nodes.items():
            if node.type == ntype and node.file_path:
                stem = Path(node.file_path).stem.lower()
                idx[stem] = nid
                idx[node.file_path.lower()] = nid
        return idx

    def _build_name_index(self, ntype: NodeType) -> dict[str, str]:
        return {
            node.name.lower(): nid
            for nid, node in self._nodes.items()
            if node.type == ntype
        }

    def _resolve_path(
        self, raw_path: str, idx: dict[str, str], prefixes: list[str]
    ) -> str | None:
        normalised = raw_path
        for prefix in prefixes:
            if normalised.startswith(prefix):
                normalised = normalised[len(prefix):]
                # strip /<email>/ pattern after /Users
                parts = normalised.lstrip("/").split("/", 1)
                if len(parts) == 2 and "@" in parts[0]:
                    normalised = "/" + parts[1]
                break
        normalised = normalised.lower().lstrip("/")
        # Try full path match
        if normalised in idx:
            return idx[normalised]
        # Try path suffix matching
        for key, nid in idx.items():
            if key.endswith(normalised) or normalised.endswith(key):
                return nid
        # Try filename stem only
        stem = Path(normalised).stem
        return idx.get(stem)

    # ------------------------------------------------------------------
    # Traversal & analysis
    # ------------------------------------------------------------------

    def upstream(self, node_id: str, depth: int = 10) -> list[Node]:
        """Return nodes that are upstream data sources of *node_id*.

        READS_FROM edges are stored as consumer → source (e.g. gold → silver),
        so upstream sources are reachable via ``nx.descendants``.
        """
        return [
            self._nodes[n]
            for n in nx.descendants(self._g, node_id)
            if n in self._nodes
        ]

    def downstream(self, node_id: str, depth: int = 10) -> list[Node]:
        """Return nodes that consume *node_id* (downstream consumers).

        Consumers have edges pointing TO *node_id* via READS_FROM, so they
        appear as ``nx.ancestors`` of this node.
        """
        return [
            self._nodes[n]
            for n in nx.ancestors(self._g, node_id)
            if n in self._nodes
        ]

    def impact_analysis(self, node_id: str) -> dict[str, Any]:
        node = self._nodes.get(node_id)
        # Direct consumers: nodes whose edge points TO node_id (predecessors)
        direct = [self._nodes[n] for n in self._g.predecessors(node_id) if n in self._nodes]
        # All transitive consumers
        all_down = [self._nodes[n] for n in nx.ancestors(self._g, node_id) if n in self._nodes]
        return {
            "node": node,
            "directly_affected": direct,
            "transitively_affected": all_down,
        }

    def schedule_for(self, node_id: str) -> list[Node]:
        """Return all orchestrators responsible for refreshing this node."""
        return [
            self._nodes[n]
            for n in nx.ancestors(self._g, node_id)
            if self._nodes.get(n) and self._nodes[n].type in ORCHESTRATOR_NODE_TYPES
        ]

    def execution_order(self, job_id: str) -> list[list[Node]]:
        """Return topological task stages for a job or DAG (parallel tasks in same stage)."""
        task_ids = [
            n
            for n in self._g.successors(job_id)
            if self._nodes.get(n) and self._nodes[n].type in TASK_NODE_TYPES
        ]
        if not task_ids:
            return []
        subgraph = self._g.subgraph(task_ids)
        return [
            [self._nodes[n] for n in gen if n in self._nodes]
            for gen in nx.topological_generations(subgraph)
        ]

    def god_nodes(self, top_n: int = 10) -> list[tuple[Node, int]]:
        """Most-connected nodes by total degree."""
        scored = [
            (self._nodes[n], self._g.degree(n))
            for n in self._g.nodes
            if n in self._nodes
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def shortest_path(self, source_id: str, target_id: str) -> list[Node]:
        try:
            path = nx.shortest_path(self._g, source_id, target_id)
            return [self._nodes[n] for n in path if n in self._nodes]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def nodes_by_layer(self) -> dict[str, list[Node]]:
        result: dict[str, list[Node]] = {}
        for node in self._nodes.values():
            result.setdefault(node.layer.value, []).append(node)
        return result

    def orphan_nodes(self) -> list[Node]:
        return [
            self._nodes[n]
            for n in self._g.nodes
            if self._g.degree(n) == 0 and n in self._nodes
        ]

    # ------------------------------------------------------------------
    # Graph views
    # ------------------------------------------------------------------

    def lineage_subgraph(self) -> nx.DiGraph:
        return nx.subgraph_view(
            self._g,
            filter_edge=lambda u, v: self._g[u][v].get("type") in LINEAGE_EDGE_TYPES,
        )

    def orchestration_subgraph(self) -> nx.DiGraph:
        return nx.subgraph_view(
            self._g,
            filter_edge=lambda u, v: self._g[u][v].get("type") in ORCHESTRATION_EDGE_TYPES,
        )

    def find_node(self, name_or_id: str) -> Node | None:
        """Find by ID or by name (case-insensitive)."""
        if name_or_id in self._nodes:
            return self._nodes[name_or_id]
        lower = name_or_id.lower()
        for node in self._nodes.values():
            if node.name.lower() == lower:
                return node
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": sorted(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "type": n.type.value,
                        "layer": n.layer.value,
                        "file_path": n.file_path,
                        "description": n.description,
                        "tags": n.tags,
                        "metadata": n.metadata,
                    }
                    for n in self._nodes.values()
                ],
                key=lambda x: x["id"],
            ),
            "edges": sorted(
                [
                    {
                        "source": e.source_id,
                        "target": e.target_id,
                        "type": e.type.value,
                        "confidence": e.confidence,
                    }
                    for e in self._edges
                ],
                key=lambda x: (x["source"], x["target"], x["type"]),
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataGraph":
        g = cls()
        type_map = {nt.value: nt for nt in NodeType}
        layer_map = {dl.value: dl for dl in DataLayer}
        edge_map = {et.value: et for et in EdgeType}
        for nd in data.get("nodes", []):
            g.add_node(
                Node(
                    id=nd["id"],
                    name=nd["name"],
                    type=type_map.get(nd["type"], NodeType.DOC_FILE),
                    layer=layer_map.get(nd.get("layer", "unknown"), DataLayer.UNKNOWN),
                    file_path=nd.get("file_path"),
                    description=nd.get("description"),
                    tags=nd.get("tags", []),
                    metadata=nd.get("metadata", {}),
                )
            )
        for ed in data.get("edges", []):
            et = edge_map.get(ed["type"])
            if et:
                g.add_edge(
                    Edge(
                        source_id=ed["source"],
                        target_id=ed["target"],
                        type=et,
                        confidence=ed.get("confidence", "EXTRACTED"),
                    )
                )
        return g

    @classmethod
    def load(cls, path: Path) -> "DataGraph":
        data = json.loads(path.read_text())
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, int]:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
        }
