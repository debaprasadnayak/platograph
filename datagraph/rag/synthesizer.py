"""LLM synthesizer — answers questions using retrieved graph context."""

from __future__ import annotations

import json
import os
from typing import Any


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

    backend = _detect_backend(backend)

    if backend == "anthropic":
        return _call_anthropic(messages)
    if backend in ("openai", "azure_openai"):
        return _call_openai(messages, backend == "azure_openai")
    if backend == "databricks":
        return _call_databricks(messages)

    # No LLM available — return structured summary
    return _fallback_summary(question, retrieved_nodes)


def _detect_backend(backend: str) -> str:
    if backend != "auto":
        return backend
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure_openai"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        return "databricks"
    return "none"


def _call_anthropic(messages: list[dict]) -> str:
    try:
        import anthropic
    except ImportError:
        return _fallback_summary("", [])
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def _call_openai(messages: list[dict], azure: bool = False) -> str:
    try:
        if azure:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
                azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            )
            model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        else:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            model = "gpt-4o"
        all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        resp = client.chat.completions.create(model=model, messages=all_messages, max_tokens=2048)
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"Error calling OpenAI: {e}"


def _call_databricks(messages: list[dict]) -> str:
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
        w = WorkspaceClient()
        endpoint = os.environ.get("DATABRICKS_SERVING_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
        resp = w.serving_endpoints.query(
            name=endpoint,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"Error calling Databricks endpoint: {e}"


def _fallback_summary(question: str, nodes: list[dict]) -> str:
    if not nodes:
        return "No matching nodes found in the graph for your question."
    lines = [f"Found {len(nodes)} relevant nodes:\n"]
    for n in nodes[:15]:
        lines.append(f"  • [{n['type']}] {n['name']} (layer: {n['layer']}) — {n.get('description') or 'no description'}")
    if len(nodes) > 15:
        lines.append(f"  ... and {len(nodes) - 15} more")
    return "\n".join(lines)
