# Airflow run acceptance_bad_quality_20260930

Status: **failed**

Scenario: bad_quality

| Task | Status |
|---|---|
| initialize | success |
| prepare_data | success |
| experiment_2 | success |
| experiment_3 | success |
| verify_full_folds | success |
| candidate_quality_gate | failed |
| register_models | not_run |
| export_bundles | not_run |
| benchmark_candidates | not_run |
| approve_and_deploy | not_run |
| rollback_drill | not_run |
| verify_monitoring | not_run |
| simulate_drift | not_run |
| check_drift | not_run |
| retrain_candidate | not_run |

See summary.json, per-task logs, approval.json, parity reports, load_test.json and drift_demo/.

Drift/retraining evidence is synthetic_demo_only. Team sign-off remains pending.