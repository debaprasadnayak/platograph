"""PR triage — data-platform-aware blast-radius ranking for open pull requests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datagraph.graph import DataGraph


@dataclass
class PrSummary:
    pr_number: int
    title: str
    url: str
    changed_files: list[str]
    impacted_nodes: list[str]
    blast_radius: int
    gold_tables_affected: list[str]
    orchestrators_affected: list[str]
    BI_assets_affected: list[str]


def get_open_prs(repo: str, token: str | None = None) -> list[dict[str, Any]]:
    """Fetch open PRs from GitHub REST API."""
    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:
        return []

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=50"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return []
    return resp.json()


def get_pr_files(repo: str, pr_number: int, token: str | None = None) -> list[str]:
    """Return list of changed file paths for a PR."""
    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:
        return []

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return []
    return [f["filename"] for f in resp.json()]


def triage_prs(
    graph: "DataGraph",
    repo: str,
    token: str | None = None,
) -> list[PrSummary]:
    """
    Fetch open PRs, map changed files to graph nodes, compute downstream blast radius.
    Returns PRs sorted by blast_radius descending.
    """
    from datagraph.models import DataLayer, NodeType

    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    prs = get_open_prs(repo, token)
    results: list[PrSummary] = []

    for pr in prs:
        pr_number = pr["number"]
        changed_files = get_pr_files(repo, pr_number, token)

        impacted_node_ids: list[str] = []
        for file_path in changed_files:
            # Find nodes whose file_path matches or is a suffix of the changed file
            for node in graph._nodes.values():
                if node.file_path and (
                    file_path.endswith(node.file_path)
                    or node.file_path.endswith(file_path)
                    or file_path == node.file_path
                ):
                    impacted_node_ids.append(node.id)

        # Compute all downstream from impacted nodes
        all_downstream: set[str] = set()
        for nid in impacted_node_ids:
            try:
                import networkx as nx
                all_downstream.update(nx.descendants(graph._g, nid))
            except Exception:
                pass

        # Classify affected downstream
        gold_tables = [
            graph._nodes[n].name
            for n in all_downstream
            if graph._nodes.get(n) and graph._nodes[n].layer in (DataLayer.GOLD, DataLayer.DATAMART)
        ]
        orchestrators = [
            graph._nodes[n].name
            for n in all_downstream
            if graph._nodes.get(n) and graph._nodes[n].type.value.endswith("_job") or
               (graph._nodes.get(n) and graph._nodes[n].type.value.endswith("_dag"))
        ]
        bi_assets = [
            graph._nodes[n].name
            for n in all_downstream
            if graph._nodes.get(n) and graph._nodes[n].type.value in (
                "pbi_dataset", "pbi_report", "fabric_semantic_model",
                "pbi_measure", "fabric_measure",
            )
        ]

        results.append(
            PrSummary(
                pr_number=pr_number,
                title=pr.get("title", ""),
                url=pr.get("html_url", ""),
                changed_files=changed_files,
                impacted_nodes=impacted_node_ids,
                blast_radius=len(all_downstream),
                gold_tables_affected=list(set(gold_tables)),
                orchestrators_affected=list(set(orchestrators)),
                BI_assets_affected=list(set(bi_assets)),
            )
        )

    results.sort(key=lambda x: x.blast_radius, reverse=True)
    return results
