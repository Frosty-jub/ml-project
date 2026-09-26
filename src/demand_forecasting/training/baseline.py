"""Persistable historical demand baseline."""

from __future__ import annotations

import numpy as np


class HistoricalSumBaseline:
    """Predict the next horizon total with the previous horizon total."""

    def __init__(self, feature_index: int) -> None:
        self.feature_index = feature_index

    def fit(self, X: np.ndarray, y: np.ndarray) -> HistoricalSumBaseline:
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X[:, self.feature_index], dtype=np.float64)
