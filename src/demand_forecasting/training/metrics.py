"""Metrics for nonnegative demand forecasts."""

from __future__ import annotations

import numpy as np


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    """Return MAE, RMSE, and WAPE (percent) for equally sized finite arrays.

    WAPE is undefined when total actual demand is zero and errors are nonzero.
    A perfect all-zero forecast has WAPE 0.
    """
    actual = np.asarray(y_true, dtype=np.float64).reshape(-1)
    predicted = np.asarray(y_pred, dtype=np.float64).reshape(-1)
    if actual.size == 0 or actual.shape != predicted.shape:
        raise ValueError("Actual and predicted values must have the same nonzero length")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require finite actual and predicted values")
    if (actual < 0).any():
        raise ValueError("Actual demand cannot be negative")

    errors = np.abs(actual - predicted)
    absolute_error = float(np.mean(errors))
    rmse = float(np.sqrt(np.mean(np.square(actual - predicted))))
    denominator = float(np.sum(np.abs(actual)))
    wape = 100.0 * float(np.sum(errors)) / denominator if denominator else (
        0.0 if not np.any(errors) else None
    )
    return {"MAE": absolute_error, "RMSE": rmse, "WAPE": wape}
