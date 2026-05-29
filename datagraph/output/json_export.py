"""JSON export for graph.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datagraph.graph import DataGraph


def export(graph: "DataGraph", output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "graph.json"
    data = graph.to_dict()
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return out_path
