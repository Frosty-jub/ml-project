"""Behavioral checks for the quality gate and alias transitions."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.demand_forecasting.registry import evaluate_gate, promote, rollback


class OrderedModel:
    feature_names = ["lag", "weekday"]

    def predict(self, frame):
        if list(frame.columns) != self.feature_names:
            raise ValueError("wrong feature order")
        return np.array([1.0] * len(frame))


def evidence(candidate_mae=18.0):
    baseline = [20.0, 21.0, 22.0, 23.0]
    candidate = [15.0, 16.0, 17.0, 24.0]
    folds = ([{"trial_id": "historical_7d_sum", "fold": f"fold_{i}", "MAE": value}
              for i, value in enumerate(baseline)]
             + [{"trial_id": "candidate", "fold": f"fold_{i}", "MAE": value}
                for i, value in enumerate(candidate)])
    metadata = {
        "feature_order": ["lag", "weekday"], "model_name": "candidate", "test_set_used": False,
        "fold_date_ranges": [{"fold": f"fold_{i}"} for i in range(4)],
        "aggregate_metrics": {"MAE": candidate_mae, "RMSE": 25.0, "WAPE": 50.0,
                              "folds_won_vs_baseline": 3},
        "baseline_metrics": {"MAE": 21.5, "RMSE": 30.0, "WAPE": 60.0},
    }
    policy = {"expected_folds": 4, "minimum_fold_wins": 3}
    return metadata, folds, policy


class FakeClient:
    def __init__(self):
        self.aliases = {"champion": "1"}
        benchmark = {
            "serving_gate_passed": "true", "latency_p50_ms": "20", "latency_p95_ms": "40",
            "throughput_predictions_per_second": "1000", "benchmark_batch_size": "32",
            "benchmark_concurrency": "4",
            "benchmark_measured_requests": "30", "benchmark_url": "http://localhost:5001",
            "benchmark_run_id": "run", "benchmark_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.tags = {
            "1": {**benchmark, "gate_passed": "true", "validation_mae": "18.0", "validation_folds_sha256": "same"},
            "2": {**benchmark, "gate_passed": "true", "validation_mae": "17.5", "validation_folds_sha256": "same"},
            "3": {**benchmark, "gate_passed": "false", "validation_mae": "17.0"},
        }

    def get_registered_model(self, name):
        return SimpleNamespace(aliases=self.aliases.copy())

    def get_model_version(self, name, version):
        return SimpleNamespace(tags=self.tags[version], version=version)

    def set_registered_model_alias(self, name, alias, version):
        self.aliases[alias] = str(version)


class RegistryTests(unittest.TestCase):
    def test_gate_checks_actual_fold_metrics_and_model_output(self):
        metadata, folds, policy = evidence()
        result = evaluate_gate(metadata, folds, OrderedModel(), policy)
        self.assertTrue(result["passed"])
        self.assertEqual(result["folds_won"], 3)
        import json
        json.dumps(result)

        metadata["aggregate_metrics"]["MAE"] = 17.0
        self.assertFalse(evaluate_gate(metadata, folds, OrderedModel(), policy)["checks"]["aggregate_matches_folds"])
        metadata["aggregate_metrics"]["MAE"] = 18.0
        folds[-2]["MAE"] = 23.0
        self.assertFalse(evaluate_gate(metadata, folds, OrderedModel(), policy)["checks"]["wins_required_folds"])

    def test_promote_requires_gate_and_supports_rollback(self):
        client = FakeClient()
        mlflow = SimpleNamespace(MlflowClient=lambda: client)
        policy = {"registered_model_name": "forecast", "maximum_champion_mae_regression_pct": 0.0,
                  "maximum_latency_p50_ms": 200, "maximum_latency_p95_ms": 500,
                  "minimum_throughput_predictions_per_second": 100,
                  "benchmark_batch_size": 32, "benchmark_measured_requests": 30,
                  "benchmark_concurrency": 4,
                  "maximum_benchmark_age_hours": 24}
        with patch("src.demand_forecasting.registry.configure_mlflow", return_value=mlflow), patch(
            "src.demand_forecasting.registry.read_json", return_value=policy
        ):
            with self.assertRaisesRegex(ValueError, "validation and serving gates"):
                promote("3")
            client.tags["2"]["latency_p95_ms"] = "600"
            with self.assertRaisesRegex(ValueError, "serving thresholds"):
                promote("2")
            client.tags["2"]["latency_p95_ms"] = "40"
            client.tags["2"]["throughput_predictions_per_second"] = "50"
            with self.assertRaisesRegex(ValueError, "serving thresholds"):
                promote("2")
            client.tags["2"]["throughput_predictions_per_second"] = "1000"
            client.tags["2"]["validation_folds_sha256"] = "different"
            with self.assertRaisesRegex(ValueError, "different validation folds"):
                promote("2")
            client.tags["2"]["validation_folds_sha256"] = "same"
            client.tags["2"]["validation_mae"] = "19.0"
            with self.assertRaisesRegex(ValueError, "champion limit"):
                promote("2")
            client.tags["2"]["validation_mae"] = "17.5"
            promote("2")
            self.assertEqual(client.aliases, {"production": "2", "champion": "2", "previous": "1"})
            rollback()
            self.assertEqual(client.aliases, {"production": "1", "champion": "1", "previous": "2"})


if __name__ == "__main__":
    unittest.main()
