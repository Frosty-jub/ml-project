"""Historical feature engineering shared by training and serving preparation."""

from __future__ import annotations

import pandas as pd


def build_features(panel: pd.DataFrame, config: dict[str, object]) -> tuple[pd.DataFrame, int]:
    feature_config = config["features"]
    lags = [int(value) for value in feature_config["sales_lags_days"]]
    windows = [int(value) for value in feature_config["sales_rolling_windows_days"]]
    minimum_previous_days = int(feature_config["minimum_previous_days"])
    if min(lags + windows + [minimum_previous_days]) <= 0 or minimum_previous_days < max(lags):
        raise ValueError("ค่าระยะย้อนหลังใน config/pipeline.json ไม่ถูกต้อง")

    panel = panel.sort_values(["sku_id", "forecast_origin_date"], kind="stable").reset_index(drop=True)
    sales_by_sku = panel.groupby("sku_id", sort=False)["daily_sold_units"]
    panel["days_since_first_sale"] = panel.groupby("sku_id", sort=False).cumcount()
    for lag in lags:
        panel[f"sales_lag_{lag}"] = sales_by_sku.shift(lag)
    for window in windows:
        panel[f"sales_rolling_sum_{window}"] = sales_by_sku.transform(
            lambda values, window=window: values.rolling(window, min_periods=window).sum()
        )

    panel["day_of_week"] = panel["forecast_origin_date"].dt.dayofweek.astype("int8")
    panel["month"] = panel["forecast_origin_date"].dt.month.astype("int8")
    panel["is_weekend"] = panel["day_of_week"].ge(5).astype("int8")
    warmup = panel["days_since_first_sale"].lt(minimum_previous_days)
    omitted_warmup = int(warmup.sum())
    panel = panel.loc[~warmup].copy()
    feature_columns = [f"sales_lag_{lag}" for lag in lags] + [
        f"sales_rolling_sum_{window}" for window in windows
    ]
    if panel[feature_columns].isna().any().any():
        raise ValueError("feature ย้อนหลังมีค่าว่างหลังตัดช่วงประวัติไม่ครบ")
    for column in feature_columns:
        panel[column] = panel[column].astype("int64")
    return panel, omitted_warmup
