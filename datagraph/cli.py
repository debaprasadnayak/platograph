"""CLI entry point for platograph / datagraph."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
@click.version_option(package_name="platograph")
def main() -> None:
    """Platograph — data-platform knowledge graph for Databricks + Fabric."""


# ─── scan ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("project_path", default=".", type=click.Path(exists=True))
@click.option("--out", default="datagraph-out", show_default=True, help="Output directory.")
@click.option("--dialect", default="databricks", show_default=True, help="SQL dialect (databricks|tsql|spark|ansi).")
@click.option("--no-viz", is_flag=True, help="Skip HTML visualisation.")
@click.option("--no-report", is_flag=True, help="Skip LINEAGE_REPORT.md.")
@click.option("--enrich-llm", is_flag=True, help="Enrich descriptions using LLM.")
@click.option("--live-uc", is_flag=True, help="Fetch live Unity Catalog metadata.")
@click.option("--live-jobs", is_flag=True, help="Fetch live Databricks Jobs.")
@click.option("--update", is_flag=True, help="Merge into existing graph.json.")
def scan(
    project_path: str,
    out: str,
    dialect: str,
    no_viz: bool,
    no_report: bool,
    enrich_llm: bool,
    live_uc: bool,
    live_jobs: bool,
    update: bool,
) -> None:
    """Scan PROJECT_PATH and build the knowledge graph."""
    try:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn
        console = Console()
    except ImportError:
        console = None  # type: ignore[assignment]

    def _print(msg: str) -> None:
        if console:
            console.print(msg)
        else:
            print(msg)

    root = Path(project_path).resolve()
    output_dir = Path(out).resolve()

    _print(f"[bold cyan]Platograph[/bold cyan] scanning [green]{root}[/green]")

    # Load config
    from datagraph.config import load_config
    cfg = load_config(root)

    # Build graph (optionally merge with existing)
    from datagraph.graph import DataGraph
    existing_json = output_dir / "graph.json"
    if update and existing_json.exists():
        graph = DataGraph.load(existing_json)
        _print(f"  Loaded existing graph ({len(graph._nodes)} nodes)")
    else:
        graph = DataGraph()

    # Discover and run extractors
    from datagraph.extractors.base import get_all_extractors
    extractors = get_all_extractors()

    # Default ignore dirs
    _DEFAULT_IGNORE = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "target", "dist", "build"}
    ignore_patterns = _DEFAULT_IGNORE | set(cfg.ignore_paths or [])

    def _is_ignored(p: Path) -> bool:
        return any(part in ignore_patterns for part in p.parts)

    # Partition: directory-level vs file-level extractors
    dir_extractors = [e for e in extractors if not e.supported_extensions]
    file_extractors = [e for e in extractors if e.supported_extensions]

    # Build extension → extractor mapping
    from collections import defaultdict
    ext_map: dict[str, list] = defaultdict(list)
    for ext in file_extractors:
        for suffix in ext.supported_extensions:
            ext_map[suffix].append(ext)

    def _add_to_graph(nodes, edges):
        for n in nodes:
            graph.add_node(n)
        for e in edges:
            graph.add_edge(e)

    _print(f"  Running {len(extractors)} extractors …")

    # Collect all nodes and edges before adding to graph (two-pass approach)
    # so cross-file edges (e.g. pipeline YAML → dataset from .py) are not
    # silently dropped because the target node doesn't exist yet.
    all_nodes_batch: list = []
    all_edges_batch: list = []

    def _collect(nodes, edges):
        all_nodes_batch.extend(nodes)
        all_edges_batch.extend(edges)

    # Run directory-level extractors once on project root
    for extractor in dir_extractors:
        nodes, edges = extractor.safe_extract(root, root)
        _collect(nodes, edges)

    # Walk the tree and dispatch file-level extractors
    try:
        all_files = [p for p in root.rglob("*") if p.is_file() and not _is_ignored(p)]
    except Exception:
        all_files = []

    for file_path in all_files:
        suffix = file_path.suffix.lower()
        for extractor in ext_map.get(suffix, []):
            nodes, edges = extractor.safe_extract(file_path, root)
            _collect(nodes, edges)

    # First pass: add all nodes so edges never reference missing endpoints
    for n in all_nodes_batch:
        graph.add_node(n)
    # Second pass: add all edges
    for e in all_edges_batch:
        graph.add_edge(e)

    # Cross-reference resolution
    graph.resolve_cross_references()

    # LLM document enrichment (Pass 3 — costs tokens, opt-in via --enrich-llm)
    if enrich_llm:
        try:
            from datagraph.enrichment.doc_enrichment import enrich_docs_with_llm
            _print("  Running LLM document enrichment …")
            n_enriched = enrich_docs_with_llm(graph)
            _print(f"  [green]✓[/green] Doc enrichment: {n_enriched} document(s) enriched")
        except Exception as exc:
            _print(f"  [yellow]Doc enrichment skipped:[/yellow] {exc}")

    # Community detection
    try:
        from datagraph.analysis.clustering import cluster
        cluster(graph)
        _print(f"  Clustering done.")
    except Exception as exc:
        _print(f"  [yellow]Clustering skipped:[/yellow] {exc}")

    # Outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    from datagraph.output import json_export
    json_export.export(graph, output_dir)
    _print(f"  [green]✓[/green] {output_dir / 'graph.json'}")

    if not no_viz:
        try:
            from datagraph.output import html_viz
            html_viz.export(graph, output_dir)
            _print(f"  [green]✓[/green] {output_dir / 'graph.html'}")
        except Exception as exc:
            _print(f"  [yellow]HTML viz skipped:[/yellow] {exc}")

    if not no_report:
        from datagraph.output import report, mermaid
        report.export(graph, output_dir, project_name=root.name)
        _print(f"  [green]✓[/green] {output_dir / 'LINEAGE_REPORT.md'}")
        mermaid.export_lineage(graph, output_dir)
        mermaid.export_orchestration(graph, output_dir)
        _print(f"  [green]✓[/green] lineage.mermaid + orchestration.mermaid")

    s = graph.summary()
    _print(
        f"\n[bold]Done.[/bold] {s['nodes']} nodes · {s['edges']} edges"
        + (f" · {s.get('clusters', 0)} clusters" if s.get("clusters") else "")
    )


# ─── query ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("question")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def query(question: str, graph_json: str) -> None:
    """Answer a natural-language question about the graph."""
    from datagraph.graph import DataGraph
    from datagraph.rag.retriever import retrieve
    from datagraph.rag.synthesizer import synthesize

    g = DataGraph.load(Path(graph_json))
    nodes = retrieve(g, question, top_k=12)
    answer = synthesize(question, nodes)
    click.echo(answer)


# ─── upstream / downstream ─────────────────────────────────────────────────────

@main.command()
@click.argument("node_id")
@click.option("--depth", default=3, show_default=True)
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def upstream(node_id: str, depth: int, graph_json: str) -> None:
    """List upstream dependencies of NODE_ID."""
    from datagraph.graph import DataGraph
    g = DataGraph.load(Path(graph_json))
    result = g.upstream(node_id, depth)
    for n in result:
        click.echo(f"{n.id}  [{n.type.value}]")


@main.command()
@click.argument("node_id")
@click.option("--depth", default=3, show_default=True)
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def downstream(node_id: str, depth: int, graph_json: str) -> None:
    """List downstream consumers of NODE_ID."""
    from datagraph.graph import DataGraph
    g = DataGraph.load(Path(graph_json))
    result = g.downstream(node_id, depth)
    for n in result:
        click.echo(f"{n.id}  [{n.type.value}]")


# ─── impact ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("node_id")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def impact(node_id: str, graph_json: str) -> None:
    """Full blast-radius analysis for NODE_ID."""
    from datagraph.graph import DataGraph
    g = DataGraph.load(Path(graph_json))
    result = g.impact_analysis(node_id)
    affected = result["transitively_affected"]
    click.echo(f"Blast radius: {len(affected)} nodes")
    for n in affected:
        click.echo(f"  {n.id}  [{n.type.value}]")


# ─── path ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("source")
@click.argument("target")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def path(source: str, target: str, graph_json: str) -> None:
    """Shortest path between SOURCE and TARGET."""
    from datagraph.graph import DataGraph
    g = DataGraph.load(Path(graph_json))
    p = g.shortest_path(source, target)
    if p:
        click.echo(" → ".join(n.id for n in p))
    else:
        click.echo("No path found.")


# ─── schedule ──────────────────────────────────────────────────────────────────

@main.command()
@click.argument("asset_name")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def schedule(asset_name: str, graph_json: str) -> None:
    """Show what schedule/orchestrator runs ASSET_NAME."""
    from datagraph.graph import DataGraph
    import json as _json
    g = DataGraph.load(Path(graph_json))
    info = g.schedule_for(asset_name)
    click.echo(_json.dumps(info, indent=2) if info else "No schedule found.")


# ─── execution ─────────────────────────────────────────────────────────────────

@main.command()
@click.argument("job_name")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def execution(job_name: str, graph_json: str) -> None:
    """Show topological execution order for JOB_NAME."""
    from datagraph.graph import DataGraph
    g = DataGraph.load(Path(graph_json))
    stages = g.execution_order(job_name)
    for i, stage in enumerate(stages, 1):
        click.echo(f"Stage {i}: {', '.join(n.name for n in stage)}")


# ─── install ───────────────────────────────────────────────────────────────────

@main.command()
@click.argument("project_path", default=".", type=click.Path(exists=True))
def install(project_path: str) -> None:
    """Write CLAUDE.md and AGENTS.md into PROJECT_PATH for AI assistant integration."""
    root = Path(project_path).resolve()
    content = """# Platograph — AI Assistant Integration

This project uses **Platograph** to maintain a data-platform knowledge graph.

## Available Commands

```bash
# Scan / refresh the graph
platograph scan .

# Answer questions
platograph query "what jobs write to the gold layer?"
platograph query "show me all assets with no downstream consumers"

# Lineage
platograph upstream <node_id>
platograph downstream <node_id>
platograph path <source> <target>

# Impact
platograph impact <node_id>

# Orchestration
platograph schedule <asset_name>
platograph execution <job_name>
```

## Graph files

- `datagraph-out/graph.json` — machine-readable graph
- `datagraph-out/graph.html` — interactive visualisation
- `datagraph-out/LINEAGE_REPORT.md` — summary report
- `datagraph-out/lineage.mermaid` — lineage diagram source
- `datagraph-out/orchestration.mermaid` — orchestration diagram source

**Always use these commands before modifying pipeline code or table schemas.**
"""
    for fname in ("CLAUDE.md", "AGENTS.md"):
        fpath = root / fname
        fpath.write_text(content)
        click.echo(f"Written {fpath}")


# ─── serve ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def serve(graph_json: str) -> None:
    """Start the MCP stdio server backed by GRAPH_JSON."""
    from datagraph.serve.mcp_server import serve as _serve
    _serve(Path(graph_json))


# ─── prs ───────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("repo")
@click.option("--graph-json", default="datagraph-out/graph.json", show_default=True)
def prs(repo: str, graph_json: str) -> None:
    """List open PRs and their blast-radius for REPO (owner/name)."""
    from datagraph.graph import DataGraph
    from datagraph.analysis.pr_triage import list_open_prs, pr_blast_radius
    g = DataGraph.load(Path(graph_json))
    open_prs = list_open_prs(repo)
    for pr in open_prs:
        result = pr_blast_radius(g, repo, pr["number"])
        affected = result.get("affected_nodes", [])
        click.echo(f"PR #{pr['number']} — {pr.get('title', '')} — {len(affected)} affected nodes")


if __name__ == "__main__":
    main()
