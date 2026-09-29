"""Fail CI on import errors or a broken production task dependency chain."""
from airflow.dag_processing.dagbag import DagBag

bag = DagBag(dag_folder="dags")
assert not bag.import_errors, bag.import_errors
dag = bag.dags.get("demand_forecasting")
expected = ["download", "prepare", "validate", "features", "experiment2",
            "experiment3", "quality_gate", "register", "benchmark_candidate",
            "benchmark_previous", "promote_and_verify"]
assert dag is not None
assert set(dag.task_ids) == set(expected), dag.task_ids
for index, name in enumerate(expected):
    task = dag.get_task(name)
    children = {expected[index + 1]} if index + 1 < len(expected) else set()
    assert task.downstream_task_ids == children, name
    assert task.trigger_rule == "all_success", name
assert dag.max_active_runs == 1
print("PASS: DAG imports and all 11 gated dependencies")
