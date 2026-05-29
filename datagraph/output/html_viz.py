"""Interactive HTML visualisation using pyvis."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datagraph.graph import DataGraph

LAYER_COLORS: dict[str, str] = {
    "source":        "#8B0000",
    "raw":           "#CD5C5C",
    "bronze":        "#CD853F",
    "silver":        "#708090",
    "gold":          "#DAA520",
    "datamart":      "#2E8B57",
    "reporting":     "#4169E1",
    "orchestration": "#9932CC",
    "semantic_model":"#6A0DAD",
    "unknown":       "#808080",
}

EDGE_COLORS: dict[str, str] = {
    "reads_from":   "#1E90FF",
    "writes_to":    "#00BFFF",
    "depends_on":   "#87CEEB",
    "references":   "#B0C4DE",
    "tested_by":    "#ADD8E6",
    "shortcut_to":  "#00CED1",
    "executes":     "#FF8C00",
    "precedes":     "#FFA500",
    "triggers":     "#FF6347",
    "scheduled_by": "#FFD700",
    "run_by":       "#FF7F50",
    "contains":     "#DEB887",
    "part_of":      "#D2B48C",
    "promoted_to":  "#FFB6C1",
    "documented_by":"#90EE90",
}

NODE_SHAPES: dict[str, str] = {
    "table":                   "ellipse",
    "view":                    "ellipse",
    "dbt_model":               "ellipse",
    "dbt_seed":                "ellipse",
    "source_table":            "ellipse",
    "lakeflow_dataset":        "ellipse",
    "fabric_lakehouse":        "ellipse",
    "fabric_warehouse":        "ellipse",
    "databricks_job":          "box",
    "airflow_dag":             "box",
    "adf_pipeline":            "box",
    "synapse_pipeline":        "box",
    "fabric_pipeline":         "box",
    "fabric_deployment_pipeline": "box",
    "github_action_workflow":  "box",
    "dbt_cloud_job":           "box",
    "databricks_job_task":     "diamond",
    "airflow_task":            "diamond",
    "adf_activity":            "diamond",
    "synapse_activity":        "diamond",
    "fabric_pipeline_activity":"diamond",
    "pbi_measure":             "triangle",
    "fabric_measure":          "triangle",
    "dbt_test":                "triangle",
    "doc_file":                "text",
}

_TOGGLE_JS = """
<script>
function showAll() {
    network.setOptions({edges: {hidden: false}});
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-all').classList.add('active');
}
function showLineage() {
    var LINEAGE = ["reads_from","writes_to","depends_on","references","tested_by","shortcut_to","documented_by"];
    network.body.data.edges.forEach(function(edge) {
        var hidden = !LINEAGE.includes(edge.title);
        network.body.data.edges.update({id: edge.id, hidden: hidden});
    });
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-lineage').classList.add('active');
}
function showOrchestration() {
    var ORCH = ["executes","precedes","triggers","scheduled_by","run_by","contains","part_of","promoted_to"];
    network.body.data.edges.forEach(function(edge) {
        var hidden = !ORCH.includes(edge.title);
        network.body.data.edges.update({id: edge.id, hidden: hidden});
    });
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-orch').classList.add('active');
}
</script>
<style>
.toggle-btn { padding:6px 14px; margin:4px; cursor:pointer; border:1px solid #555; border-radius:4px; background:#2a2a2a; color:#eee; }
.toggle-btn.active { background:#9932CC; color:#fff; }
#controls { position:fixed; top:10px; left:10px; z-index:999; background:rgba(0,0,0,0.7); padding:8px; border-radius:6px; }
</style>
<div id="controls">
  <b style="color:#eee">Platograph</b><br>
  <button id="btn-all" class="toggle-btn active" onclick="showAll()">All</button>
  <button id="btn-lineage" class="toggle-btn" onclick="showLineage()">Lineage</button>
  <button id="btn-orch" class="toggle-btn" onclick="showOrchestration()">Orchestration</button>
</div>
"""


def export(
    graph: "DataGraph",
    output_dir: Path,
    max_nodes: int = 300,
) -> Path:
    try:
        from pyvis.network import Network  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("pip install pyvis to generate graph.html")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "graph.html"

    net = Network(height="95vh", width="100%", bgcolor="#1a1a2e", font_color="#eee", directed=True)
    net.toggle_physics(True)
    net.set_options('{"physics": {"stabilization": {"iterations": 150}}}')

    # Limit to top nodes by degree if graph is large
    nodes_to_show = list(graph._nodes.values())
    if len(nodes_to_show) > max_nodes:
        nodes_to_show.sort(key=lambda n: graph._g.degree(n.id), reverse=True)
        nodes_to_show = nodes_to_show[:max_nodes]
    shown_ids = {n.id for n in nodes_to_show}

    for node in nodes_to_show:
        color = LAYER_COLORS.get(node.layer.value, "#808080")
        shape = NODE_SHAPES.get(node.type.value, "ellipse")
        tooltip = f"ID: {node.id}\nType: {node.type.value}\nLayer: {node.layer.value}"
        if node.description:
            tooltip += f"\n{node.description}"
        net.add_node(
            node.id,
            label=node.name,
            title=tooltip,
            color=color,
            shape=shape,
        )

    for edge in graph._edges:
        if edge.source_id not in shown_ids or edge.target_id not in shown_ids:
            continue
        color = EDGE_COLORS.get(edge.type.value, "#888888")
        net.add_edge(
            edge.source_id,
            edge.target_id,
            title=edge.type.value,
            color=color,
            arrows="to",
        )

    html = net.generate_html()
    # Inject toggle controls before </body>
    html = html.replace("</body>", f"{_TOGGLE_JS}\n</body>")
    out_path.write_text(html)
    return out_path
