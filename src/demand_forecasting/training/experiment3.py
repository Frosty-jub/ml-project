"""Final Sira experiment: LightGBM tuning and robustness without opening test.

Run from the repository root: python -m src.demand_forecasting.training.experiment3
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn
from lightgbm import LGBMRegressor

from .baseline import HistoricalSumBaseline
from .experiment2 import (
    Fold, build_folds, dump_json, fit_lightgbm, git_version, load_pretest, select_rows,
    sha256, summarize, write_csv,
)
from .metrics import evaluate
from .models import FeatureOrderedModel
from .train import (
    DATASET_CONFIG_PATH, MANIFEST_PATH, OUTPUT_DIR, ROOT, TRAINING_CONFIG_PATH,
    load_manifest, predict_nonnegative, target_from_dataset_config,
)


def require_experiment2_reference(folds: list[Fold], settings: dict) -> tuple[dict, dict[str, dict]]:
    """Use Experiment 2 as a frozen, read-only comparison on identical folds."""
    trial_path = OUTPUT_DIR / "experiment2_trials.json"
    fold_path = OUTPUT_DIR / "experiment2_fold_metrics.json"
    definitions_path = OUTPUT_DIR / "validation_folds.json"
    if not all(path.exists() for path in (trial_path, fold_path, definitions_path)):
        raise FileNotFoundError("Run Experiment 2 first to regenerate its reference artifacts")
    definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
    if len(definitions) != len(folds) or any(
        row["fold"] != fold.name or row["train_origin_end"] != fold.train_end
        or row["validation_origin_start"] != fold.validation_start
        or row["validation_origin_end"] != fold.validation_end
        or row["train_rows"] != len(fold.train_indices)
        or row["validation_rows"] != len(fold.validation_indices)
        for row, fold in zip(definitions, folds)
    ):
        raise ValueError("Experiment 3 folds do not match Experiment 2")
    trials = json.loads(trial_path.read_text(encoding="utf-8"))
    reference = next(row for row in trials if row["trial_id"] == "lightgbm_l1")
    if reference["parameters"] != settings["experiment2"]["lightgbm_l1"]:
        raise ValueError("Experiment 2 LightGBM parameters changed")
    previous_folds = {
        row["fold"]: row for row in json.loads(fold_path.read_text(encoding="utf-8"))
        if row["trial_id"] == "lightgbm_l1"
    }
    if set(previous_folds) != {fold.name for fold in folds}:
        raise ValueError("Experiment 2 reference is missing a fold")
    return reference, previous_folds


def segment_masks(actual: np.ndarray, high_cutoff: int) -> dict[str, np.ndarray]:
    if high_cutoff <= 5:
        raise ValueError("High-demand cutoff must exceed the low-demand band")
    return {
        "zero": actual == 0,
        "low_1_5": (actual >= 1) & (actual <= 5),
        "medium_6_to_p95": (actual > 5) & (actual <= high_cutoff),
        "high_above_p95": actual > high_cutoff,
    }


def segment_rows(trial_id: str, fold: Fold, actual: np.ndarray, predicted: np.ndarray,
                 high_cutoff: int) -> list[dict]:
    rows = []
    for name, mask in segment_masks(actual, high_cutoff).items():
        if not mask.any():
            raise ValueError(f"No rows in {name} for {fold.name}")
        scores = evaluate(actual[mask], predicted[mask])
        rows.append({"trial_id": trial_id, "fold": fold.name, "segment": name, "rows": int(mask.sum()),
                     **scores, "mean_actual": float(actual[mask].mean()),
                     "mean_prediction": float(predicted[mask].mean()),
                     "bias_prediction_minus_actual": float((predicted[mask] - actual[mask]).mean())})
    return rows


def score_fold(trial_id: str, model_name: str, model: object, fold: Fold,
               X: np.ndarray, y: np.ndarray, fit_rows: int,
               high_cutoff: int) -> tuple[dict, list[dict], np.ndarray]:
    actual = y[fold.validation_indices]
    predicted = predict_nonnegative(model, X[fold.validation_indices])
    scores = evaluate(actual, predicted)
    if any(value is None or not np.isfinite(value) for value in scores.values()):
        raise ValueError(f"Invalid {trial_id} metrics on {fold.name}")
    row = {"trial_id": trial_id, "model": model_name, "fold": fold.name,
           "train_rows": len(fold.train_indices), "validation_rows": len(fold.validation_indices),
           "fit_rows": fit_rows, **scores}
    return row, segment_rows(trial_id, fold, actual, predicted, high_cutoff), predicted


def diagnose_reference(X: np.ndarray, y: np.ndarray, folds: list[Fold], features: list[str],
                       horizon: int, high_cutoff: int, settings: dict,
                       previous_folds: dict[str, dict], manifest: dict) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Reproduce Experiment 2 LightGBM and analyze errors before new trials."""
    baseline_rows = []
    reference_rows = []
    segments = []
    baseline = HistoricalSumBaseline(features.index(f"sales_rolling_sum_{horizon}"))
    diagnostic = {"segment_definition": {"zero": "target = 0", "low_1_5": "1 <= target <= 5",
                 "medium_6_to_p95": f"6 <= target <= {high_cutoff}",
                 "high_above_p95": f"target > {high_cutoff}"},
                 "high_cutoff_source": "95th percentile of original Experiment 1 train target",
                 "folds": [], "top_absolute_error_examples_fold_4": [],
                 "top_sku_total_absolute_error_fold_4": []}
    seed = int(settings["random_seed"])
    reference_params = settings["experiment2"]["lightgbm_l1"]
    cap = int(settings["experiment2"]["lightgbm_train_rows"])
    for fold in folds:
        base_row, base_segments, _ = score_fold("historical_7d_sum", "baseline", baseline,
                                                fold, X, y, 0, high_cutoff)
        model, fit_rows = fit_lightgbm(X, y, fold.train_indices, reference_params, cap, seed)
        ref_row, ref_segments, predictions = score_fold("exp2_lightgbm_l1", "lightgbm_l1",
                                                        model, fold, X, y, fit_rows, high_cutoff)
        saved = previous_folds[fold.name]
        if any(not np.isclose(ref_row[metric], saved[metric], rtol=0, atol=1e-8)
               for metric in ("MAE", "RMSE", "WAPE")):
            raise ValueError(f"Experiment 2 reference changed on {fold.name}")
        baseline_rows.append(base_row)
        reference_rows.append(ref_row)
        segments.extend(base_segments + ref_segments)
        diagnostic["folds"].append({"fold": fold.name, "overall": ref_row,
                                     "segments": ref_segments})
        print(f"Reference {fold.name}: MAE={ref_row['MAE']:.4f}; baseline={base_row['MAE']:.4f}", flush=True)
        if fold is folds[-1]:
            path = ROOT / manifest["splits"]["validation"]["path"]
            identifiers = pd.read_csv(path, compression="gzip",
                                      usecols=["sku_id", "forecast_origin_date"],
                                      dtype={"sku_id": "string"})
            actual = y[fold.validation_indices]
            if len(identifiers) != len(actual):
                raise ValueError("Fold 4 SKU identifiers do not match validation rows")
            errors = np.abs(predictions - actual)
            top = np.argsort(errors)[-10:][::-1]
            diagnostic["top_absolute_error_examples_fold_4"] = [
                {"sku_id": str(identifiers.iloc[i]["sku_id"]),
                 "origin": str(identifiers.iloc[i]["forecast_origin_date"]),
                 "actual": float(actual[i]), "prediction": float(predictions[i]),
                 "absolute_error": float(errors[i])} for i in top]
            totals = (pd.DataFrame({"sku_id": identifiers["sku_id"], "absolute_error": errors})
                      .groupby("sku_id")["absolute_error"].sum().nlargest(10))
            diagnostic["top_sku_total_absolute_error_fold_4"] = [
                {"sku_id": str(sku), "total_absolute_error": float(value)}
                for sku, value in totals.items()]
    return baseline_rows, reference_rows, segments, diagnostic


def summarize_trial(trial_id: str, model_name: str, params: dict, rows: list[dict],
                    baseline_rows: list[dict], segment_metrics: list[dict]) -> dict:
    result = summarize(trial_id, model_name, params, rows)
    result["objective"] = params.get("objective", "historical_sum")
    result["folds_won_vs_baseline"] = sum(row["MAE"] < baseline["MAE"]
                                         for row, baseline in zip(rows, baseline_rows))
    result["worst_fold_MAE"] = max(row["MAE"] for row in rows)
    result["segment_mean_MAE"] = {
        name: float(np.mean([row["MAE"] for row in segment_metrics
                             if row["trial_id"] == trial_id and row["segment"] == name]))
        for name in ("zero", "low_1_5", "medium_6_to_p95", "high_above_p95")
    }
    return result


def choose_candidate(summaries: list[dict]) -> dict:
    """Keep the Experiment 2 reference unless a new trial lowers mean MAE."""
    eligible = [row for row in summaries if row["trial_id"] != "historical_7d_sum"]
    if not eligible:
        raise ValueError("No machine-learning candidate")
    return min(eligible, key=lambda row: (row["MAE"], row["RMSE"], row["trial_id"]))


def run_trials(X: np.ndarray, y: np.ndarray, folds: list[Fold], features: list[str], horizon: int,
               high_cutoff: int, settings: dict, manifest: dict,
               reference: dict, previous_folds: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict], dict[str, object], dict]:
    baseline_rows, reference_rows, segments, diagnostic = diagnose_reference(
        X, y, folds, features, horizon, high_cutoff, settings, previous_folds, manifest)
    if not np.isclose(float(np.mean([row["MAE"] for row in reference_rows])), reference["MAE"], atol=1e-8):
        raise ValueError("Experiment 2 reference aggregate changed")
    all_fold_rows = baseline_rows + reference_rows
    params_by_trial = {"historical_7d_sum": {"feature": f"sales_rolling_sum_{horizon}"},
                       "exp2_lightgbm_l1": settings["experiment2"]["lightgbm_l1"]}
    names_by_trial = {"historical_7d_sum": "baseline", "exp2_lightgbm_l1": "lightgbm_l1"}
    models_last_fold = {}
    seed = int(settings["random_seed"])
    cap = int(settings["experiment3"]["lightgbm_train_rows_per_fold"])
    for trial_id, params in settings["experiment3"]["trials"].items():
        rows = []
        for fold in folds:
            model, fit_rows = fit_lightgbm(X, y, fold.train_indices, params, cap, seed)
            row, group_rows, _ = score_fold(trial_id, "lightgbm", model, fold, X, y,
                                            fit_rows, high_cutoff)
            rows.append(row)
            segments.extend(group_rows)
            print(f"{trial_id} {fold.name}: MAE={row['MAE']:.4f}", flush=True)
            if fold is folds[-1]:
                models_last_fold[trial_id] = model
        all_fold_rows.extend(rows)
        params_by_trial[trial_id] = params
        names_by_trial[trial_id] = "lightgbm"
    summaries = []
    for trial_id, params in params_by_trial.items():
        rows = [row for row in all_fold_rows if row["trial_id"] == trial_id]
        summaries.append(summarize_trial(trial_id, names_by_trial[trial_id], params,
                                         rows, baseline_rows, segments))
    baseline_mae = next(row["MAE"] for row in summaries if row["trial_id"] == "historical_7d_sum")
    reference_mae = next(row["MAE"] for row in summaries if row["trial_id"] == "exp2_lightgbm_l1")
    for row in summaries:
        row["improvement_vs_baseline_pct"] = 100 * (baseline_mae - row["MAE"]) / baseline_mae
        row["improvement_vs_exp2_lightgbm_pct"] = 100 * (reference_mae - row["MAE"]) / reference_mae
    summaries.sort(key=lambda row: (row["MAE"], row["RMSE"], row["trial_id"]))
    return summaries, all_fold_rows, segments, models_last_fold, diagnostic


def fit_final_candidate(winner: dict, X: np.ndarray, y: np.ndarray, features: list[str],
                        seed: int) -> tuple[FeatureOrderedModel, dict]:
    """Try every permitted pre-test row; sample only if full fit runs out of memory."""
    started = time.perf_counter()
    model = LGBMRegressor(random_state=seed, **winner["parameters"])
    reason = None
    rows = len(y)
    try:
        model.fit(X, y)
    except MemoryError:
        rows = min(500_000, len(y))
        indices = select_rows(np.arange(len(y)), rows, seed)
        model = LGBMRegressor(random_state=seed, **winner["parameters"])
        model.fit(X[indices], y[indices])
        reason = "Full pre-test fit raised MemoryError; deterministic capped sample used"
    return FeatureOrderedModel(model, features), {
        "permitted_rows": len(y), "fit_rows": rows, "sampling_ratio": rows / len(y),
        "random_seed": seed, "sampling_reason": reason,
        "fit_elapsed_seconds": time.perf_counter() - started,
    }


def three_experiment_rows(exp2_comparison: list[dict], exp3_summaries: list[dict],
                          winner_id: str) -> list[dict]:
    result = []
    for row in exp2_comparison:
        first = row["experiment"] == "Experiment 1"
        result.append({"experiment": row["experiment"], "model": row["model"],
                       "purpose": "Explore model families" if first else "Handle zero-heavy demand across time",
                       "validation_strategy": row["validation_strategy"], "MAE": row["MAE"],
                       "MAE_std": row["MAE_std"], "RMSE": row["RMSE"], "WAPE": row["WAPE"],
                       "baseline_improvement_pct": row["MAE_improvement_vs_baseline_percent"],
                       "main_change": "Initial baseline and families" if first else "4 expanding windows; LightGBM and two-stage",
                       "result": "Frozen validation result", "decision": "Historical record"})
    for row in exp3_summaries:
        result.append({"experiment": "Experiment 3", "model": row["trial_id"],
                       "purpose": "Optimize and stress-test Experiment 2 candidate",
                       "validation_strategy": "Same 4 expanding windows as Experiment 2",
                       "MAE": row["MAE"], "MAE_std": row["MAE_std"], "RMSE": row["RMSE"],
                       "WAPE": row["WAPE"], "baseline_improvement_pct": row["improvement_vs_baseline_pct"],
                       "main_change": row["objective"], "result": f"{row['folds_won_vs_baseline']}/4 folds beat baseline",
                       "decision": "Final candidate" if row["trial_id"] == winner_id else "Reference or rejected"})
    return result


def main() -> None:
    if git_version()["branch"] != "Sira":
        raise ValueError("Experiment 3 must run on branch Sira")
    target = target_from_dataset_config(DATASET_CONFIG_PATH)
    manifest, features, horizon = load_manifest(target)
    settings = json.loads(TRAINING_CONFIG_PATH.read_text(encoding="utf-8"))
    X, y, dates, source = load_pretest(manifest, features, target)
    folds = build_folds(dates, horizon, settings["experiment2"]["folds"])
    reference, previous_folds = require_experiment2_reference(folds, settings)
    original_train = y[:source["train"]["rows"]]
    high_cutoff = int(np.quantile(original_train, .95))
    distribution = {"train_rows": len(original_train), "mean": float(original_train.mean()),
                    "variance": float(original_train.var()), "variance_to_mean": float(original_train.var()/original_train.mean()),
                    "zero_ratio": float(np.mean(original_train == 0)),
                    "low_le_1_ratio": float(np.mean(original_train <= 1)),
                    "low_le_5_ratio": float(np.mean(original_train <= 5)), "p95": high_cutoff}
    print(f"Train target distribution: {distribution}", flush=True)
    summaries, fold_rows, segment_metrics, fold_models, diagnostic = run_trials(
        X, y, folds, features, horizon, high_cutoff, settings, manifest, reference, previous_folds)
    diagnostic["train_target_distribution"] = distribution
    diagnostic["decision_for_two_stage_refinement"] = (
        "Not retried: zero predictions have low MAE relative to high-demand errors; "
        "Experiment 2 two-stage did not improve mean MAE over L1 reference."
    )
    winner = choose_candidate(summaries)
    model_dir = OUTPUT_DIR / "experiment3_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    for row in summaries:
        if row["trial_id"] in fold_models:
            path = model_dir / f"{row['trial_id']}_fold4.joblib"
            joblib.dump(fold_models[row["trial_id"]], path)
            row["fold4_model_artifact"] = str(path.relative_to(ROOT)).replace("\\", "/")
        elif row["trial_id"] == "exp2_lightgbm_l1":
            row["fold4_model_artifact"] = "artifacts/training/experiment2_models/lightgbm_l1.joblib"
        else:
            row["fold4_model_artifact"] = "artifacts/training/experiment2_models/historical_7d_sum.joblib"
    final_model, training = fit_final_candidate(winner, X, y, features, int(settings["random_seed"]))
    final_path = OUTPUT_DIR / "final_candidate_model.joblib"
    joblib.dump(final_model, final_path)
    reloaded = joblib.load(final_path)
    probe = X[folds[-1].validation_indices[:20]]
    if reloaded.feature_names != features or not np.allclose(final_model.predict(probe), reloaded.predict(probe)):
        raise ValueError("Final artifact does not reproduce its predictions")
    exp2_comparison = json.loads((OUTPUT_DIR / "experiment_comparison.json").read_text(encoding="utf-8"))
    combined = three_experiment_rows(exp2_comparison, summaries, winner["trial_id"])
    columns = ["experiment", "model", "purpose", "validation_strategy", "MAE", "MAE_std",
               "RMSE", "WAPE", "baseline_improvement_pct", "main_change", "result", "decision"]
    write_csv(OUTPUT_DIR / "experiment1_2_3_summary.csv", combined, columns)
    dump_json(OUTPUT_DIR / "experiment1_2_3_summary.json", combined)
    fold_columns = ["trial_id", "model", "fold", "train_rows", "validation_rows", "fit_rows",
                    "MAE", "RMSE", "WAPE"]
    write_csv(OUTPUT_DIR / "experiment3_fold_metrics.csv", fold_rows, fold_columns)
    dump_json(OUTPUT_DIR / "experiment3_fold_metrics.json", fold_rows)
    segment_columns = ["trial_id", "fold", "segment", "rows", "MAE", "RMSE", "WAPE",
                       "mean_actual", "mean_prediction", "bias_prediction_minus_actual"]
    write_csv(OUTPUT_DIR / "experiment3_segment_metrics.csv", segment_metrics, segment_columns)
    dump_json(OUTPUT_DIR / "experiment3_segment_metrics.json", segment_metrics)
    dump_json(OUTPUT_DIR / "experiment3_error_analysis.json", diagnostic)
    trial_columns = ["trial_id", "objective", "MAE", "MAE_std", "RMSE", "RMSE_std", "WAPE", "WAPE_std",
                     "improvement_vs_exp2_lightgbm_pct", "improvement_vs_baseline_pct",
                     "folds_won_vs_baseline", "worst_fold_MAE", "fold4_model_artifact"]
    write_csv(OUTPUT_DIR / "experiment3_trials.csv", summaries, trial_columns)
    dump_json(OUTPUT_DIR / "experiment3_trials.json", summaries)
    comparison = [{"model": row["trial_id"], "objective": row["objective"],
                   "mean_MAE": row["MAE"], "std_MAE": row["MAE_std"], "mean_RMSE": row["RMSE"],
                   "mean_WAPE": row["WAPE"],
                   "improvement_vs_exp2_lightgbm_pct": row["improvement_vs_exp2_lightgbm_pct"],
                   "improvement_vs_baseline_pct": row["improvement_vs_baseline_pct"],
                   "folds_won_vs_baseline": row["folds_won_vs_baseline"],
                   "worst_fold_MAE": row["worst_fold_MAE"],
                   "zero_MAE": row["segment_mean_MAE"]["zero"],
                   "low_MAE": row["segment_mean_MAE"]["low_1_5"],
                   "high_MAE": row["segment_mean_MAE"]["high_above_p95"],
                   "notes": "Final candidate" if row["trial_id"] == winner["trial_id"] else "Validation trial"}
                  for row in summaries]
    write_csv(OUTPUT_DIR / "experiment3_comparison.csv", comparison, list(comparison[0]))
    dump_json(OUTPUT_DIR / "experiment3_comparison.json", comparison)
    best_metrics = {key: winner[key] for key in ("trial_id", "objective", "MAE", "MAE_std", "RMSE", "RMSE_std",
                                             "WAPE", "WAPE_std", "folds_won_vs_baseline", "worst_fold_MAE",
                                             "improvement_vs_exp2_lightgbm_pct", "improvement_vs_baseline_pct",
                                             "segment_mean_MAE")}
    dump_json(OUTPUT_DIR / "final_candidate_metrics.json", best_metrics)
    dump_json(OUTPUT_DIR / "final_candidate_params.json", winner["parameters"])
    metadata = {"experiment_number": 3, "experiment_name": "Sira Experiment 3",
                "trained_at_utc": datetime.now(timezone.utc).isoformat(), "model_name": winner["trial_id"],
                "objective": winner["objective"], "hyperparameters": winner["parameters"],
                "random_seed": int(settings["random_seed"]), "target": target,
                "forecast_horizon_days": horizon, "feature_order": features,
                "prediction_postprocessing": "clip to nonnegative",
                "validation_strategy": "Experiment 2 identical 4 expanding windows; equal mean of fold MAE",
                "fold_date_ranges": json.loads((OUTPUT_DIR / "validation_folds.json").read_text(encoding="utf-8")),
                "fold_metrics": [row for row in fold_rows if row["trial_id"] == winner["trial_id"]],
                "aggregate_metrics": best_metrics,
                "baseline_metrics": next(row for row in summaries if row["trial_id"] == "historical_7d_sum"),
                "experiment2_reference_metrics": reference,
                "model_artifact_path": str(final_path.relative_to(ROOT)).replace("\\", "/"),
                "training": training, "training_origin_range": [str(dates.min()), str(dates.max())],
                "source_splits": source, "source_workbook_sha256": sha256(ROOT / "data/raw/online_retail_II.xlsx"),
                "feature_manifest_sha256": sha256(MANIFEST_PATH),
                "training_config_sha256": sha256(TRAINING_CONFIG_PATH),
                "code_sha256": {name: sha256(ROOT / name) for name in
                    ("src/demand_forecasting/training/experiment3.py",
                     "src/demand_forecasting/training/experiment2.py",
                     "src/demand_forecasting/training/models.py",
                     "src/demand_forecasting/training/metrics.py")},
                "git": git_version(),
                "environment": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__,
                                "scikit_learn": sklearn.__version__, "lightgbm": lightgbm.__version__,
                                "joblib": joblib.__version__},
                "test_set_used": False,
                "final_test_limitation": "Experiment 1 test aggregate was seen; no later untouched dates exist.",
                "recommended_quality_gates_not_implemented": {
                    "performance": "candidate mean validation MAE < baseline mean validation MAE",
                    "robustness": "candidate wins >=3/4 folds (recommended project policy)",
                    "integrity": "load, predict, finite and nonnegative outputs",
                    "features": "inference feature names/order match metadata"}}
    dump_json(OUTPUT_DIR / "final_candidate_metadata.json", metadata)
    print(f"Final candidate: {winner['trial_id']} mean MAE={winner['MAE']:.4f}, "
          f"baseline={next(row['MAE'] for row in summaries if row['trial_id']=='historical_7d_sum'):.4f}, "
          f"fit rows={training['fit_rows']:,}", flush=True)
    print(f"Artifacts: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
