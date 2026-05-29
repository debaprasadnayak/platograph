"""LINEAGE_REPORT.md generator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datagraph.graph import DataGraph

from datagraph.models import ORCHESTRATOR_NODE_TYPES


def export(graph: "DataGraph", output_dir: Path, project_name: str = "unknown") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "LINEAGE_REPORT.md"

    summary = graph.summary()
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"# Platograph Lineage Report",
        f"",
        f"**Project**: {project_name}  ",
        f"**Generated**: {now}  ",
        f"**Nodes**: {summary['nodes']}  **Edges**: {summary['edges']}  **Clusters**: {summary.get('clusters', '—')}",
        f"",
        "---",
        "",
    ]

    # God nodes
    god = graph.god_nodes(top_n=20)
    lines += ["## God Nodes (high-fan-out)", ""]
    if god:
        lines += ["| Node | Type | Layer | Degree |", "| --- | --- | --- | --- |"]
        for n, deg in god[:20]:
            lines.append(f"| `{n.name}` | {n.type.value} | {n.layer.value} | {deg} |")
    else:
        lines.append("_None found._")
    lines.append("")

    # Layer summary
    lines += ["## Layer Summary", ""]
    by_layer = graph.nodes_by_layer()
    if by_layer:
        lines += ["| Layer | Count |", "| --- | --- |"]
        for layer, nodes in sorted(by_layer.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| {layer} | {len(nodes)} |")
    lines.append("")

    # Orchestration summary
    orch_nodes = [n for n in graph._nodes.values() if n.type in ORCHESTRATOR_NODE_TYPES]
    lines += ["## Orchestration Summary", ""]
    if orch_nodes:
        lines += ["| Name | Type | Schedule | Tasks |", "| --- | --- | --- | --- |"]
        for n in orch_nodes[:30]:
            schedule = n.metadata.get("schedule", "—") if n.metadata else "—"
            task_count = sum(
                1 for e in graph._edges
                if e.source_id == n.id and e.type.value in ("contains", "part_of")
            )
            lines.append(f"| `{n.name}` | {n.type.value} | {schedule} | {task_count} |")
    else:
        lines.append("_No orchestrators found._")
    lines.append("")

    # Orphan nodes
    orphans = graph.orphan_nodes()
    lines += ["## Orphan Nodes (no edges)", ""]
    if orphans:
        for n in orphans[:20]:
            lines.append(f"- `{n.name}` ({n.type.value})")
        if len(orphans) > 20:
            lines.append(f"- _... and {len(orphans) - 20} more_")
    else:
        lines.append("_None found._")
    lines.append("")

    # Suggested questions
    lines += [
        "## Suggested Questions",
        "",
        "Use `platograph query` to explore:",
        "",
    ]
    suggestions = [
        "Which tables have no downstream consumers?",
        "What jobs write to the gold layer?",
        "Which pipelines run on a daily schedule?",
        "What is the blast radius of the orders table?",
        "Show me all assets without a description.",
    ]
    for s in suggestions:
        lines.append(f"- {s}")

    out_path.write_text("\n".join(lines) + "\n")
    return out_path
