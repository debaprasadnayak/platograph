"""Rich document extractor — uses MarkItDown to convert PDF, DOCX, PPTX, images,
Excel, EPUB, HTML and more to Markdown text, then creates DOC_FILE nodes.

The converted markdown is stored in ``node.metadata["markdown_text"]`` (capped at
``_TEXT_LIMIT`` chars) so the optional LLM enrichment pass can later extract
knowledge-graph entities and relationships from it.

Install the optional dependency:
    pip install 'markitdown[pdf,docx,pptx,xlsx]'   # or 'markitdown[all]'

If markitdown is not installed, the extractor is silently skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from datagraph.extractors.base import BaseExtractor, register
from datagraph.models import Edge, Node, NodeType

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)", re.MULTILINE)

# Character limit stored in metadata — avoids huge payloads; LLM enrichment
# only needs the first portion of most documents.
_TEXT_LIMIT = 4_000

# Extensions markitdown can convert that are NOT already handled by other
# dedicated extractors (.md/.mdx → MarkdownExtractor, .sql → SqlExtractor, etc.)
_SUPPORTED_EXTENSIONS = [
    # Documents
    ".pdf",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
    ".epub",
    # Web
    ".html", ".htm",
    # Data (markitdown renders as markdown tables / code blocks)
    ".json", ".csv",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
]


@register
class RichDocExtractor(BaseExtractor):
    """Convert rich document formats to DOC_FILE nodes via MarkItDown."""

    supported_extensions: list[str] = _SUPPORTED_EXTENSIONS

    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        nodes: list[Node] = []
        edges: list[Edge] = []

        try:
            from markitdown import MarkItDown  # type: ignore[import-untyped]
        except ImportError:
            # Optional dependency not installed — skip gracefully
            return nodes, edges

        rel = self.relative_path(path, project_root)
        doc_id = self.make_node_id("doc_file", rel)

        text_content = ""
        try:
            md = MarkItDown(enable_plugins=False)
            result = md.convert_local(str(path))
            text_content = result.text_content or ""
        except Exception:
            # Conversion failed (password-protected, corrupt, etc.) — still
            # create a node so the file appears in the graph.
            pass

        title_match = _H1_RE.search(text_content) or _H2_RE.search(text_content)
        description = title_match.group(1).strip() if title_match else path.stem

        metadata: dict[str, object] = {}
        if text_content:
            metadata["markdown_text"] = text_content[:_TEXT_LIMIT]

        nodes.append(
            Node(
                id=doc_id,
                name=path.name,
                type=NodeType.DOC_FILE,
                file_path=rel,
                description=description,
                metadata=metadata,
            )
        )

        return nodes, edges
