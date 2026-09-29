"""Focused checks for chronological folds and deployable Experiment 2 models."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LogisticRegression

from src.demand_forecasting.training.experiment2 import (
    FeatureOrderedModel,
    TwoStageDemandModel,
    build_folds,
    fit_forest,
    fit_lightgbm,
    load_pretest,
)
from src.demand_forecasting.training.train import Split, predict_nonnegative


class FoldTests(unittest.TestCase):
    def test_expanding_folds_keep_labels_before_validation(self) -> None:
        dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-03-01"), dtype="datetime64[D]")
        definitions = [
            {"train_label_end": "2020-01-20", "validation_start": "2020-01-21", "validation_end": "2020-01-30"},
            {"train_label_end": "2020-02-10", "validation_start": "2020-02-11", "validation_end": "2020-02-20"},
        ]
        folds = build_folds(dates, 7, definitions)
        self.assertEqual(len(folds), 2)
        for fold in folds:
            self.assertLess(np.max(dates[fold.train_indices]) + np.timedelta64(7, "D"),
                            np.min(dates[fold.validation_indices]))
            self.assertFalse(np.intersect1d(fold.train_indices, fold.validation_indices).size)
        self.assertGreater(len(folds[1].train_indices), len(folds[0].train_indices))

    def test_overlapping_label_window_rejected(self) -> None:
        dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-02-01"), dtype="datetime64[D]")
        with self.assertRaisesRegex(ValueError, "overlap"):
            build_folds(dates, 7, [{"train_label_end": "2020-01-20",
                                    "validation_start": "2020-01-20", "validation_end": "2020-01-28"}])

    def test_pretest_loader_never_opens_test(self) -> None:
        manifest = {"splits": {
            "train": {"path": "train.csv.gz"}, "validation": {"path": "validation.csv.gz"},
            "test": {"first_origin_date": "2020-03-01", "path": "test.csv.gz"}}}
        splits = {
            "train": Split(np.array([[1.0]], dtype=np.float32), np.array([0.0]), "2020-01-01", "2020-01-01"),
            "validation": Split(np.array([[2.0]], dtype=np.float32), np.array([1.0]), "2020-02-01", "2020-02-01"),
        }
        with (patch("src.demand_forecasting.training.experiment2.load_split", side_effect=lambda name, *_: splits[name]) as loader,
              patch("src.demand_forecasting.training.experiment2.pd.read_csv",
                    side_effect=[pd.DataFrame({"forecast_origin_date": ["2020-01-01"]}),
                                 pd.DataFrame({"forecast_origin_date": ["2020-02-01"]})]),
              patch("src.demand_forecasting.training.experiment2.sha256", return_value="mock")):
            X, y, dates, _ = load_pretest(manifest, ["feature"], "target")
        self.assertEqual([call.args[0] for call in loader.call_args_list], ["train", "validation"])
        self.assertEqual((X.shape, len(y), len(dates)), ((2, 1), 2, 2))


class ModelTests(unittest.TestCase):
    def test_two_stage_zero_positive_and_saved_model(self) -> None:
        X = np.array([[0.0], [1.0], [2.0], [3.0]], dtype=np.float32)
        classifier = LogisticRegression().fit(X, [0, 0, 1, 1])
        regressor = DummyRegressor(strategy="constant", constant=4.0).fit(X[2:], [3.0, 5.0])
        model = TwoStageDemandModel(classifier, regressor, 0.5)
        expected = np.array([0.0, 0.0, 4.0, 4.0])
        np.testing.assert_array_equal(predict_nonnegative(model, X), expected)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.joblib"
            joblib.dump(model, path)
            loaded = joblib.load(path)
            np.testing.assert_array_equal(predict_nonnegative(loaded, X), expected)
        all_zero = TwoStageDemandModel(classifier, regressor, 0.9999)
        np.testing.assert_array_equal(predict_nonnegative(all_zero, X), np.zeros(4))

    def test_tree_fits_predict_finite_nonnegative_values(self) -> None:
        rng = np.random.default_rng(3)
        X = rng.uniform(size=(80, 2)).astype(np.float32)
        y = np.where(X[:, 0] > 0.5, X[:, 0] * 10, 0.0)
        rows = np.arange(len(y))
        forest, _ = fit_forest(X, y, rows,
                               {"n_estimators": 5, "max_depth": 3, "min_samples_leaf": 2, "n_jobs": 1}, 80, 42)
        boosted, _ = fit_lightgbm(X, y, rows,
                                  {"objective": "regression_l1", "n_estimators": 5, "min_child_samples": 2,
                                   "n_jobs": 1, "verbosity": -1}, 80, 42)
        for model in (forest, boosted):
            predicted = predict_nonnegative(model, X)
            self.assertEqual(len(predicted), len(y))
            self.assertTrue(np.isfinite(predicted).all())
            self.assertTrue((predicted >= 0).all())

    def test_saved_candidate_preserves_feature_order(self) -> None:
        X = pd.DataFrame({"older_sales": [1.0, 2.0], "recent_sales": [3.0, 4.0]})
        regressor = DummyRegressor(strategy="constant", constant=-2.0).fit(X, [0.0, 0.0])
        model = FeatureOrderedModel(regressor, list(X.columns))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ordered.joblib"
            joblib.dump(model, path)
            loaded = joblib.load(path)
            self.assertEqual(loaded.feature_names, ["older_sales", "recent_sales"])
            np.testing.assert_array_equal(loaded.predict(X), np.zeros(2))
            with self.assertRaisesRegex(ValueError, "order"):
                loaded.predict(X[["recent_sales", "older_sales"]])


if __name__ == "__main__":
    unittest.main()
