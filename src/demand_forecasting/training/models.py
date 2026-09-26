"""Persistable model wrappers used by Sira's Experiment 2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .train import predict_nonnegative


class TwoStageDemandModel:
    """Predict zero below a fixed validation-selected occurrence threshold."""

    def __init__(self, classifier: object, regressor: object, threshold: float):
        self.classifier = classifier
        self.regressor = regressor
        self.threshold = float(threshold)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("Occurrence threshold must be between zero and one")
        probability = self.classifier.predict_proba(X)[:, 1]
        if len(probability) != len(X) or not np.isfinite(probability).all():
            raise ValueError("Classifier returned invalid probabilities")
        predictions = np.zeros(len(X), dtype=np.float64)
        positive = probability >= self.threshold
        if positive.any():
            predictions[positive] = predict_nonnegative(self.regressor, X[positive])
        return predictions


class FeatureOrderedModel:
    """Saved candidate with an explicit feature schema and nonnegative output."""

    def __init__(self, model: object, feature_names: list[str]):
        self.model = model
        self.feature_names = list(feature_names)

    def predict(self, X: np.ndarray | pd.DataFrame) -> np.ndarray:
        if isinstance(X, pd.DataFrame):
            if list(X.columns) != self.feature_names:
                raise ValueError("Prediction feature order does not match training")
            values = X.to_numpy(dtype=np.float32)
        else:
            values = np.asarray(X, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names):
            raise ValueError("Prediction feature count does not match training")
        return predict_nonnegative(self.model, values)
