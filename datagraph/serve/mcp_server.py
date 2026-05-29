"""MCP stdio server exposing datagraph tools to AI assistants.

Design philosophy:
  - Tools that previously required an internal LLM call (query_graph, enrich_doc)
    now return **context + instructions** so the CALLING AI assistant (GitHub Copilot,
    Claude Code, etc.) can answer/generate directly — no API key needed on this side.
  - Users WITH API keys can still run `platograph query` / `platograph scan --enrich-llm`
    directly in the terminal for the same functionality.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load_graph(graph_json: Path):
    from datagraph.graph import DataGraph
    return DataGraph.load(graph_json)


def _node_to_dict(node) -> dict:
    """Serialize a Node dataclass to a JSON-safe dict."""
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type.value,
        "layer": node.layer.value,
        "file_path": node.file_path,
        "description": node.description,
        "tags": node.tags,
        "metadata": {k: v for k, v in (node.metadata or {}).items() if k != "markdown_text"},
    }


def _node_to_compact(node) -> dict:
    """Minimal node dict for context (saves tokens)."""
    d: dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": node.type.value,
        "layer": node.layer.value,
    }
    if node.description:
        d["description"] = node.description
    return d


def _edges_for_nodes(graph, node_ids: set[str]) -> list[dict]:
    """Return edges where both endpoints are in node_ids."""
    edges = []
    for u, v, data in graph._g.edges(data=True):
        if u in node_ids and v in node_ids:
            edges.append({
                "source": u,
                "target": v,
                "type": data.get("edge_type", "unknown"),
            })
    return edges


def serve(graph_json: Path) -> None:
    """Run an MCP stdio server backed by graph_json."""
    try:
        from mcp.server import Server  # type: ignore[import-untyped]
        from mcp.server.stdio import stdio_server  # type: ignore[import-untyped]
        import mcp.types as types  # type: ignore[import-untyped]
    except ImportError:
        print("Install mcp: pip install mcp", file=sys.stderr)
        sys.exit(1)

    graph = _load_graph(graph_json)
    server = Server("platograph")

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            # ── LLM-powered (context returned to calling AI) ─────────
            types.Tool(
                name="query_graph",
                description=(
                    "Retrieve relevant nodes and edges from the data platform knowledge graph "
                    "for a natural-language question. Returns graph context that YOU (the AI "
                    "assistant) should use to answer the user's question. No API key needed."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The user's natural-language question about the data platform.",
                        },
                    },
                    "required": ["question"],
                },
            ),
            types.Tool(
                name="list_docs_for_enrichment",
                description=(
                    "List documents in the graph that can be enriched with LLM-extracted "
                    "entities. Returns doc IDs and titles. Call enrich_document for each one."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            types.Tool(
                name="enrich_document",
                description=(
                    "Return a document's text and extraction instructions. YOU (the AI "
                    "assistant) should read the text, extract data platform entities and "
                    "relationships, then call apply_enrichment with the result. No API key needed."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "The node ID of the document to enrich.",
                        },
                    },
                    "required": ["doc_id"],
                },
            ),
            types.Tool(
                name="apply_enrichment",
                description=(
                    "Apply LLM-extracted entities and edges to the graph. Call this after "
                    "enrich_document with the structured JSON you extracted from the document."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "The node ID of the source document.",
                        },
                        "entities": {
                            "type": "object",
                            "description": "JSON with 'nodes' and 'edges' arrays extracted from the document.",
                            "properties": {
                                "nodes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "type": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["id", "name", "type"],
                                    },
                                },
                                "edges": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source_id": {"type": "string"},
                                            "target_id": {"type": "string"},
                                            "type": {"type": "string"},
                                        },
                                        "required": ["source_id", "target_id", "type"],
                                    },
                                },
                            },
                        },
                    },
                    "required": ["doc_id", "entities"],
                },
            ),
            # ── Graph navigation (no LLM needed) ─────────────────────
            types.Tool(
                name="get_node",
                description="Return metadata for a single node by ID or name.",
                inputSchema={
                    "type": "object",
                    "properties": {"node_id": {"type": "string"}},
                    "required": ["node_id"],
                },
            ),
            types.Tool(
                name="get_neighbors",
                description="Return upstream or downstream neighbours of a node.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "direction": {"type": "string", "enum": ["upstream", "downstream", "both"]},
                        "depth": {"type": "integer", "default": 1},
                    },
                    "required": ["node_id"],
                },
            ),
            types.Tool(
                name="shortest_path",
                description="Return the shortest path between two nodes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                    },
                    "required": ["source", "target"],
                },
            ),
            types.Tool(
                name="impact_analysis",
                description="List all downstream nodes that would be affected if this node changes.",
                inputSchema={
                    "type": "object",
                    "properties": {"node_id": {"type": "string"}},
                    "required": ["node_id"],
                },
            ),
            types.Tool(
                name="schedule_for",
                description="Show what schedule/orchestrator runs a given asset.",
                inputSchema={
                    "type": "object",
                    "properties": {"asset_name": {"type": "string"}},
                    "required": ["asset_name"],
                },
            ),
            types.Tool(
                name="execution_order",
                description="Return the topological execution order of tasks in a job or DAG.",
                inputSchema={
                    "type": "object",
                    "properties": {"job_name": {"type": "string"}},
                    "required": ["job_name"],
                },
            ),
            types.Tool(
                name="list_prs",
                description="List open pull requests and their blast-radius in the graph.",
                inputSchema={
                    "type": "object",
                    "properties": {"repo": {"type": "string"}},
                    "required": ["repo"],
                },
            ),
            types.Tool(
                name="pr_impact",
                description="Show which graph nodes are affected by a specific PR.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "pr_number": {"type": "integer"},
                    },
                    "required": ["repo", "pr_number"],
                },
            ),
        ]

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result: Any

        # ── LLM-powered tools (context returned for the calling AI) ──

        if name == "query_graph":
            result = _handle_query_graph(graph, arguments)

        elif name == "list_docs_for_enrichment":
            result = _handle_list_docs(graph)

        elif name == "enrich_document":
            result = _handle_enrich_document(graph, arguments)

        elif name == "apply_enrichment":
            result = _handle_apply_enrichment(graph, graph_json, arguments)

        # ── Graph navigation tools (no LLM) ──────────────────────────

        elif name == "get_node":
            node = graph.find_node(arguments["node_id"])
            result = _node_to_dict(node) if node else {"error": "node not found"}

        elif name == "get_neighbors":
            nid = arguments["node_id"]
            direction = arguments.get("direction", "both")
            depth = int(arguments.get("depth", 1))
            up = graph.upstream(nid, depth) if direction in ("upstream", "both") else []
            dn = graph.downstream(nid, depth) if direction in ("downstream", "both") else []
            seen: dict[str, Any] = {}
            for n in up + dn:
                seen[n.id] = _node_to_dict(n)
            result = {"neighbors": list(seen.values())}

        elif name == "shortest_path":
            path_nodes = graph.shortest_path(arguments["source"], arguments["target"])
            result = {"path": [_node_to_dict(n) for n in path_nodes]}

        elif name == "impact_analysis":
            raw = graph.impact_analysis(arguments["node_id"])
            result = {
                "node": _node_to_dict(raw["node"]) if raw.get("node") else None,
                "directly_affected": [_node_to_dict(n) for n in raw.get("directly_affected", [])],
                "transitively_affected": [_node_to_dict(n) for n in raw.get("transitively_affected", [])],
            }

        elif name == "schedule_for":
            info = graph.schedule_for(arguments["asset_name"])
            result = {"schedule": [_node_to_dict(n) for n in info]} if info else {"message": "no schedule found"}

        elif name == "execution_order":
            stages = graph.execution_order(arguments["job_name"])
            result = {"stages": [[_node_to_dict(n) for n in stage] for stage in stages]}

        elif name == "list_prs":
            from datagraph.analysis.pr_triage import list_open_prs
            prs = list_open_prs(arguments["repo"])
            result = {"prs": prs}

        elif name == "pr_impact":
            from datagraph.analysis.pr_triage import pr_blast_radius
            result = pr_blast_radius(graph, arguments["repo"], arguments["pr_number"])

        else:
            result = {"error": f"unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    import asyncio

    async def _main():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())

    asyncio.run(_main())


# ---------------------------------------------------------------------------
# LLM-powered tool handlers (return context for the calling AI)
# ---------------------------------------------------------------------------

def _handle_query_graph(graph, arguments: dict) -> dict:
    """Retrieve relevant context and return it for the calling AI to answer."""
    from datagraph.rag.retriever import retrieve

    question = arguments["question"]
    nodes = retrieve(graph, question, top_k=12)

    # Build edges between retrieved nodes for richer context
    node_ids = {n["id"] for n in nodes}
    edges = _edges_for_nodes(graph, node_ids)

    return {
        "instructions": (
            "Use the graph context below to answer the user's question. "
            "Cite node IDs when referencing specific assets. "
            "If the context doesn't contain enough information, say so clearly. "
            "Do NOT hallucinate table names, jobs, or relationships not present in the context."
        ),
        "question": question,
        "graph_context": {
            "nodes": nodes,
            "edges": edges,
        },
        "summary": f"{len(nodes)} relevant nodes, {len(edges)} connecting edges retrieved.",
    }


def _handle_list_docs(graph) -> dict:
    """Return documents that have markdown text available for enrichment."""
    from datagraph.models import NodeType

    docs = []
    for node in graph._nodes.values():
        if node.type == NodeType.DOC_FILE and node.metadata.get("markdown_text"):
            docs.append({
                "id": node.id,
                "name": node.name,
                "description": node.description or "",
                "file_path": node.file_path,
                "text_length": len(str(node.metadata.get("markdown_text", ""))),
            })

    return {
        "documents": docs,
        "count": len(docs),
        "instructions": (
            "Each document can be enriched by calling enrich_document with its ID. "
            "The tool will return the document text and extraction instructions."
        ),
    }


def _handle_enrich_document(graph, arguments: dict) -> dict:
    """Return document text + extraction prompt for the calling AI."""
    doc_id = arguments["doc_id"]
    node = graph.find_node(doc_id)
    if not node:
        return {"error": f"Document node '{doc_id}' not found."}

    text = str(node.metadata.get("markdown_text", ""))
    if not text:
        return {"error": f"Document '{doc_id}' has no markdown_text to enrich."}

    # Truncate very long docs to avoid token overflow
    if len(text) > 50_000:
        text = text[:50_000] + "\n\n... (truncated at 50k characters)"

    return {
        "doc_id": doc_id,
        "doc_name": node.name,
        "document_text": text,
        "extraction_instructions": (
            "Read the document text above and extract data platform entities and "
            "their relationships. Return ONLY entities explicitly named in the text.\n\n"
            "After extracting, call the apply_enrichment tool with this doc_id and "
            "the extracted entities in this exact JSON structure:\n"
            "{\n"
            '  "nodes": [\n'
            '    {"id": "snake_case_id", "name": "Human Readable Name",\n'
            '     "type": "table|view|pipeline|job|notebook|system|api|model",\n'
            '     "description": "one-line description"}\n'
            "  ],\n"
            '  "edges": [\n'
            '    {"source_id": "snake_case_id", "target_id": "snake_case_id",\n'
            '     "type": "reads_from|writes_to|references|depends_on"}\n'
            "  ]\n"
            "}\n\n"
            "If no entities are found, return: {\"nodes\": [], \"edges\": []}"
        ),
    }


def _handle_apply_enrichment(graph, graph_json: Path, arguments: dict) -> dict:
    """Apply extracted entities/edges to the graph and persist."""
    from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

    doc_id = arguments["doc_id"]
    entities = arguments.get("entities", {})

    if not graph.find_node(doc_id):
        return {"error": f"Document node '{doc_id}' not found."}

    _TYPE_MAP: dict[str, NodeType] = {
        "table":    NodeType.TABLE,
        "dataset":  NodeType.TABLE,
        "view":     NodeType.VIEW,
        "pipeline": NodeType.LAKEFLOW_PIPELINE,
        "job":      NodeType.DATABRICKS_JOB,
        "notebook": NodeType.NOTEBOOK,
        "system":   NodeType.TABLE,
        "api":      NodeType.TABLE,
        "model":    NodeType.DBT_MODEL,
    }
    _EDGE_MAP: dict[str, EdgeType] = {
        "reads_from":  EdgeType.READS_FROM,
        "writes_to":   EdgeType.WRITES_TO,
        "references":  EdgeType.REFERENCES,
        "depends_on":  EdgeType.DEPENDS_ON,
    }

    added_nodes = 0
    added_edges = 0
    id_map: dict[str, str] = {}

    # Add nodes
    for item in entities.get("nodes", []):
        llm_id = str(item.get("id", "")).strip()
        if not llm_id:
            continue
        node_type = _TYPE_MAP.get(item.get("type", ""), NodeType.TABLE)
        node = Node(
            id=llm_id,
            name=item.get("name", llm_id),
            type=node_type,
            layer=DataLayer.UNKNOWN,
            description=item.get("description"),
            tags=["llm_enriched"],
        )
        graph.add_node(node)
        id_map[llm_id] = node.id
        added_nodes += 1

        # REFERENCES edge from doc → entity
        graph.add_edge(Edge(doc_id, node.id, EdgeType.REFERENCES, "LLM_INFERRED"))
        added_edges += 1

    # Add inter-entity edges
    for item in entities.get("edges", []):
        src = id_map.get(item.get("source_id", ""))
        tgt = id_map.get(item.get("target_id", ""))
        if src and tgt:
            edge_type = _EDGE_MAP.get(item.get("type", ""), EdgeType.DEPENDS_ON)
            graph.add_edge(Edge(src, tgt, edge_type, "LLM_INFERRED"))
            added_edges += 1

    # Persist updated graph
    try:
        from datagraph.output import json_export
        json_export.export(graph, graph_json.parent)
    except Exception as exc:
        return {
            "warning": f"Enrichment applied in memory but save failed: {exc}",
            "added_nodes": added_nodes,
            "added_edges": added_edges,
        }

    return {
        "success": True,
        "doc_id": doc_id,
        "added_nodes": added_nodes,
        "added_edges": added_edges,
        "message": f"Added {added_nodes} nodes and {added_edges} edges from '{doc_id}'. Graph saved.",
    }
