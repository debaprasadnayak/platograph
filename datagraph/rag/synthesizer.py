"""LLM synthesizer — answers questions using retrieved graph context."""

from __future__ import annotations

import json
from typing import Any

from datagraph.llm_backend import call_llm, detect_backend


SYSTEM_PROMPT = """You are a data platform expert assistant. You have access to a knowledge graph
of the user's data platform. Answer the user's question using ONLY the provided graph context.
Cite node IDs in your answer. If you cannot answer from the context, say so clearly.
Do not hallucinate table names, job names, or relationships not present in the context."""


def synthesize(
    question: str,
    retrieved_nodes: list[dict[str, Any]],
    edges_context: list[dict[str, Any]] | None = None,
    backend: str = "auto",
) -> str:
    """
    Generate an answer using retrieved nodes as context.
    Falls back to a structured summary if no LLM backend is available.
    """
    context = json.dumps({"nodes": retrieved_nodes, "edges": edges_context or []}, indent=2)
    # Truncate if too long (rough 60k token guard)
    if len(context) > 80_000:
        context = context[:80_000] + "\n... (truncated)"

    messages = [
        {"role": "user", "content": f"Graph context:\n{context}\n\nQuestion: {question}"},
    ]

    backend = detect_backend(backend)

    if backend == "none":
        return _fallback_summary(question, retrieved_nodes)

    try:
        return call_llm(messages, system=SYSTEM_PROMPT, backend=backend, max_tokens=2048)
    except Exception as exc:
        return f"LLM call failed ({backend}): {exc}\n\n" + _fallback_summary(question, retrieved_nodes)




def _fallback_summary(question: str, nodes: list[dict]) -> str:
    if not nodes:
        return "No matching nodes found in the graph for your question."
    lines = [f"Found {len(nodes)} relevant nodes:\n"]
    for n in nodes[:15]:
        lines.append(f"  • [{n['type']}] {n['name']} (layer: {n['layer']}) — {n.get('description') or 'no description'}")
    if len(nodes) > 15:
        lines.append(f"  ... and {len(nodes) - 15} more")
    return "\n".join(lines)
