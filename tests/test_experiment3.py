from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np

from src.demand_forecasting.training.experiment3 import (
    choose_candidate, fit_final_candidate, require_experiment2_reference,
    segment_rows, three_experiment_rows,
)
from src.demand_forecasting.training.experiment2 import Fold, fit_lightgbm


class Experiment3Tests(unittest.TestCase):
    def test_experiment3_rejects_changed_experiment2_fold(self) -> None:
        fold = Fold("fold_1", np.array([0, 1]), np.array([2, 3]),
                    "2020-01-01", "2020-01-02", "2020-01-10", "2020-01-11")
        settings = {"experiment2": {"lightgbm_l1": {"objective": "regression_l1"}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "experiment2_trials.json").write_text(json.dumps([
                {"trial_id": "lightgbm_l1", "parameters": settings["experiment2"]["lightgbm_l1"]}]))
            (root / "experiment2_fold_metrics.json").write_text(json.dumps([
                {"trial_id": "lightgbm_l1", "fold": "fold_1", "MAE": 1.0}]))
            fold_info = {"fold": "fold_1", "train_origin_end": "2020-01-02",
                         "validation_origin_start": "2020-01-10", "validation_origin_end": "2020-01-11",
                         "train_rows": 2, "validation_rows": 2}
            path = root / "validation_folds.json"
            path.write_text(json.dumps([fold_info]))
            with patch("src.demand_forecasting.training.experiment3.OUTPUT_DIR", root):
                self.assertEqual(require_experiment2_reference([fold], settings)[0]["trial_id"],
                                 "lightgbm_l1")
                fold_info["validation_origin_end"] = "2020-01-12"
                path.write_text(json.dumps([fold_info]))
                with self.assertRaisesRegex(ValueError, "do not match"):
                    require_experiment2_reference([fold], settings)

    def test_reference_remains_candidate_when_new_trial_is_worse(self) -> None:
        rows = [{"trial_id": "historical_7d_sum", "MAE": 20.0, "RMSE": 80.0},
                {"trial_id": "exp2_lightgbm_l1", "MAE": 16.0, "RMSE": 70.0},
                {"trial_id": "new_trial", "MAE": 16.1, "RMSE": 60.0}]
        self.assertEqual(choose_candidate(rows)["trial_id"], "exp2_lightgbm_l1")
        rows[-1]["MAE"] = 15.9
        self.assertEqual(choose_candidate(rows)["trial_id"], "new_trial")

    def test_segment_analysis_reports_zero_bias_and_finite_metrics(self) -> None:
        fold = Fold("fold_1", np.array([0]), np.array([1, 2, 3, 4]),
                    "2020-01-01", "2020-01-01", "2020-01-09", "2020-01-12")
        rows = segment_rows("trial", fold, np.array([0., 3., 20., 200.]),
                            np.array([1., 4., 18., 150.]), 100)
        self.assertEqual({row["segment"] for row in rows},
                         {"zero", "low_1_5", "medium_6_to_p95", "high_above_p95"})
        zero = next(row for row in rows if row["segment"] == "zero")
        high = next(row for row in rows if row["segment"] == "high_above_p95")
        self.assertEqual(zero["bias_prediction_minus_actual"], 1.0)
        self.assertIsNone(zero["WAPE"])
        self.assertEqual(high["bias_prediction_minus_actual"], -50.0)
        self.assertTrue(all(np.isfinite(row["MAE"]) and np.isfinite(row["RMSE"]) for row in rows))

    def test_final_fit_uses_all_available_pretest_rows_and_loads(self) -> None:
        rng = np.random.default_rng(7)
        X = rng.uniform(size=(100, 2)).astype(np.float32)
        y = np.where(X[:, 0] > 0.5, 5.0, 0.0)
        winner = {"trial_id": "trial", "model": "lightgbm", "parameters": {
            "objective": "regression_l1", "n_estimators": 5, "num_leaves": 3,
            "min_child_samples": 2, "n_jobs": 1, "verbosity": -1}}
        model, training = fit_final_candidate(winner, X, y, ["recent", "older"], 42)
        self.assertEqual(training["fit_rows"], len(y))
        self.assertEqual(training["sampling_ratio"], 1.0)
        self.assertIsNone(training["sampling_reason"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.joblib"
            joblib.dump(model, path)
            loaded = joblib.load(path)
            predictions = loaded.predict(X)
            self.assertEqual(loaded.feature_names, ["recent", "older"])
            self.assertEqual(len(predictions), len(y))
            self.assertTrue(np.isfinite(predictions).all())
            self.assertTrue((predictions >= 0).all())

    def test_poisson_objective_smoke(self) -> None:
        rng = np.random.default_rng(11)
        X = rng.uniform(size=(100, 2)).astype(np.float32)
        y = np.where(X[:, 0] > 0.5, 4.0, 0.0)
        model, rows = fit_lightgbm(X, y, np.arange(len(y)),
            {"objective": "poisson", "n_estimators": 5, "num_leaves": 3,
             "min_child_samples": 2, "n_jobs": 1, "verbosity": -1}, 100, 42)
        predictions = model.predict(X)
        self.assertEqual(rows, 100)
        self.assertEqual(len(predictions), len(y))
        self.assertTrue(np.isfinite(predictions).all())
        self.assertTrue((predictions >= 0).all())

    def test_comparison_contains_all_three_experiments(self) -> None:
        old = [{"experiment": "Experiment 1", "model": "baseline", "validation_strategy": "single",
                "MAE": 20.0, "MAE_std": "", "RMSE": 40.0, "WAPE": 80.0,
                "MAE_improvement_vs_baseline_percent": 0.0},
               {"experiment": "Experiment 2", "model": "lightgbm_l1", "validation_strategy": "rolling",
                "MAE": 17.0, "MAE_std": 2.0, "RMSE": 38.0, "WAPE": 70.0,
                "MAE_improvement_vs_baseline_percent": 15.0}]
        new = [{"trial_id": "new", "MAE": 16.0, "MAE_std": 2.0, "RMSE": 36.0,
                "WAPE": 68.0, "improvement_vs_baseline_pct": 20.0,
                "objective": "regression_l1", "folds_won_vs_baseline": 4}]
        summary = three_experiment_rows(old, new, "new")
        self.assertEqual({row["experiment"] for row in summary},
                         {"Experiment 1", "Experiment 2", "Experiment 3"})
        self.assertEqual(summary[-1]["decision"], "Final candidate")

    def test_generated_metadata_has_handoff_fields_when_available(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "artifacts" / "training" / "final_candidate_metadata.json"
        if not path.exists():
            self.skipTest("Experiment 3 artifacts have not been generated")
        metadata = json.loads(path.read_text(encoding="utf-8"))
        required = {"experiment_number", "objective", "hyperparameters", "random_seed", "target",
                    "forecast_horizon_days", "feature_order", "fold_date_ranges", "fold_metrics",
                    "aggregate_metrics", "baseline_metrics", "model_artifact_path", "training",
                    "source_splits", "git", "environment", "test_set_used"}
        self.assertFalse(required - metadata.keys())
        self.assertFalse(metadata["test_set_used"])
        self.assertEqual(len(metadata["fold_metrics"]), 4)
        self.assertEqual(len(metadata["feature_order"]), 12)


if __name__ == "__main__":
    unittest.main()
