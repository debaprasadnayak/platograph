"""Louvain community clustering for the DataGraph."""

from __future__ import annotations

from typing import TYPE_CHECKING

import community as community_louvain  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datagraph.graph import DataGraph


def cluster(graph: "DataGraph", resolution: float = 1.0) -> dict[str, int]:
    """
    Run Louvain community detection on the undirected projection of the graph.
    Returns a mapping of node_id → cluster_id.
    Updates each node's metadata with 'cluster' key.
    """
    undirected = graph._g.to_undirected()
    if len(undirected.nodes) == 0:
        return {}

    partition: dict[str, int] = community_louvain.best_partition(
        undirected, resolution=resolution, randomize=False
    )

    for node_id, cluster_id in partition.items():
        if node_id in graph._nodes:
            graph._nodes[node_id].metadata["cluster"] = cluster_id

    return partition
