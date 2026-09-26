from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.demand_forecasting.training.metrics import evaluate
from src.demand_forecasting.training.train import (
    Split,
    main,
    predict_nonnegative,
    target_from_dataset_config,
    train_and_select,
)


class MetricTests(unittest.TestCase):
    def test_known_metrics(self) -> None:
        result = evaluate(np.array([1, 3]), np.array([2, 1]))
        self.assertAlmostEqual(result["MAE"], 1.5)
        self.assertAlmostEqual(result["RMSE"], np.sqrt(2.5))
        self.assertAlmostEqual(result["WAPE"], 75.0)

    def test_zero_denominator(self) -> None:
        self.assertEqual(evaluate([0, 0], [0, 0])["WAPE"], 0.0)
        self.assertIsNone(evaluate([0, 0], [1, 0])["WAPE"])

    def test_invalid_arrays(self) -> None:
        with self.assertRaises(ValueError):
            evaluate([1], [float("nan")])
        with self.assertRaises(ValueError):
            evaluate([1, 2], [1])


class TrainingTests(unittest.TestCase):
    def test_target_comes_from_project_config(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "dataset.yaml"
        self.assertEqual(target_from_dataset_config(path), "demand_next_7d_units")

    def test_candidates_fit_predict_and_select_on_validation(self) -> None:
        rng = np.random.default_rng(4)
        X_train = rng.uniform(0, 10, size=(80, 2)).astype(np.float32)
        X_validation = rng.uniform(0, 10, size=(20, 2)).astype(np.float32)
        y_train = X_train[:, 0].astype(float) * 1.2
        y_validation = X_validation[:, 0].astype(float) * 1.2
        train = Split(X_train, y_train, "2020-01-01", "2020-03-20")
        validation = Split(X_validation, y_validation, "2020-04-01", "2020-04-20")
        settings = {
            "random_seed": 7,
            "max_random_forest_train_rows": 50,
            "max_hist_gradient_boosting_train_rows": 50,
            "ridge_alphas": [1.0, 10.0],
            "random_forest": {"n_estimators": 5, "max_depth": 3, "min_samples_leaf": 2, "n_jobs": 1},
            "hist_gradient_boosting": {"max_iter": 5, "learning_rate": 0.1, "max_leaf_nodes_options": [3, 5], "min_samples_leaf": 2},
        }
        model, winner, comparison, trials = train_and_select(
            train, validation, ["sales_rolling_sum_7", "other_past_feature"], 7, settings
        )
        self.assertEqual({row["model"] for row in comparison}, {
            "historical_7d_sum", "ridge", "random_forest", "hist_gradient_boosting"
        })
        self.assertEqual(len(trials), 6)
        self.assertEqual(winner["MAE"], min(row["MAE"] for row in comparison))
        predictions = predict_nonnegative(model, validation.X)
        self.assertEqual(len(predictions), len(validation.y))
        self.assertTrue(np.isfinite(predictions).all())
        self.assertTrue(all(np.isfinite(row["MAE"]) and np.isfinite(row["RMSE"]) for row in trials))
        self.assertTrue(all(np.isfinite(row["WAPE"]) for row in trials))

    def test_overlapping_dates_rejected_before_tuning(self) -> None:
        split = Split(np.ones((2, 1)), np.ones(2), "2020-01-01", "2020-01-02")
        with self.assertRaisesRegex(ValueError, "overlap"):
            train_and_select(split, split, ["sales_rolling_sum_7"], 7, {})

    def test_test_set_is_loaded_after_model_selection(self) -> None:
        events: list[str] = []
        splits = {
            "train": Split(np.ones((2, 1)), np.ones(2), "2020-01-01", "2020-01-02"),
            "validation": Split(np.ones((2, 1)), np.ones(2), "2020-02-01", "2020-02-02"),
            "test": Split(np.ones((2, 1)), np.ones(2), "2020-03-01", "2020-03-02"),
        }

        class Model:
            def predict(self, X: np.ndarray) -> np.ndarray:
                return np.ones(len(X))

        winner = {"model": "mock", "hyperparameters": {}, "train_rows": 2, "MAE": 0.0, "RMSE": 0.0, "WAPE": 0.0}

        def load(name: str, *_args: object) -> Split:
            events.append(f"load_{name}")
            return splits[name]

        def select(*_args: object) -> tuple[object, dict, list[dict], list[dict]]:
            events.append("select")
            self.assertNotIn("load_test", events)
            return Model(), winner, [winner], [winner]

        with (
            patch("src.demand_forecasting.training.train.target_from_dataset_config", return_value="target"),
            patch("src.demand_forecasting.training.train.load_manifest", return_value=({}, ["sales_rolling_sum_7"], 7)),
            patch("src.demand_forecasting.training.train.load_split", side_effect=load),
            patch("src.demand_forecasting.training.train.train_and_select", side_effect=select),
            patch("src.demand_forecasting.training.train.save_artifacts"),
            patch("src.demand_forecasting.training.train.MANIFEST_PATH", Path(__file__)),
        ):
            main()
        self.assertEqual(events, ["load_train", "load_validation", "select", "load_test"])


if __name__ == "__main__":
    unittest.main()
