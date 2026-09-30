# MLflow tracking and Model Registry

Run commands from the repository root after installing `requirements.txt`. The default tracking store is `sqlite:///mlflow.db`, with model artifacts in `mlartifacts/`. Both are local and ignored by Git. Set `MLFLOW_TRACKING_URI` to a shared MLflow server URL if the team needs the same registry.

## Produce source artifacts

Run the data pipeline and Experiments 1, 2, and 3 as described in the main README. The experiment scripts run on a work branch and record the actual Git commit and branch in their metadata. This workflow uses the existing validation results and final candidate; it does not open the test split again.

## Track and check

```bash
python -m src.demand_forecasting.registry track
python -m src.demand_forecasting.registry check
```

`track` creates one MLflow run per Experiment 1, 2, and 3 trial, with hyperparameters, validation metrics, and source evidence. Experiment 2–3 runs also include per-fold metrics. Experiment 1 uses its single validation split and is not directly comparable to the four-fold Experiment 2–3 scores. Each invocation creates new runs. `check` loads the final candidate and reports each quality rule. A nonzero exit code means a rule failed.

The policy in `config/model_registry.json` requires valid metrics and feature order, finite nonnegative predictions, no test-set use, lower mean validation MAE than the historical baseline, and wins on at least 3 of the same 4 validation folds. The aggregate MAE must match those folds. This is a validation gate, not an independent test estimate: the original test aggregate was already seen in Experiment 1.

## Register selected models

```bash
python -m src.demand_forecasting.registry register
python -m src.demand_forecasting.registry register-experiments
python -m src.demand_forecasting.registry status
```

`register` logs the Experiment 3 final run and its gate evidence. `register-experiments` adds one saved selected model per experiment and reuses an existing version when its source artifact SHA-256 matches. Experiment 1 is a historical single-split reference and cannot pass the four-fold validation gate. Experiment 2 is an eligible fallback; Experiment 3 is the best candidate. The per-trial results remain in tracking runs, since final fitted models were not saved for every trial.

## Measure serving performance

Export the validation-gated Registry version from the repository root into the bundle format used by FastAPI:

```powershell
python serving\scripts\export_model.py --version 1 --destination serving\artifacts\group-v1-joblib
```

The exporter reads the current validation feature manifest, saves the registered `FeatureOrderedModel` as `model.joblib`, and checks its predictions against the registered model. Start FastAPI with that bundle from the `serving/` directory:

```powershell
docker compose -f compose.yaml -f compose.model.yaml up --build -d --force-recreate
```

From the repository root, benchmark the same registered version through FastAPI:

```powershell
python -m src.demand_forecasting.registry benchmark 1 --url http://127.0.0.1:18005
```

The benchmark sends validation feature rows to `POST /predict` as `records`, checks the response model name/version, and compares predictions with the Registry version. It warms up with 5 requests, then measures 30 requests at concurrency 4, logs p50/p95 and throughput in MLflow, and applies the policy in `config/model_registry.json`. Its current gate is p50 ≤ 200 ms, p95 ≤ 500 ms, and throughput ≥ 100 predictions/second; evidence must be less than 24 hours old at promotion time. `serving/slo.json` currently has different demo thresholds, so the group must agree on one SLO before treating this gate as the service SLO.

## Promote and roll back

```bash
python -m src.demand_forecasting.registry promote 1 --fallback-version 3
python -m src.demand_forecasting.registry rollback
```

`promote` requires both validation and serving gates to pass. It points `production` (and the compatible `champion` alias) to the selected version and `previous` to the named fallback or the old production version. An incoming version must use the same validation folds and have validation MAE no worse than the current production version, subject to `maximum_champion_mae_regression_pct` (default 0%). Rollback swaps `production` and `previous` and updates `champion`. It is an alias change; a process that already loaded the old model must reload it or restart before traffic uses the new alias target.

Consumers can load the active model with `mlflow.pyfunc.load_model("models:/demand-forecasting-7d@production")`. Supply a DataFrame with the exact training feature columns in order. Run consumers from the repository root or install the project package so the saved Python model class is importable.

To open the local UI against the same store:

```bash
mlflow server --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5000
```
