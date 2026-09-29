"""Manual, serialized training-to-serving DAG for the course demonstration."""
from datetime import datetime, timedelta, timezone
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="demand_forecasting", schedule=None, catchup=False,
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    max_active_runs=1, max_active_tasks=1,
    dagrun_timeout=timedelta(hours=12),
    default_args={"retries": 0, "execution_timeout": timedelta(hours=4)},
    tags=["ml", "integration", "course"],
    description="Raw data to validated model, benchmark, promotion and live serving verification",
) as dag:
    commands = [
        ("download", "scripts/download_data.py"),
        ("prepare", "scripts/prepare_data.py"),
        ("validate", "scripts/validate_data.py"),
        ("features", "scripts/build_features.py"),
        ("experiment2", "-m src.demand_forecasting.training.experiment2"),
        ("experiment3", "-m src.demand_forecasting.training.experiment3"),
        ("quality_gate", "-m src.demand_forecasting.orchestration gate"),
        ("register", "-m src.demand_forecasting.orchestration register"),
        ("benchmark_candidate", "-m src.demand_forecasting.orchestration benchmark-candidate"),
        ("benchmark_previous", "-m src.demand_forecasting.orchestration benchmark-previous"),
        ("promote_and_verify", "-m src.demand_forecasting.orchestration release"),
    ]
    previous = None
    for task_id, command in commands:
        current = BashOperator(
            task_id=task_id, cwd="/tmp",
            bash_command=f"cd /workspace && exec /opt/ml/bin/python {command}",
            env={"PIPELINE_RUN_ID": "{{ run_id }}"}, append_env=True,
            do_xcom_push=False, skip_on_exit_code=None,
        )
        if previous is not None:
            previous >> current
        previous = current
