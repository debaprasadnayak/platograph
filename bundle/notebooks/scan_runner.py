# Databricks notebook source
# MAGIC %md
# MAGIC # Platograph Scan Runner
# MAGIC
# MAGIC This notebook is invoked by the `platograph_scan_job` bundle job.
# MAGIC It runs `platograph scan` against the target project path and writes
# MAGIC graph artefacts to a Unity Catalog Volume.

# COMMAND ----------

import subprocess
import sys

dbutils.widgets.text("project_path", "/Workspace/Repos/platograph", "Project Path")
dbutils.widgets.text("output_path", "/Volumes/main/default/platograph_out", "Output Path")

project_path = dbutils.widgets.get("project_path")
output_path = dbutils.widgets.get("output_path")

print(f"Scanning: {project_path}")
print(f"Output:   {output_path}")

# COMMAND ----------

result = subprocess.run(
    [sys.executable, "-m", "datagraph.cli", "scan", project_path, "--out", output_path, "--no-viz"],
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
    raise RuntimeError(f"platograph scan failed (exit {result.returncode})")

# COMMAND ----------

# Show summary
import json, pathlib
graph_json = pathlib.Path(output_path) / "graph.json"
if graph_json.exists():
    data = json.loads(graph_json.read_text())
    print(f"Nodes: {len(data['nodes'])}  Edges: {len(data['edges'])}")
