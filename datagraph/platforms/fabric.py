"""Microsoft Fabric platform helpers — OneLake URL parsing + optional REST client."""

from __future__ import annotations

import re
from urllib.parse import urlparse


_ONELAKE_RE = re.compile(
    r"onelake(?:\.blob\.fabric)?\.microsoft\.com/([^/]+)/([^/]+)/([^/]+)/(.+)",
    re.IGNORECASE,
)


def parse_onelake_url(url: str) -> dict[str, str] | None:
    """Parse an OneLake ABFS/HTTPS URL into workspace/item/path parts."""
    # abfs(s)://... or https://onelake.blob.fabric...
    path = url.replace("abfss://", "").replace("abfs://", "")
    # Handle @-style: <container>@onelake.dfs.fabric.microsoft.com/<ws>/<item>/...
    at_match = re.match(r"([^@]+)@onelake\.dfs\.fabric\.microsoft\.com/(.+)", path)
    if at_match:
        container, remainder = at_match.groups()
        parts = remainder.strip("/").split("/", 2)
        return {"workspace": parts[0] if parts else "", "item": container, "path": parts[1] if len(parts) > 1 else ""}

    m = _ONELAKE_RE.search(path)
    if m:
        workspace, item, folder, sub = m.groups()
        return {"workspace": workspace, "item": item, "folder": folder, "path": sub}
    return None


def lakehouse_name_from_path(path: str) -> str | None:
    """Extract lakehouse name from a relative Fabric path like Tables/mydb/..."""
    parts = path.replace("\\", "/").split("/")
    # Fabric paths often: <LakehouseName>.Lakehouse/Tables/...
    for p in parts:
        if p.endswith(".Lakehouse"):
            return p[: -len(".Lakehouse")]
    return None
