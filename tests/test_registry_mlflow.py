"""Exercise the local MLflow registry with a small, real model."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from src.demand_forecasting.registry import log_trials, promote, register_candidate, rollback
from src.demand_forecasting.training.models import FeatureOrderedModel
from tests.test_registry import evidence


@unittest.skipUnless(importlib.util.find_spec("mlflow"), "mlflow is not installed")
class MlflowRegistryTests(unittest.TestCase):
    def test_register_promote_load_and_rollback(self):
        import mlflow

        # MLflow keeps SQLite connections open until interpreter exit on Windows.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            model_path = root / "candidate.joblib"
            metadata_path = root / "metadata.json"
            fold_path = root / "folds.json"
            policy_path = root / "policy.json"
            frame = pd.DataFrame([[0.0, 0.0], [1.0, 1.0]], columns=["lag", "weekday"])
            estimator = DummyRegressor(strategy="constant", constant=1.0).fit(frame, [1.0, 1.0])
            joblib.dump(FeatureOrderedModel(estimator, list(frame.columns)), model_path)
            metadata, folds, _ = evidence()
            metadata.update({"hyperparameters": {"strategy": "constant"}})
            policy = {"experiment_name": "registry-test", "registered_model_name": "registry-test",
                      "expected_folds": 4, "minimum_fold_wins": 3,
                      "maximum_champion_mae_regression_pct": 0.0,
                      "maximum_latency_p50_ms": 200, "maximum_latency_p95_ms": 500,
                      "minimum_throughput_predictions_per_second": 100,
                      "benchmark_batch_size": 32, "benchmark_measured_requests": 30,
                      "benchmark_concurrency": 4,
                      "maximum_benchmark_age_hours": 24}
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            fold_path.write_text(json.dumps(folds), encoding="utf-8")
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            (root / "tuning_results.csv").write_text(
                'model,MAE,RMSE,WAPE,train_rows,hyperparameters\n'
                'ridge,18.0,25.0,50.0,100,"{""alpha"": 1.0}"\n', encoding="utf-8")
            for number in (2, 3):
                trial = {"trial_id": f"trial_{number}", "model": "lightgbm",
                         "parameters": {"n_estimators": 10}, "MAE": 18.0,
                         "RMSE": 25.0, "WAPE": 50.0}
                trial_folds = [{"trial_id": trial["trial_id"], "fold": f"fold_{i}",
                                "MAE": value, "RMSE": value + 2, "WAPE": 50.0}
                               for i, value in enumerate([15.0, 16.0, 17.0, 24.0])]
                (root / f"experiment{number}_trials.json").write_text(json.dumps([trial]), encoding="utf-8")
                (root / f"experiment{number}_fold_metrics.json").write_text(json.dumps(trial_folds), encoding="utf-8")
            uri = "sqlite:///" + (root / "mlflow.db").as_posix()
            with patch.dict(os.environ, {"MLFLOW_TRACKING_URI": uri}), patch(
                "src.demand_forecasting.registry.MODEL_PATH", model_path
            ), patch("src.demand_forecasting.registry.METADATA_PATH", metadata_path), patch(
                "src.demand_forecasting.registry.FOLD_PATH", fold_path
            ), patch("src.demand_forecasting.registry.POLICY_PATH", policy_path), patch(
                "src.demand_forecasting.registry.OUTPUT_DIR", root
            ):
                log_trials()
                experiment = mlflow.get_experiment_by_name("registry-test")
                self.assertEqual(len(mlflow.search_runs([experiment.experiment_id])), 3)
                self.assertEqual(register_candidate(), 0)
                client = mlflow.MlflowClient()
                versions = client.search_model_versions("name='registry-test'")
                self.assertEqual(len(versions), 1)
                version = versions[0].version
                for key, value in {"serving_gate_passed": "true", "latency_p50_ms": "20",
                                   "latency_p95_ms": "40", "throughput_predictions_per_second": "1000",
                                   "benchmark_batch_size": "32", "benchmark_measured_requests": "30",
                                   "benchmark_concurrency": "4",
                                   "benchmark_url": "http://localhost:5001", "benchmark_run_id": "test",
                                   "benchmark_at_utc": datetime.now(timezone.utc).isoformat()}.items():
                    client.set_model_version_tag("registry-test", version, key, value)
                promote(version)
                loaded = mlflow.pyfunc.load_model("models:/registry-test@production")
                np.testing.assert_allclose(loaded.predict(frame), [1.0, 1.0])
                with self.assertRaisesRegex(ValueError, "Rollback requires"):
                    rollback()


if __name__ == "__main__":
    unittest.main()
