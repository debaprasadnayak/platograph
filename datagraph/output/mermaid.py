"""Mermaid diagram generator — lineage.mermaid + orchestration.mermaid."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datagraph.graph import DataGraph

from datagraph.models import LINEAGE_EDGE_TYPES, ORCHESTRATION_EDGE_TYPES, ORCHESTRATOR_NODE_TYPES


def _safe_id(node_id: str) -> str:
    """Make node_id safe for Mermaid (no special chars)."""
    return node_id.replace("/", "_").replace(".", "_").replace("-", "_").replace(" ", "_")


def export_lineage(graph: "DataGraph", output_dir: Path, max_nodes: int = 50) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "lineage.mermaid"

    # Pick top N nodes by degree
    all_nodes = list(graph._nodes.values())
    all_nodes.sort(key=lambda n: graph._g.degree(n.id), reverse=True)
    top_nodes = all_nodes[:max_nodes]
    shown = {n.id for n in top_nodes}

    lines = ["flowchart LR"]
    for n in top_nodes:
        nid = _safe_id(n.id)
        label = n.name.replace('"', "'")
        lines.append(f'    {nid}["{label}"]')

    for edge in graph._edges:
        if edge.type not in LINEAGE_EDGE_TYPES:
            continue
        if edge.source_id not in shown or edge.target_id not in shown:
            continue
        src = _safe_id(edge.source_id)
        tgt = _safe_id(edge.target_id)
        label = edge.type.value
        lines.append(f"    {src} -->|{label}| {tgt}")

    out_path.write_text("\n".join(lines) + "\n")
    return out_path


def export_orchestration(graph: "DataGraph", output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "orchestration.mermaid"

    orchestrator_ids = {
        n.id for n in graph._nodes.values() if n.type in ORCHESTRATOR_NODE_TYPES
    }

    lines = ["flowchart TD"]
    shown: set[str] = set()

    # Group tasks inside orchestrator subgraphs
    subgraph_members: dict[str, list[str]] = {}
    for edge in graph._edges:
        if edge.type.value in ("contains", "part_of") and edge.source_id in orchestrator_ids:
            subgraph_members.setdefault(edge.source_id, []).append(edge.target_id)
            shown.add(edge.source_id)
            shown.add(edge.target_id)

    # Emit standalone orchestrators not captured above
    for nid in orchestrator_ids:
        shown.add(nid)

    for orch_id, members in subgraph_members.items():
        safe_orch = _safe_id(orch_id)
        orch_label = graph._nodes[orch_id].name.replace('"', "'")
        lines.append(f'    subgraph {safe_orch} ["{orch_label}"]')
        for m in members:
            if m in graph._nodes:
                mnode = graph._nodes[m]
                lines.append(f'        {_safe_id(m)}["{mnode.name}"]')
        lines.append("    end")

    for nid in orchestrator_ids - set(subgraph_members.keys()):
        n = graph._nodes[nid]
        lines.append(f'    {_safe_id(nid)}["{n.name}"]')

    for edge in graph._edges:
        if edge.type not in ORCHESTRATION_EDGE_TYPES:
            continue
        if edge.source_id not in shown or edge.target_id not in shown:
            continue
        src = _safe_id(edge.source_id)
        tgt = _safe_id(edge.target_id)
        label = edge.type.value
        lines.append(f"    {src} -->|{label}| {tgt}")

    out_path.write_text("\n".join(lines) + "\n")
    return out_path
