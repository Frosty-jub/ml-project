"""Pass JSON to the Airflow CLI without Windows shell quoting ambiguities."""
import json
import subprocess
import sys

run_id, dag_id, scenario = sys.argv[1:]
subprocess.run(['airflow', 'dags', 'trigger', '--run-id', run_id,
                '--conf', json.dumps({'scenario': scenario}), dag_id], check=True)
