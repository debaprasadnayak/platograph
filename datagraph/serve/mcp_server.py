"""MCP stdio server exposing datagraph tools to AI assistants."""

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
        "metadata": node.metadata,
    }


def _tool_result(content: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(content, indent=2)}]}


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

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="query_graph",
                description="Answer a natural language question about the data platform graph.",
                inputSchema={
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                },
            ),
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

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result: Any

        if name == "query_graph":
            from datagraph.rag.retriever import retrieve
            from datagraph.rag.synthesizer import synthesize
            question = arguments["question"]
            nodes = retrieve(graph, question, top_k=10)  # already list[dict]
            answer = synthesize(question, nodes)
            result = {"answer": answer}

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
