"""Hybrid graph retriever: keyword + graph expansion."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datagraph.graph import DataGraph


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve(
    graph: "DataGraph",
    question: str,
    top_k: int = 10,
    hop_depth: int = 2,
    embedder: Any = None,
) -> list[dict[str, Any]]:
    """
    Hybrid retrieval:
    1. Keyword match on node name + description
    2. Optional vector similarity if embedder is available
    3. Ego-graph expansion (hop_depth hops from seed nodes)
    4. Re-rank by degree (connectivity proxy for importance)
    Returns list of serialisable node dicts.
    """
    import networkx as nx

    lower_q = question.lower()
    keywords = set(lower_q.split())

    # ── Step 1: Keyword seed ─────────────────────────────────────────
    scored: list[tuple[float, str]] = []
    for node_id, node in graph._nodes.items():
        score = 0.0
        text = f"{node.name} {node.description or ''} {node.type.value}".lower()
        for kw in keywords:
            if kw in text:
                score += 1.0
        if score > 0:
            scored.append((score, node_id))

    # ── Step 2: Vector similarity (optional) ─────────────────────────
    if embedder is not None:
        try:
            q_vec = embedder.embed([question])[0]
            for node_id, node in graph._nodes.items():
                node_text = f"{node.name} {node.description or ''} {node.layer.value}"
                n_vecs = embedder.embed([node_text])
                sim = _cosine(q_vec, n_vecs[0])
                if sim > 0.7:
                    scored.append((sim, node_id))
        except Exception:
            pass

    # Deduplicate and keep top_k seeds
    seen: set[str] = set()
    seeds: list[str] = []
    for _, nid in sorted(scored, reverse=True):
        if nid not in seen:
            seeds.append(nid)
            seen.add(nid)
        if len(seeds) >= top_k:
            break

    # ── Step 3: Ego-graph expansion ──────────────────────────────────
    expanded: set[str] = set(seeds)
    for seed in seeds:
        try:
            ego = nx.ego_graph(graph._g, seed, radius=hop_depth, undirected=True)
            expanded.update(ego.nodes)
        except Exception:
            pass

    # ── Step 4: Re-rank by degree ────────────────────────────────────
    result_nodes = [
        graph._nodes[nid] for nid in expanded if nid in graph._nodes
    ]
    result_nodes.sort(key=lambda n: graph._g.degree(n.id), reverse=True)
    result_nodes = result_nodes[: top_k * 3]

    return [
        {
            "id": n.id,
            "name": n.name,
            "type": n.type.value,
            "layer": n.layer.value,
            "description": n.description,
            "file_path": n.file_path,
        }
        for n in result_nodes
    ]
