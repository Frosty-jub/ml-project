"""Verify the already selected Sira candidate using every train row per fold.

This is a robustness check only: it does not select models or open the test set.
Run from the repository root:
python -m src.demand_forecasting.training.verify_full_folds
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
from lightgbm import LGBMRegressor

from .experiment2 import build_folds, dump_json, load_pretest, write_csv
from .experiment3 import require_experiment2_reference
from .metrics import evaluate
from .train import (
    DATASET_CONFIG_PATH, OUTPUT_DIR, TRAINING_CONFIG_PATH, load_manifest,
    predict_nonnegative, target_from_dataset_config,
)


def main() -> None:
    target = target_from_dataset_config(DATASET_CONFIG_PATH)
    manifest, features, horizon = load_manifest(target)
    settings = json.loads(TRAINING_CONFIG_PATH.read_text(encoding="utf-8"))
    X, y, dates, _ = load_pretest(manifest, features, target)
    folds = build_folds(dates, horizon, settings["experiment2"]["folds"])
    require_experiment2_reference(folds, settings)

    metadata_path = OUTPUT_DIR / "final_candidate_metadata.json"
    selected = json.loads(metadata_path.read_text(encoding="utf-8"))
    trial_id = "l1_more_trees"
    params = settings["experiment3"]["trials"][trial_id]
    if selected["model_name"] != trial_id or selected["hyperparameters"] != params:
        raise ValueError("Final candidate has changed; full-fold check is limited to l1_more_trees")
    if selected["feature_order"] != features or selected["test_set_used"] is not False:
        raise ValueError("Final candidate metadata does not match the pre-test feature protocol")

    previous = json.loads((OUTPUT_DIR / "experiment3_fold_metrics.json").read_text(encoding="utf-8"))
    sampled = {row["fold"]: row for row in previous if row["trial_id"] == trial_id}
    baseline = {row["fold"]: row for row in previous if row["trial_id"] == "historical_7d_sum"}
    if set(sampled) != {fold.name for fold in folds} or set(baseline) != set(sampled):
        raise ValueError("Sampled candidate/baseline fold metrics are incomplete")

    seed = int(settings["random_seed"])
    rows = []
    for fold in folds:
        started = time.perf_counter()
        model = LGBMRegressor(random_state=seed, **params)
        model.fit(X[fold.train_indices], y[fold.train_indices])
        predictions = predict_nonnegative(model, X[fold.validation_indices])
        scores = evaluate(y[fold.validation_indices], predictions)
        if any(value is None or not np.isfinite(value) for value in scores.values()):
            raise ValueError(f"Nonfinite full-fold metrics on {fold.name}")
        row = {"fold": fold.name, "trial_id": trial_id,
               "train_rows_available": len(fold.train_indices),
               "train_rows_used": len(fold.train_indices),
               "validation_rows": len(fold.validation_indices),
               "train_origin_end": fold.train_end,
               "validation_origin_start": fold.validation_start,
               "validation_origin_end": fold.validation_end,
               **scores, "sampled_MAE": sampled[fold.name]["MAE"],
               "sampled_RMSE": sampled[fold.name]["RMSE"],
               "sampled_WAPE": sampled[fold.name]["WAPE"],
               "baseline_MAE": baseline[fold.name]["MAE"],
               "beats_baseline": scores["MAE"] < baseline[fold.name]["MAE"],
               "elapsed_seconds": time.perf_counter() - started}
        rows.append(row)
        print(f"{fold.name}: full rows={row['train_rows_used']:,}; "
              f"MAE={row['MAE']:.4f}; sampled={row['sampled_MAE']:.4f}; "
              f"baseline={row['baseline_MAE']:.4f}", flush=True)

    aggregate = {metric: {"mean": float(np.mean([row[metric] for row in rows])),
                          "std": float(np.std([row[metric] for row in rows]))}
                 for metric in ("MAE", "RMSE", "WAPE")}
    sampled_aggregate = {metric: float(np.mean([row[f"sampled_{metric}"] for row in rows]))
                         for metric in ("MAE", "RMSE", "WAPE")}
    baseline_mean = float(np.mean([row["baseline_MAE"] for row in rows]))
    summary = {"verification_name": "Final candidate full-row fold robustness check",
               "verified_at_utc": datetime.now(timezone.utc).isoformat(),
               "model": trial_id, "objective": params["objective"],
               "protocol": "Same Experiment 2/3 folds, features, target, seed, metrics, clipping; full train rows per fold",
               "selection_changed": False, "test_set_used": False,
               "fold_count": len(rows), "folds_won_vs_baseline": sum(row["beats_baseline"] for row in rows),
               "aggregate": aggregate, "sampled_fold_mean": sampled_aggregate,
               "baseline_mean_MAE": baseline_mean,
               "full_minus_sampled_MAE": aggregate["MAE"]["mean"] - sampled_aggregate["MAE"],
               "MAE_improvement_vs_baseline_pct":
                   100 * (baseline_mean - aggregate["MAE"]["mean"]) / baseline_mean,
               "training_rows_per_fold": [row["train_rows_used"] for row in rows],
               "note": "This check uses validation already used for model selection and is not a new holdout."}
    write_csv(OUTPUT_DIR / "final_candidate_full_fold_metrics.csv", rows, list(rows[0]))
    dump_json(OUTPUT_DIR / "final_candidate_full_fold_metrics.json", rows)
    dump_json(OUTPUT_DIR / "final_candidate_full_fold_summary.json", summary)
    print(f"Full-fold mean MAE={aggregate['MAE']['mean']:.4f}; "
          f"sampled-fold mean MAE={sampled_aggregate['MAE']:.4f}; "
          f"wins={summary['folds_won_vs_baseline']}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
