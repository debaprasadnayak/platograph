"""LLM enrichment pass — extracts knowledge entities and relationships from
DOC_FILE nodes that have ``metadata["markdown_text"]`` populated by
RichDocExtractor.

Each document is processed in a parallel thread (ThreadPoolExecutor). Claude
(or any configured backend) reads the markdown text and returns structured JSON:

    {
      "nodes": [{"id": "...", "name": "...", "type": "table|pipeline|...", "description": "..."}],
      "edges": [{"source_id": "...", "target_id": "...", "type": "reads_from|..."}]
    }

The extracted nodes are added to the graph and a REFERENCES edge is created
from the source DOC_FILE to each discovered entity, so documents become first-
class participants in the lineage graph.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datagraph.graph import DataGraph

from datagraph.llm_backend import call_llm, detect_backend
from datagraph.models import DataLayer, Edge, EdgeType, Node, NodeType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
You are a data-platform knowledge extractor. Given document text from a data \
engineering project, identify named entities and their relationships.

Extract ONLY entities that are explicitly named in the text — do not hallucinate.

Return ONLY valid JSON with this exact structure (no prose, no markdown code fences):
{
  "nodes": [
    {"id": "snake_case_id", "name": "Human Readable Name",
     "type": "table|view|pipeline|job|notebook|system|api|model",
     "description": "one-line description"}
  ],
  "edges": [
    {"source_id": "snake_case_id", "target_id": "snake_case_id",
     "type": "reads_from|writes_to|references|depends_on"}
  ]
}

If no entities are found, return: {"nodes": [], "edges": []}"""

# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_docs_with_llm(
    graph: "DataGraph",
    backend: str = "auto",
    max_workers: int = 4,
) -> int:
    """Enrich all DOC_FILE nodes that carry ``markdown_text`` metadata.

    Spawns up to *max_workers* parallel LLM calls. Each call extracts entity
    nodes and edges which are merged back into *graph*.

    Returns the number of documents successfully enriched (≥ 1 new node each).
    """
    doc_nodes = [
        node
        for node in graph._nodes.values()
        if node.type == NodeType.DOC_FILE and node.metadata.get("markdown_text")
    ]
    if not doc_nodes:
        return 0

    resolved = detect_backend(backend)
    if resolved == "none":
        log.warning("No LLM backend available — skipping doc enrichment. "
                    "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or DATABRICKS_HOST+TOKEN.")
        return 0

    enriched = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_enrich_one, node, resolved): node
            for node in doc_nodes
        }
        for future in as_completed(futures):
            doc_node = futures[future]
            try:
                new_nodes, inter_edges = future.result()
            except Exception as exc:
                log.warning("Doc enrichment failed for %s: %s", doc_node.id, exc)
                continue

            # Add extracted entity nodes first
            for n in new_nodes:
                graph.add_node(n)

            # REFERENCES edges from the doc to each extracted entity
            for n in new_nodes:
                graph.add_edge(
                    Edge(doc_node.id, n.id, EdgeType.REFERENCES, "LLM_INFERRED")
                )

            # Entity-to-entity edges returned by the LLM
            for e in inter_edges:
                graph.add_edge(e)

            if new_nodes:
                enriched += 1
                log.info("Enriched %s → %d new node(s)", doc_node.id, len(new_nodes))

    return enriched


# ---------------------------------------------------------------------------
# Per-document worker
# ---------------------------------------------------------------------------

def _enrich_one(doc_node: Node, backend: str) -> tuple[list[Node], list[Edge]]:
    text = str(doc_node.metadata.get("markdown_text", ""))
    raw = _call_llm(text, backend)
    return _parse_response(raw)


# ---------------------------------------------------------------------------
# LLM backends (mirrors synthesizer.py pattern)
# ---------------------------------------------------------------------------

def _call_llm(text: str, backend: str) -> str:
    messages = [{"role": "user", "content": f"Document text:\n{text}"}]
    return call_llm(messages, system=_EXTRACT_PROMPT, backend=backend, max_tokens=1024)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> tuple[list[Node], list[Edge]]:
    """Parse the LLM's JSON response into Node / Edge objects."""
    nodes: list[Node] = []
    edges: list[Edge] = []

    raw = raw.strip()

    # Strip markdown code fences that models sometimes add despite instructions
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("Doc enrichment: failed to parse LLM JSON: %r", raw[:200])
        return nodes, edges

    # Build a local id→node_id map to resolve inter-entity edges
    id_map: dict[str, str] = {}

    for item in data.get("nodes", []):
        llm_id = str(item.get("id", "")).strip()
        name = str(item.get("name", llm_id)).strip()
        type_str = str(item.get("type", "table")).lower()
        description = str(item.get("description", "")).strip()

        if not llm_id or not name:
            continue

        ntype = _TYPE_MAP.get(type_str, NodeType.TABLE)
        # Namespace the node id so it can merge with existing nodes of the same name
        node_id = f"{ntype.value}::{llm_id.lower().replace(' ', '_')}"
        id_map[llm_id] = node_id

        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=ntype,
                layer=DataLayer.UNKNOWN,
                description=description,
                metadata={"source": "llm_doc_enrichment"},
            )
        )

    for item in data.get("edges", []):
        src_llm = str(item.get("source_id", ""))
        tgt_llm = str(item.get("target_id", ""))
        etype_str = str(item.get("type", "references")).lower()

        src_id = id_map.get(src_llm)
        tgt_id = id_map.get(tgt_llm)
        if not src_id or not tgt_id:
            continue

        etype = _EDGE_MAP.get(etype_str, EdgeType.REFERENCES)
        edges.append(Edge(src_id, tgt_id, etype, "LLM_INFERRED"))

    return nodes, edges


# detect_backend imported from datagraph.llm_backend
