# Platograph Viewer

Streamlit application that visualises the `datagraph-out/` artefacts.

## Run locally

```bash
pip install streamlit
streamlit run apps/datagraph_viewer/main.py
```

## Deploy to Databricks Apps

```bash
databricks apps create platograph-viewer
databricks apps deploy platograph-viewer --source-code-path apps/datagraph_viewer
```
