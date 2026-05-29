"""Markdown documentation extractor."""

from __future__ import annotations

import re
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import Edge, EdgeType, Node, NodeType

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)", re.MULTILINE)


@register
class MarkdownExtractor(BaseExtractor):
    supported_extensions: list[str] = [".md", ".mdx"]

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        text = path.read_text(errors="replace")
        rel = self.relative_path(path, project_root)
        doc_id = self.make_node_id("doc_file", rel)

        title_match = _H1_RE.search(text) or _H2_RE.search(text)
        description = title_match.group(1).strip() if title_match else path.stem

        nodes.append(
            Node(
                id=doc_id,
                name=path.name,
                type=NodeType.DOC_FILE,
                file_path=rel,
                description=description,
            )
        )

        return nodes, edges
