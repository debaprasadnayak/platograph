"""Platograph Viewer — Streamlit app that renders graph.html + report."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

GRAPH_JSON = Path("datagraph-out/graph.json")
GRAPH_HTML = Path("datagraph-out/graph.html")
REPORT_MD = Path("datagraph-out/LINEAGE_REPORT.md")


def main() -> None:
    st.set_page_config(page_title="Platograph Viewer", layout="wide", page_icon="🕸️")
    st.title("🕸️ Platograph — Data Platform Knowledge Graph")

    if not GRAPH_JSON.exists():
        st.warning(
            "No graph found. Run `platograph scan .` first to generate `datagraph-out/graph.json`."
        )
        st.stop()

    data = json.loads(GRAPH_JSON.read_text())
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Nodes", len(nodes))
    col2.metric("Edges", len(edges))
    col3.metric("Clusters", data.get("metadata", {}).get("clusters", "—"))

    st.divider()

    tab_viz, tab_report, tab_nodes = st.tabs(["Interactive Graph", "Lineage Report", "Node Explorer"])

    with tab_viz:
        if GRAPH_HTML.exists():
            html_content = GRAPH_HTML.read_text()
            st.components.v1.html(html_content, height=750, scrolling=False)
        else:
            st.info("Re-run `platograph scan` without `--no-viz` to generate the HTML graph.")

    with tab_report:
        if REPORT_MD.exists():
            st.markdown(REPORT_MD.read_text())
        else:
            st.info("Run `platograph scan` without `--no-report` to generate the report.")

    with tab_nodes:
        if nodes:
            type_filter = st.selectbox(
                "Filter by type",
                ["all"] + sorted({n.get("type", "?") for n in nodes}),
            )
            filtered = nodes if type_filter == "all" else [n for n in nodes if n.get("type") == type_filter]
            st.write(f"{len(filtered)} nodes")
            st.dataframe(
                [
                    {
                        "Name": n.get("name"),
                        "Type": n.get("type"),
                        "Layer": n.get("layer"),
                        "Description": (n.get("description") or "")[:80],
                    }
                    for n in filtered
                ],
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
