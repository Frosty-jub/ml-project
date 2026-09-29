"""Train demand forecasting candidates from Chawa's prepared time splits.

Run from the repository root: python -m src.demand_forecasting.training.train
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import HistoricalSumBaseline
from .metrics import evaluate


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "reports" / "generated" / "feature_split_manifest.json"
PIPELINE_CONFIG_PATH = ROOT / "config" / "pipeline.json"
TRAINING_CONFIG_PATH = ROOT / "config" / "training.json"
DATASET_CONFIG_PATH = ROOT / "config" / "dataset.yaml"
OUTPUT_DIR = ROOT / "artifacts" / "training"
ORIGIN_COLUMN = "forecast_origin_date"


@dataclass
class Split:
    X: np.ndarray
    y: np.ndarray
    first_origin: str
    last_origin: str


def target_from_dataset_config(path: Path) -> str:
    """Read the simple scalar `forecast.target` entry in the project's YAML."""
    text = path.read_text(encoding="utf-8")
    forecast = re.search(r"(?ms)^forecast:[^\n]*\n(.*?)(?=^[^\s#][^\n]*:|\Z)", text)
    if forecast is None:
        raise ValueError("config/dataset.yaml has no forecast section")
    matches = re.findall(r"(?m)^  target:\s*([^\s#]+)", forecast.group(1))
    if len(matches) != 1:
        raise ValueError("config/dataset.yaml must define one scalar forecast.target")
    return matches[0]


def load_manifest(target: str) -> tuple[dict, list[str], int]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError("Feature manifest missing; run python scripts/run_data_pipeline.py")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pipeline_config = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(PIPELINE_CONFIG_PATH.read_bytes()).hexdigest()
    if manifest.get("configuration_sha256") != digest:
        raise ValueError("Feature manifest is stale relative to config/pipeline.json")
    features = manifest.get("feature_columns")
    if not isinstance(features, list) or not features or len(features) != len(set(features)):
        raise ValueError("Feature manifest has an invalid feature list")
    if any(name in {target, ORIGIN_COLUMN, "sku_id"} for name in features):
        raise ValueError("Target, origin date, or SKU cannot be a model feature")
    horizon = int(pipeline_config["forecast_horizon_days"])
    if manifest.get("forecast_horizon_days") != horizon:
        raise ValueError("Feature manifest has a different forecast horizon")
    return manifest, features, horizon


def load_split(name: str, manifest: dict, features: list[str], target: str) -> Split:
    if name not in {"train", "validation", "test"}:
        raise ValueError(f"Unknown split: {name}")
    details = manifest["splits"][name]
    path = ROOT / details["path"]
    if not path.exists():
        raise FileNotFoundError(f"Missing {name} dataset: {path}; rerun the data pipeline")
    required = [ORIGIN_COLUMN, target, *features]
    frame = pd.read_csv(path, compression="gzip", usecols=required)
    if frame.empty or len(frame) != details["rows"]:
        raise ValueError(f"{name} row count does not match the feature manifest")
    if frame[required].isna().any().any():
        raise ValueError(f"{name} contains missing required values")
    first, last = str(frame[ORIGIN_COLUMN].min()), str(frame[ORIGIN_COLUMN].max())
    if (first, last) != (details["first_origin_date"], details["last_origin_date"]):
        raise ValueError(f"{name} date range does not match the feature manifest")
    X = frame[features].to_numpy(dtype=np.float32, copy=True)
    y = frame[target].to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(X).all() or not np.isfinite(y).all() or (y < 0).any():
        raise ValueError(f"{name} contains invalid feature or target values")
    return Split(X, y, first, last)


def sample_training(split: Split, max_rows: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    if max_rows <= 0:
        raise ValueError("Training row cap must be positive")
    if len(split.y) <= max_rows:
        return split.X, split.y
    indices = np.sort(np.random.default_rng(seed).choice(len(split.y), size=max_rows, replace=False))
    return split.X[indices], split.y[indices]


def predict_nonnegative(model: object, X: np.ndarray) -> np.ndarray:
    predictions = np.asarray(model.predict(X), dtype=np.float64).reshape(-1)
    if len(predictions) != len(X) or not np.isfinite(predictions).all():
        raise ValueError("Model returned an invalid prediction")
    return np.maximum(predictions, 0.0)


def train_and_select(
    train: Split, validation: Split, features: list[str], horizon: int, settings: dict
) -> tuple[object, dict, list[dict], list[dict]]:
    """Fit and tune using train/validation only; no test data enters this function."""
    if train.last_origin >= validation.first_origin:
        raise ValueError("Train and validation origin dates overlap")
    seed = int(settings["random_seed"])
    rolling_feature = f"sales_rolling_sum_{horizon}"
    if rolling_feature not in features:
        raise ValueError(f"Cannot form horizon-matched baseline: {rolling_feature} is absent")

    trials: list[dict] = []
    fitted: dict[str, object] = {}
    comparison: list[dict] = []

    def record(name: str, params: dict, model: object, rows_used: int) -> None:
        scores = evaluate(validation.y, predict_nonnegative(model, validation.X))
        if any(value is not None and not np.isfinite(value) for value in scores.values()):
            raise ValueError(f"Nonfinite validation metric for {name}")
        trial = {"model": name, "hyperparameters": params, "train_rows": rows_used, **scores}
        trials.append(trial)
        current = next((row for row in comparison if row["model"] == name), None)
        if current is None or (trial["MAE"], trial["RMSE"]) < (current["MAE"], current["RMSE"]):
            if current is not None:
                comparison.remove(current)
            comparison.append(trial)
            fitted[name] = model
        print(f"{name} {params}: MAE={scores['MAE']:.4f} RMSE={scores['RMSE']:.4f} WAPE={scores['WAPE']}", flush=True)

    baseline = HistoricalSumBaseline(features.index(rolling_feature))
    record("historical_7d_sum", {"feature": rolling_feature}, baseline, 0)

    for alpha in settings["ridge_alphas"]:
        model = make_pipeline(StandardScaler(), Ridge(alpha=float(alpha)))
        model.fit(train.X, train.y)
        record("ridge", {"alpha": float(alpha)}, model, len(train.y))

    forest_settings = settings["random_forest"]
    X_forest, y_forest = sample_training(train, int(settings["max_random_forest_train_rows"]), seed)
    forest = RandomForestRegressor(random_state=seed, **forest_settings)
    forest.fit(X_forest, y_forest)
    record("random_forest", dict(forest_settings), forest, len(y_forest))

    boost_settings = settings["hist_gradient_boosting"]
    X_boost, y_boost = sample_training(train, int(settings["max_hist_gradient_boosting_train_rows"]), seed)
    for leaves in boost_settings["max_leaf_nodes_options"]:
        params = {key: value for key, value in boost_settings.items() if key != "max_leaf_nodes_options"}
        params["max_leaf_nodes"] = int(leaves)
        model = HistGradientBoostingRegressor(loss="absolute_error", random_state=seed, **params)
        model.fit(X_boost, y_boost)
        record("hist_gradient_boosting", {"loss": "absolute_error", **params}, model, len(y_boost))

    comparison.sort(key=lambda row: (row["MAE"], row["RMSE"], row["model"]))
    winner = comparison[0]
    return fitted[winner["model"]], winner, comparison, trials


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False, sort_keys=True) if key == "hyperparameters" else row.get(key) for key in columns})


def save_artifacts(
    model: object, winner: dict, comparison: list[dict], trials: list[dict],
    test_scores: dict, metadata: dict,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    columns = ["model", "MAE", "RMSE", "WAPE", "train_rows", "hyperparameters"]
    write_csv(OUTPUT_DIR / "model_comparison.csv", comparison, columns)
    write_csv(OUTPUT_DIR / "tuning_results.csv", trials, columns)
    joblib.dump(model, OUTPUT_DIR / "best_model.joblib")
    for name, payload in (
        ("validation_metrics.json", {"best_model": winner["model"], **{key: winner[key] for key in ("MAE", "RMSE", "WAPE")}}),
        ("test_metrics.json", {"best_model": winner["model"], **test_scores}),
        ("training_metadata.json", metadata),
    ):
        (OUTPUT_DIR / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Demand forecasting evaluation",
        "",
        f"Selected on validation MAE: **{winner['model']}**",
        "",
        "| Model | Validation MAE | RMSE | WAPE (%) |",
        "|---|---:|---:|---:|",
    ]
    for row in comparison:
        wape = "undefined" if row["WAPE"] is None else f"{row['WAPE']:.2f}"
        lines.append(f"| {row['model']} | {row['MAE']:.4f} | {row['RMSE']:.4f} | {wape} |")
    lines += ["", "## Final test result", ""]
    lines += [f"- MAE: {test_scores['MAE']:.4f}", f"- RMSE: {test_scores['RMSE']:.4f}"]
    lines += [f"- WAPE (%): {test_scores['WAPE']:.2f}" if test_scores["WAPE"] is not None else "- WAPE: undefined (zero actual demand)"]
    lines += ["", "Validation selected the model and hyperparameters. The test split was loaded once, after selection.", ""]
    (OUTPUT_DIR / "evaluation_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    target = target_from_dataset_config(DATASET_CONFIG_PATH)
    manifest, features, horizon = load_manifest(target)
    settings = json.loads(TRAINING_CONFIG_PATH.read_text(encoding="utf-8"))
    train = load_split("train", manifest, features, target)
    validation = load_split("validation", manifest, features, target)
    model, winner, comparison, trials = train_and_select(train, validation, features, horizon, settings)
    # Keep the test set entirely out of model and hyperparameter selection.
    test = load_split("test", manifest, features, target)
    if validation.last_origin >= test.first_origin:
        raise ValueError("Validation and test origin dates overlap")
    test_scores = evaluate(test.y, predict_nonnegative(model, test.X))
    metadata = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "features": features,
        "forecast_horizon_days": horizon,
        "selected_model": winner["model"],
        "selected_hyperparameters": winner["hyperparameters"],
        "selection_metric": "validation MAE",
        "validation_metrics": {key: winner[key] for key in ("MAE", "RMSE", "WAPE")},
        "test_metrics": test_scores,
        "training_rows_for_selected_model": winner["train_rows"],
        "split_rows": {"train": len(train.y), "validation": len(validation.y), "test": len(test.y)},
        "split_origin_ranges": {name: [split.first_origin, split.last_origin] for name, split in (("train", train), ("validation", validation), ("test", test))},
        "random_seed": int(settings["random_seed"]),
        "prediction_postprocessing": "clip at zero",
        "feature_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        "training_config_sha256": hashlib.sha256(TRAINING_CONFIG_PATH.read_bytes()).hexdigest(),
        "python_packages": {"pandas": pd.__version__, "numpy": np.__version__, "scikit_learn": sklearn.__version__, "joblib": joblib.__version__},
    }
    save_artifacts(model, winner, comparison, trials, test_scores, metadata)
    print(f"\nBest validation model: {winner['model']} (MAE={winner['MAE']:.4f})")
    print(f"Final test: MAE={test_scores['MAE']:.4f}, RMSE={test_scores['RMSE']:.4f}, WAPE={test_scores['WAPE']}")
    print(f"Artifacts: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
