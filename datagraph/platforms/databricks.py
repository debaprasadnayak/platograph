"""Databricks platform helpers — path normalisation + optional live API."""

from __future__ import annotations

import re
from pathlib import Path


_WS_PREFIXES = re.compile(
    r"^(?:/Workspace|/Repos|/Users/[^/]+)(/.*)"
)


def normalise_notebook_path(raw: str) -> str:
    """Strip /Workspace, /Repos, /Users/<email> prefix, return stem."""
    m = _WS_PREFIXES.match(raw)
    if m:
        raw = m.group(1)
    # Return filename stem as fallback identifier
    return Path(raw).stem or raw


def list_live_jobs(host: str, token: str) -> list[dict]:
    """Fetch job list from Databricks REST API (requires databricks-sdk or requests)."""
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
        w = WorkspaceClient(host=host, token=token)
        return [j.as_dict() for j in w.jobs.list()]
    except Exception:
        return []


def list_uc_tables(host: str, token: str, catalog: str, schema: str) -> list[dict]:
    """Fetch Unity Catalog tables for a schema."""
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
        w = WorkspaceClient(host=host, token=token)
        return [t.as_dict() for t in w.tables.list(catalog_name=catalog, schema_name=schema)]
    except Exception:
        return []
