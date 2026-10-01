"""Prepare /predict records from the same daily panel used for training.

The input must contain every day from each SKU's first sale through the origin,
including explicit zero-sales days. Forecasts run after origin-day sales close.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .features import build_features


def load_feature_contract(config_path: Path, manifest_path: Path) -> tuple[dict, dict]:
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("configuration_sha256") != hashlib.sha256(config_bytes).hexdigest():
        raise ValueError("Feature manifest does not match pipeline.json; use the training configuration")
    if manifest.get("forecast_horizon_days") != config.get("forecast_horizon_days"):
        raise ValueError("Feature manifest and pipeline have different forecast horizons")
    return config, manifest


def prepare_prediction_request(
    history: pd.DataFrame,
    forecast_origin: str,
    config: dict,
    manifest: dict,
    skus: list[str] | None = None,
) -> tuple[dict, list[dict]]:
    """Return ordered API records plus SKU/date keys kept outside model input.

    Future rows and target columns never enter feature engineering. Missing
    days are rejected: guessing zeros could silently alter lag meanings.
    """
    names = manifest.get("feature_columns")
    if (not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not name for name in names)
            or len(names) != len(set(names))):
        raise ValueError("Feature manifest must contain unique feature names")
    if any(name in {"sku_id", "forecast_origin_date", "date", "demand_next_7d_units"} for name in names):
        raise ValueError("Identifiers, dates and target cannot be model features")
    origin = pd.Timestamp(forecast_origin)
    if pd.isna(origin) or origin.tzinfo is not None or origin != origin.normalize():
        raise ValueError("Forecast origin must be a timezone-free calendar date")
    panel = history.copy()
    if "forecast_origin_date" not in panel and "date" in panel:
        panel = panel.rename(columns={"date": "forecast_origin_date"})
    required = ["sku_id", "forecast_origin_date", "daily_sold_units"]
    if any(name not in panel for name in required) or panel.empty:
        raise ValueError("Provide nonempty daily history with sku_id, date and daily_sold_units")
    # Explicitly drop labels and any precomputed features supplied by a caller.
    panel = panel[required].copy()
    if panel["sku_id"].isna().any() or not panel["sku_id"].map(
        lambda value: isinstance(value, str) and bool(value.strip()) and value == value.strip()
    ).all():
        raise ValueError("SKU identifiers must be nonempty strings without surrounding spaces")
    if skus is not None:
        if not skus or len(set(skus)) != len(skus) or set(skus) - set(panel["sku_id"]):
            raise ValueError("Requested SKUs must exist in history and must not be repeated")
        panel = panel.loc[panel["sku_id"].isin(skus)].copy()
    dates = pd.to_datetime(panel["forecast_origin_date"], errors="raise")
    if dates.isna().any() or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
        raise ValueError("History must use timezone-free daily dates")
    panel["forecast_origin_date"] = dates
    selected_skus = set(panel["sku_id"])
    panel = panel.loc[dates.le(origin)].copy()
    if set(panel["sku_id"]) != selected_skus:
        raise ValueError("Every requested SKU needs history through the forecast origin")
    quantities = panel["daily_sold_units"]
    if not pd.api.types.is_numeric_dtype(quantities) or pd.api.types.is_bool_dtype(quantities):
        raise ValueError("Daily sales must be nonnegative integer numbers")
    values = quantities.to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values < 0).any()
            or (values >= np.iinfo(np.int64).max).any() or (values != np.floor(values)).any()):
        raise ValueError("Daily sales must be finite nonnegative integers within int64 range")
    panel["daily_sold_units"] = quantities.astype("int64")
    if panel.duplicated(["sku_id", "forecast_origin_date"]).any():
        raise ValueError("Daily history contains duplicate SKU/date rows")
    panel = panel.sort_values(["sku_id", "forecast_origin_date"]).reset_index(drop=True)
    for sku, group in panel.groupby("sku_id", sort=True):
        actual_dates = pd.DatetimeIndex(group["forecast_origin_date"])
        expected_dates = pd.date_range(actual_dates[0], origin, freq="D")
        if not actual_dates.equals(expected_dates):
            raise ValueError(f"Incomplete daily history for {sku}; include zero-sales days through origin")
        if group["daily_sold_units"].iloc[0] <= 0:
            raise ValueError(f"History for {sku} must start on its first sale date")
    features, _ = build_features(panel, config)
    actual_names = [name for name in features if name not in {"sku_id", "forecast_origin_date"}]
    if actual_names != names:
        raise ValueError("Generated feature names/order do not match the training manifest")
    latest = features.loc[features["forecast_origin_date"].eq(origin)].copy()
    if set(latest["sku_id"]) != selected_skus:
        raise ValueError("Insufficient history for one or more SKUs; the training warmup must be complete")
    if not np.isfinite(latest[names].to_numpy(dtype=np.float32)).all():
        raise ValueError("Generated features are outside the model's finite float32 range")
    keys = [{"sku_id": sku, "forecast_origin_date": origin.date().isoformat()}
            for sku in latest["sku_id"]]
    records = json.loads(latest[names].to_json(orient="records"))
    return {"records": records}, keys
