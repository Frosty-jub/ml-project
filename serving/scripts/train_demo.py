"""DEMO ONLY: deterministic synthetic demand, chronological split, shared pipeline."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import Pipeline

from scripts.export_model import export_bundle

ROOT = Path(__file__).resolve().parents[1]


def build_demo(destination: Path | None = None):
    rng = np.random.default_rng(413008)
    count = 6030
    day = np.arange(count)
    demand = np.maximum(
        0,
        120
        + 20 * np.sin(2 * np.pi * day / 7)
        + 12 * np.sin(2 * np.pi * day / 365)
        + 0.008 * day
        + rng.normal(0, 5, count),
    )
    series = pd.Series(demand)
    frame = pd.DataFrame(
        {
            "lag_1": series.shift(1),
            "lag_7": series.shift(7),
            "rolling_mean_7": series.shift(1).rolling(7).mean(),
            "day_of_week": day % 7,
        }
    )
    frame = frame.iloc[30:].reset_index(drop=True)
    target = demand[30:]
    train = frame.iloc[:5000].copy()
    # Missing observations use the fitted imputer in both training and serving.
    train.loc[train.index % 97 == 0, "lag_1"] = np.nan
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "regressor",
                RandomForestRegressor(n_estimators=80, max_depth=12, min_samples_leaf=3, random_state=413008, n_jobs=1),
            ),
        ]
    )
    pipeline.fit(train, target[:5000])
    holdout = frame.iloc[5000:]
    predicted = pipeline.predict(holdout)
    schema = [
        {"name": "lag_1", "type": "number", "nullable": True, "minimum": 0},
        {"name": "lag_7", "type": "number", "minimum": 0},
        {"name": "rolling_mean_7", "type": "number", "minimum": 0},
        {"name": "day_of_week", "type": "integer", "minimum": 0, "maximum": 6},
    ]
    folder = export_bundle(
        pipeline,
        holdout.head(3),
        schema,
        destination or ROOT / "artifacts" / "demo",
        "synthetic-demand-demo",
        "demo-v1",
        data_kind="synthetic_demo_only",
    )
    metrics = {
        "data_kind": "synthetic_demo_only",
        "seed": 413008,
        "rows": 6000,
        "train_rows": 5000,
        "test_rows": 1000,
        "split": "chronological",
        "MAE": mean_absolute_error(target[5000:], predicted),
        "RMSE": root_mean_squared_error(target[5000:], predicted),
        "WAPE_percent": float(np.abs(target[5000:] - predicted).sum() / np.abs(target[5000:]).sum() * 100),
    }
    (folder / "demo_training.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"model_dir": str(folder), **metrics}, indent=2))


if __name__ == "__main__":
    build_demo()
