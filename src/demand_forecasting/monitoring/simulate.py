"""Reproducible offline reference, drift and delayed-label demonstration."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
from lightgbm import LGBMRegressor

from src.demand_forecasting.training.models import FeatureOrderedModel


def generate(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(42)
    features = ["sales_lag_1", "sales_rolling_sum_7"]
    X = np.column_stack((rng.uniform(2, 25, 500), rng.uniform(20, 180, 500))).astype("float32")
    target = X[:, 0] * 2 + X[:, 1] * .15
    regressor = LGBMRegressor(n_estimators=40, learning_rate=.08, num_leaves=15,
                             verbose=-1, random_state=42, n_jobs=1)
    regressor.fit(X, target)
    champion = FeatureOrderedModel(regressor, features)
    champion_predictions = champion.predict(X)
    joblib.dump(champion, directory / "champion_model.joblib")
    (directory / "params.json").write_text(json.dumps({
        "objective": "regression_l1", "n_estimators": 60, "learning_rate": .08,
        "num_leaves": 15, "verbosity": -1, "n_jobs": 1
    }, indent=2) + "\n", encoding="utf-8")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    outputs = {}
    for kind, number_days in (("reference", 14), ("live", 28)):
        event_path = directory / f"{kind}_events.jsonl"
        label_path = directory / f"{kind}_labels.csv"
        with event_path.open("w", encoding="utf-8") as events, label_path.open(
            "w", encoding="utf-8", newline=""
        ) as labels:
            writer = csv.DictWriter(labels, fieldnames=["request_id", "row_index", "actual", "observed_at"])
            writer.writeheader()
            for day in range(number_days):
                instant = start + timedelta(days=day + (0 if kind == "reference" else 14))
                for index in range(40):
                    source_index = rng.integers(len(X))
                    row = X[source_index]
                    demand = float(row[0] * 2 + row[1] * .15)
                    if kind == "live" and day >= 14:
                        demand += 15  # Same feature distribution; changed target relationship.
                    observed = max(0, demand + rng.normal(0, 1))
                    request_id = f"{kind}-{day:02d}-{index:02d}"
                    prediction = float(champion_predictions[source_index])
                    events.write(json.dumps({
                        "timestamp": instant.isoformat(), "request_id": request_id, "row_index": 0,
                        "model_name": "simulated-demand-7d", "model_version": "sim-v1",
                        "data_kind": "synthetic_demo_only",
                        "features": dict(zip(features, map(float, row))), "prediction": prediction,
                    }) + "\n")
                    writer.writerow({"request_id": request_id, "row_index": 0, "actual": observed,
                                     "observed_at": (instant + timedelta(days=8)).isoformat()})
        outputs[kind] = {"events": str(event_path), "labels": str(label_path)}
    return outputs
