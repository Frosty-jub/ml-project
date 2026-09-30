"""Raw data to policy-approved serving, rollback verification and monitoring evidence."""
import os
import re
import subprocess
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import Param, dag, get_current_context, task

ROOT = Path(os.environ.get('AIRFLOW_PROJECT_ROOT', '/project'))
PYTHON = os.environ.get('PROJECT_PYTHON', '/opt/project-venv/bin/python')
STAGES = [
    'initialize', 'prepare_data', 'experiment_2', 'experiment_3', 'verify_full_folds',
    'candidate_quality_gate', 'register_models', 'export_bundles', 'benchmark_candidates',
    'approve_and_deploy', 'rollback_drill', 'verify_monitoring',
    'simulate_drift', 'check_drift', 'retrain_candidate',
]


def invoke(stage):
    context = get_current_context()
    run_id = context['dag_run'].run_id
    key = re.sub(r'[^A-Za-z0-9_.-]', '_', run_id)
    runner = ROOT / 'artifacts/orchestration/runs' / key / 'project/orchestration/airflow/run_stage.py'
    if stage == 'initialize' or not runner.is_file():
        runner = ROOT / 'orchestration/airflow/run_stage.py'
    command = [PYTHON, str(runner), stage,
               '--run-id', context['dag_run'].run_id,
               '--scenario', context['params'].get('scenario', 'normal')]
    print('COMMAND:', subprocess.list2cmdline(command), flush=True)
    # Airflow's task runner exports its own site-packages through PYTHONPATH.
    # Do not let those packages shadow the project's pinned virtual environment.
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment['PYTHONNOUSERSITE'] = '1'
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


@dag(dag_id='demand_forecasting_e2e', schedule=None, catchup=False,
     start_date=pendulum.datetime(2026, 1, 1, tz='UTC'), max_active_runs=1,
     default_args={'retries': 0, 'execution_timeout': timedelta(hours=2)},
     params={'scenario': Param('normal', enum=['normal', 'bad_data', 'bad_quality'])},
     tags=['cp413008', 'real-model', 'orchestration'])
def demand_forecasting_e2e():
    @task
    def execute_stage(stage):
        invoke(stage)

    @task(trigger_rule='all_done')
    def write_run_report():
        # Collect failure evidence and fail this leaf when upstream failed.
        invoke('report')

    previous = None
    tasks = []
    for stage in STAGES:
        current = execute_stage.override(task_id=stage)(stage)
        if previous is not None:
            previous >> current
        tasks.append(current)
        previous = current
    report = write_run_report()
    for upstream in tasks:
        upstream >> report


demand_forecasting_e2e()


@dag(dag_id='demand_monitoring', schedule='@daily', catchup=False,
     start_date=pendulum.datetime(2026, 1, 1, tz='UTC'), max_active_runs=1,
     default_args={'retries': 0, 'execution_timeout': timedelta(hours=1)},
     tags=['cp413008', 'monitoring', 'delayed-labels'])
def demand_monitoring():
    @task
    def prepare_context():
        invoke('initialize')

    @task
    def check_live_observations():
        invoke('live_monitor')

    @task
    def retrain_when_triggered():
        invoke('live_retrain')

    prepare_context() >> check_live_observations() >> retrain_when_triggered()


demand_monitoring()
