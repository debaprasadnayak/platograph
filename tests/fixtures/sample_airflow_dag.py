from datetime import datetime
from airflow import DAG
from airflow.providers.databricks.operators.databricks import DatabricksRunNowOperator
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

with DAG(
    dag_id="sample_etl_dag",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
) as dag:

    ingest = DatabricksRunNowOperator(
        task_id="ingest_raw",
        job_id=12345,
        databricks_conn_id="databricks_default",
    )

    transform = BashOperator(
        task_id="run_dbt",
        bash_command="dbt run --select stg_orders orders_mart --project-dir /dbt",
    )

    report_a = BashOperator(
        task_id="report_dashboard_a",
        bash_command="echo 'Publishing dashboard A'",
    )

    report_b = BashOperator(
        task_id="report_dashboard_b",
        bash_command="echo 'Publishing dashboard B'",
    )

    trigger_downstream = TriggerDagRunOperator(
        task_id="trigger_notification_dag",
        trigger_dag_id="notification_dag",
    )

    ingest >> transform >> [report_a, report_b]
    report_a >> trigger_downstream
