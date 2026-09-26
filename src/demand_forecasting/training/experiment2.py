"""Experiment 2: expanding-window validation on pre-test features only.

Run from the repository root: python -m src.demand_forecasting.training.experiment2
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn
from lightgbm import LGBMRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import HistoricalSumBaseline
from .metrics import evaluate
from .models import FeatureOrderedModel, TwoStageDemandModel
from .train import (
    DATASET_CONFIG_PATH,
    MANIFEST_PATH,
    OUTPUT_DIR,
    ROOT,
    TRAINING_CONFIG_PATH,
    load_manifest,
    load_split,
    predict_nonnegative,
    target_from_dataset_config,
)


@dataclass(frozen=True)
class Fold:
    name: str
    train_indices: np.ndarray
    validation_indices: np.ndarray
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str


def select_rows(indices: np.ndarray, cap: int, seed: int) -> np.ndarray:
    if cap <= 0:
        raise ValueError("Training row cap must be positive")
    if len(indices) <= cap:
        return indices
    return np.sort(np.random.default_rng(seed).choice(indices, cap, replace=False))


def load_pretest(manifest: dict, features: list[str], target: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Only the existing train and validation files are opened here."""
    arrays = []
    dates = []
    source = {}
    for name in ("train", "validation"):
        split = load_split(name, manifest, features, target)
        path = ROOT / manifest["splits"][name]["path"]
        origins = pd.read_csv(path, compression="gzip", usecols=["forecast_origin_date"])["forecast_origin_date"]
        if len(origins) != len(split.y):
            raise ValueError(f"{name} origin count changed during loading")
        parsed = pd.to_datetime(origins, errors="raise").to_numpy(dtype="datetime64[D]")
        if str(parsed.min()) != split.first_origin or str(parsed.max()) != split.last_origin:
            raise ValueError(f"{name} origin dates do not match manifest")
        arrays.append((split.X, split.y))
        dates.append(parsed)
        source[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path),
                        "rows": len(split.y), "first_origin": split.first_origin, "last_origin": split.last_origin}
    if source["validation"]["last_origin"] >= manifest["splits"]["test"]["first_origin_date"]:
        raise ValueError("Pre-test data overlaps the final test period")
    return (np.concatenate([item[0] for item in arrays]),
            np.concatenate([item[1] for item in arrays]), np.concatenate(dates), source)


def build_folds(dates: np.ndarray, horizon: int, definitions: list[dict]) -> list[Fold]:
    if horizon <= 0 or not definitions:
        raise ValueError("A positive horizon and at least one fold are required")
    folds = []
    previous_end = None
    for number, definition in enumerate(definitions, 1):
        label_end = np.datetime64(definition["train_label_end"], "D")
        train_end = label_end - np.timedelta64(horizon, "D")
        validation_start = np.datetime64(definition["validation_start"], "D")
        validation_end = np.datetime64(definition["validation_end"], "D")
        if not train_end < validation_start or not label_end < validation_start:
            raise ValueError("Train labels overlap validation in a fold")
        if validation_end < validation_start or (previous_end is not None and validation_start <= previous_end):
            raise ValueError("Validation folds are empty or overlap")
        train_indices = np.flatnonzero(dates <= train_end)
        validation_indices = np.flatnonzero((dates >= validation_start) & (dates <= validation_end))
        if len(train_indices) == 0 or len(validation_indices) == 0:
            raise ValueError("A configured fold has no training or validation rows")
        folds.append(Fold(f"fold_{number}", train_indices, validation_indices,
                          str(dates[train_indices].min()), str(dates[train_indices].max()),
                          str(dates[validation_indices].min()), str(dates[validation_indices].max())))
        previous_end = validation_end
    return folds


def fit_forest(X: np.ndarray, y: np.ndarray, indices: np.ndarray, params: dict, cap: int, seed: int) -> tuple[object, int]:
    chosen = select_rows(indices, cap, seed)
    model = RandomForestRegressor(random_state=seed, **params)
    model.fit(X[chosen], y[chosen])
    return model, len(chosen)


def fit_lightgbm(X: np.ndarray, y: np.ndarray, indices: np.ndarray, params: dict, cap: int, seed: int) -> tuple[object, int]:
    chosen = select_rows(indices, cap, seed)
    model = LGBMRegressor(random_state=seed, **params)
    model.fit(X[chosen], y[chosen])
    return model, len(chosen)


def fit_two_stage(X: np.ndarray, y: np.ndarray, indices: np.ndarray, settings: dict, seed: int) -> tuple[object, object, dict]:
    classifier_rows = select_rows(indices, int(settings["classifier_train_rows"]), seed)
    classifier = make_pipeline(StandardScaler(), LogisticRegression(max_iter=300, random_state=seed))
    classifier.fit(X[classifier_rows], y[classifier_rows] > 0)
    positive_rows = indices[y[indices] > 0]
    if len(positive_rows) == 0:
        raise ValueError("Two-stage regressor has no positive-demand rows")
    regressor, rows = fit_lightgbm(X, y, positive_rows, settings["positive_regressor"],
                                  int(settings["positive_regressor_train_rows"]), seed)
    return classifier, regressor, {"classifier_rows": len(classifier_rows), "positive_regressor_rows": rows}


def refit_selected(winner: dict, X: np.ndarray, y: np.ndarray, features: list[str], horizon: int,
                   settings: dict) -> tuple[FeatureOrderedModel, object]:
    """Fit the selected configuration on all pre-test rows after CV selection."""
    indices = np.arange(len(y))
    seed = int(settings["random_seed"])
    config = settings["experiment2"]
    if winner["model"] == "historical_7d_sum":
        model, rows = HistoricalSumBaseline(features.index(f"sales_rolling_sum_{horizon}")), 0
    elif winner["model"] == "random_forest":
        model, rows = fit_forest(X, y, indices, winner["parameters"],
                                 int(config["random_forest_train_rows"]), seed)
    elif winner["model"] == "lightgbm_l1":
        model, rows = fit_lightgbm(X, y, indices, winner["parameters"],
                                  int(config["lightgbm_train_rows"]), seed)
    elif winner["model"] == "two_stage":
        classifier, regressor, rows = fit_two_stage(X, y, indices, config["two_stage"], seed)
        model = TwoStageDemandModel(classifier, regressor, winner["parameters"]["threshold"])
    else:
        raise ValueError(f"Unknown selected model: {winner['model']}")
    return FeatureOrderedModel(model, features), rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize(trial_id: str, model_name: str, params: dict, fold_rows: list[dict]) -> dict:
    scores = {name: [row[name] for row in fold_rows] for name in ("MAE", "RMSE", "WAPE")}
    if any(value is None or not np.isfinite(value) for values in scores.values() for value in values):
        raise ValueError(f"Nonfinite fold metric for {trial_id}")
    return {"trial_id": trial_id, "model": model_name, "parameters": params,
            "MAE": float(np.mean(scores["MAE"])), "MAE_std": float(np.std(scores["MAE"])),
            "RMSE": float(np.mean(scores["RMSE"])), "RMSE_std": float(np.std(scores["RMSE"])),
            "WAPE": float(np.mean(scores["WAPE"])), "WAPE_std": float(np.std(scores["WAPE"])),
            "fold_count": len(fold_rows)}


def run_experiment(X: np.ndarray, y: np.ndarray, folds: list[Fold], features: list[str], horizon: int,
                   settings: dict) -> tuple[list[dict], list[dict], dict[str, object]]:
    """All trial decisions are based on identical pre-test folds."""
    rolling = f"sales_rolling_sum_{horizon}"
    if rolling not in features:
        raise ValueError(f"Missing baseline feature: {rolling}")
    seed = int(settings["random_seed"])
    config = settings["experiment2"]
    trial_specs = [("historical_7d_sum", "historical_7d_sum", {"feature": rolling})]
    trial_specs += [(name, "random_forest", params) for name, params in config["random_forest_trials"].items()]
    trial_specs += [("lightgbm_l1", "lightgbm_l1", config["lightgbm_l1"])]
    trial_specs += [(f"two_stage_t{threshold:g}", "two_stage", {"threshold": float(threshold),
                     "classifier": "scaled_logistic_regression", "positive_regressor": config["two_stage"]["positive_regressor"]})
                    for threshold in config["two_stage"]["thresholds"]]
    metrics_by_trial = {trial_id: [] for trial_id, _, _ in trial_specs}
    model_by_trial = {}
    fold_metrics = []
    for fold in folds:
        train, validation = fold.train_indices, fold.validation_indices
        print(f"{fold.name}: train={len(train):,} validation={len(validation):,}", flush=True)
        models = {"historical_7d_sum": HistoricalSumBaseline(features.index(rolling))}
        rows_used = {"historical_7d_sum": 0}
        for name, params in config["random_forest_trials"].items():
            models[name], rows_used[name] = fit_forest(X, y, train, params,
                int(config["random_forest_train_rows"]), seed)
        models["lightgbm_l1"], rows_used["lightgbm_l1"] = fit_lightgbm(X, y, train,
            config["lightgbm_l1"], int(config["lightgbm_train_rows"]), seed)
        classifier, positive_regressor, two_stage_rows = fit_two_stage(X, y, train, config["two_stage"], seed)
        for threshold in config["two_stage"]["thresholds"]:
            name = f"two_stage_t{threshold:g}"
            models[name] = TwoStageDemandModel(classifier, positive_regressor, threshold)
            rows_used[name] = two_stage_rows
        for trial_id, model_name, params in trial_specs:
            prediction = predict_nonnegative(models[trial_id], X[validation])
            scores = evaluate(y[validation], prediction)
            row = {"trial_id": trial_id, "model": model_name, "fold": fold.name,
                   "train_rows": len(train), "validation_rows": len(validation),
                   "fit_rows": rows_used[trial_id], **scores}
            fold_metrics.append(row)
            metrics_by_trial[trial_id].append(row)
            print(f"  {trial_id}: MAE={scores['MAE']:.4f} RMSE={scores['RMSE']:.4f} WAPE={scores['WAPE']:.2f}%", flush=True)
        if fold is folds[-1]:
            model_by_trial = models
    summaries = [summarize(trial_id, model_name, params, metrics_by_trial[trial_id])
                 for trial_id, model_name, params in trial_specs]
    baseline_mae = summaries[0]["MAE"]
    for row in summaries:
        row["MAE_improvement_vs_baseline_percent"] = 100 * (baseline_mae - row["MAE"]) / baseline_mae
    summaries.sort(key=lambda row: (row["MAE"], row["RMSE"], row["trial_id"]))
    return summaries, fold_metrics, model_by_trial


def previous_experiment_rows() -> list[dict]:
    path = ROOT / "config" / "experiment1_reference.json"
    reference = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    workbook = ROOT / "data" / "raw" / "online_retail_II.xlsx"
    if not workbook.exists() or sha256(workbook) != reference["source_workbook_sha256"]:
        raise ValueError("Experiment 1 reference requires the original source workbook")
    if manifest["configuration_sha256"] != reference["pipeline_config_sha256"] or any(
        manifest["splits"][name]["rows"] != rows for name, rows in reference["split_rows"].items()
    ):
        raise ValueError("Experiment 1 reference belongs to a different pipeline or split")
    previous = reference["rows"]
    baseline = next(float(row["MAE"]) for row in previous if row["model"] == "historical_7d_sum")
    return [{"experiment": "Experiment 1", "model": row["model"], "validation_strategy": reference["validation_strategy"],
             "MAE": float(row["MAE"]), "MAE_std": "", "RMSE": float(row["RMSE"]), "WAPE": float(row["WAPE"]),
             "MAE_improvement_vs_baseline_percent": 100 * (baseline - float(row["MAE"])) / baseline,
             "hyperparameter_summary": json.dumps(row["hyperparameters"], sort_keys=True),
             "notes": "Frozen Experiment 1 result; single period, not directly comparable with rolling mean"}
            for row in previous]


def git_version() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    return {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
            "working_tree_dirty": bool(git("status", "--porcelain"))}


def main() -> None:
    target = target_from_dataset_config(DATASET_CONFIG_PATH)
    manifest, features, horizon = load_manifest(target)
    settings = json.loads(TRAINING_CONFIG_PATH.read_text(encoding="utf-8"))
    if git_version()["branch"] != "Sira":
        raise ValueError("Experiment 2 must run on branch Sira")
    X, y, dates, source = load_pretest(manifest, features, target)
    folds = build_folds(dates, horizon, settings["experiment2"]["folds"])
    original_train_rows = source["train"]["rows"]
    zero_ratios = {"train": {f"target_{label}": float(np.mean(predicate(y[:original_train_rows])))
                              for label, predicate in (("eq_0", lambda a: a == 0),
                                                       ("le_1", lambda a: a <= 1),
                                                       ("le_5", lambda a: a <= 5))},
                   "original_validation": {f"target_{label}": float(np.mean(predicate(y[original_train_rows:])))
                                           for label, predicate in (("eq_0", lambda a: a == 0),
                                                                    ("le_1", lambda a: a <= 1),
                                                                    ("le_5", lambda a: a <= 5))}}
    print(f"Zero/low target ratios: {zero_ratios}", flush=True)
    summaries, fold_metrics, models = run_experiment(X, y, folds, features, horizon, settings)
    winner = summaries[0]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_dir = OUTPUT_DIR / "experiment2_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    for row in summaries:
        path = model_dir / f"{row['trial_id']}.joblib"
        joblib.dump(models[row["trial_id"]], path)
        row["model_artifact_path"] = str(path.relative_to(ROOT)).replace("\\", "/")
    selected_model, final_fit_rows = refit_selected(winner, X, y, features, horizon, settings)
    selected_path = OUTPUT_DIR / "best_candidate_model.joblib"
    joblib.dump(selected_model, selected_path)
    loaded = joblib.load(selected_path)
    probe = X[folds[-1].validation_indices[:20]]
    if loaded.feature_names != features or not np.allclose(loaded.predict(probe), selected_model.predict(probe)):
        raise ValueError("Saved candidate did not reproduce its predictions")
    fold_definitions = [{"fold": fold.name, "train_origin_start": fold.train_start, "train_origin_end": fold.train_end,
                         "validation_origin_start": fold.validation_start, "validation_origin_end": fold.validation_end,
                         "train_rows": len(fold.train_indices), "validation_rows": len(fold.validation_indices),
                         "minimum_label_gap_days": horizon}
                        for fold in folds]
    dump_json(OUTPUT_DIR / "validation_folds.json", fold_definitions)
    dump_json(OUTPUT_DIR / "baseline_metrics.json", next(row for row in summaries if row["trial_id"] == "historical_7d_sum"))
    dump_json(OUTPUT_DIR / "best_candidate_metrics.json", {key: winner[key] for key in
              ("trial_id", "model", "MAE", "MAE_std", "RMSE", "RMSE_std", "WAPE", "WAPE_std", "MAE_improvement_vs_baseline_percent")})
    dump_json(OUTPUT_DIR / "best_candidate_params.json", winner["parameters"])
    dump_json(OUTPUT_DIR / "feature_list.json", {"target": target, "forecast_horizon_days": horizon, "features": features})
    dump_json(OUTPUT_DIR / "experiment2_fold_metrics.json", fold_metrics)
    dump_json(OUTPUT_DIR / "experiment2_trials.json", summaries)
    write_csv(OUTPUT_DIR / "experiment2_fold_metrics.csv", fold_metrics,
              ["trial_id", "model", "fold", "train_rows", "validation_rows", "fit_rows", "MAE", "RMSE", "WAPE"])
    comparison = previous_experiment_rows() + [
        {"experiment": "Experiment 2", "model": row["trial_id"], "validation_strategy": "4 expanding windows; mean of fold metrics",
         "MAE": row["MAE"], "MAE_std": row["MAE_std"], "RMSE": row["RMSE"], "WAPE": row["WAPE"],
         "MAE_improvement_vs_baseline_percent": row["MAE_improvement_vs_baseline_percent"],
         "hyperparameter_summary": json.dumps(row["parameters"], sort_keys=True),
         "notes": "Compared with Experiment 2 rolling baseline on identical folds"} for row in summaries]
    columns = ["experiment", "model", "validation_strategy", "MAE", "MAE_std", "RMSE", "WAPE",
               "MAE_improvement_vs_baseline_percent", "hyperparameter_summary", "notes"]
    write_csv(OUTPUT_DIR / "experiment_comparison.csv", comparison, columns)
    dump_json(OUTPUT_DIR / "experiment_comparison.json", comparison)
    metadata = {"experiment_name": "Sira Experiment 2", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "selection_metric": "mean validation MAE across folds", "selected_trial": winner["trial_id"],
                "selected_model": winner["model"], "selected_metrics": {key: winner[key] for key in ("MAE", "MAE_std", "RMSE", "WAPE")},
                "selected_params": winner["parameters"], "selected_artifact": str(selected_path.relative_to(ROOT)).replace("\\", "/"),
                "selected_final_fit_rows": final_fit_rows,
                "selected_final_fit_origin_range": [str(dates.min()), str(dates.max())],
                "candidate_refit_after_selection": True,
                "random_seed": int(settings["random_seed"]), "target": target, "forecast_horizon_days": horizon,
                "feature_order": features, "prediction_postprocessing": "clip to nonnegative",
                "validation_strategy": "expanding-window, fixed calendar folds, equal mean of fold metrics",
                "folds": fold_definitions, "zero_low_demand_ratios": zero_ratios, "trials": summaries,
                "source_splits": source, "feature_manifest_sha256": sha256(MANIFEST_PATH),
                "training_config_sha256": sha256(TRAINING_CONFIG_PATH), "git": git_version(),
                "code_sha256": {name: sha256(ROOT / name) for name in
                    ("src/demand_forecasting/training/experiment2.py", "src/demand_forecasting/training/models.py",
                     "src/demand_forecasting/training/train.py",
                     "src/demand_forecasting/training/metrics.py", "config/experiment1_reference.json")},
                "environment": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__,
                                "scikit_learn": sklearn.__version__, "lightgbm": lightgbm.__version__, "joblib": joblib.__version__},
                "test_set_used": False,
                "holdout_limitation": "The original test aggregate was seen in Experiment 1; no later untouched dates exist in this dataset."}
    dump_json(OUTPUT_DIR / "experiment2_training_metadata.json", metadata)
    print(f"Selected {winner['trial_id']}: mean MAE={winner['MAE']:.4f}; baseline={next(r['MAE'] for r in summaries if r['trial_id']=='historical_7d_sum'):.4f}")
    print(f"Artifacts: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
