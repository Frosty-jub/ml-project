"""Trigger one run and fail the delivery job unless deployment is verified."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from airflow.models.dagrun import DagRun
from airflow.utils.session import create_session

run_id = sys.argv[1]
airflow = "/home/airflow/.local/bin/airflow"
deadline = time.monotonic() + 300
while True:
    result = subprocess.run([airflow, "dags", "trigger", "demand_forecasting",
                             "-r", run_id], capture_output=True, text=True)
    if result.returncode == 0:
        subprocess.run([airflow, "dags", "unpause", "demand_forecasting"], check=True)
        print(result.stdout, flush=True)
        break
    if time.monotonic() >= deadline:
        raise RuntimeError(result.stdout + result.stderr)
    time.sleep(10)

deadline = time.monotonic() + 5400
while time.monotonic() < deadline:
    with create_session() as session:
        run = session.query(DagRun).filter_by(dag_id="demand_forecasting", run_id=run_id).one_or_none()
        state = run.state if run else None
    print(f"{run_id}: {state}", flush=True)
    if state == "failed":
        raise RuntimeError("DAG failed; deployment is not accepted")
    if state == "success":
        path = Path("/workspace/artifacts/orchestration") / (hashlib.sha256(run_id.encode()).hexdigest()[:24] + ".json")
        evidence = json.loads(path.read_text())
        assert evidence.get("released") is True, evidence
        print(json.dumps(evidence, indent=2), flush=True)
        break
    time.sleep(15)
else:
    raise TimeoutError("DAG did not finish within 90 minutes")
