"""Build leakage-safe historical features and chronological train/validation/test files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "pipeline.json"
LABEL_PATH = ROOT / "data" / "processed" / "sku_daily_demand_7d.csv.gz"
OUTPUT_DIR = ROOT / "data" / "processed"
MANIFEST_PATH = ROOT / "reports" / "generated" / "feature_split_manifest.json"


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
            lambda values: values.rolling(window, min_periods=window).sum()
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


def split_by_time(
    features: pd.DataFrame, config: dict[str, object]
) -> tuple[dict[str, pd.DataFrame], int]:
    settings = config["splits"]
    horizon = pd.Timedelta(days=int(config["forecast_horizon_days"]))
    train_label_end = pd.Timestamp(settings["train_label_end"])
    validation_start = pd.Timestamp(settings["validation_start"])
    validation_label_end = pd.Timestamp(settings["validation_label_end"])
    test_start = pd.Timestamp(settings["test_start"])
    if not train_label_end < validation_start <= validation_label_end < test_start:
        raise ValueError("ช่วง train/validation/test ใน config ไม่เรียงตามเวลา")

    origin = features["forecast_origin_date"]
    label_end = origin + horizon
    masks = {
        "train": label_end.le(train_label_end),
        "validation": origin.ge(validation_start) & label_end.le(validation_label_end),
        "test": origin.ge(test_start),
    }
    assigned = masks["train"] | masks["validation"] | masks["test"]
    splits = {name: features.loc[mask].copy() for name, mask in masks.items()}
    if any(frame.empty for frame in splits.values()):
        raise ValueError("อย่างน้อยหนึ่งชุดข้อมูล train/validation/test ว่าง")
    if splits["train"]["forecast_origin_date"].max() >= splits["validation"]["forecast_origin_date"].min():
        raise ValueError("train และ validation มีวันที่ทับกัน")
    if splits["validation"]["forecast_origin_date"].max() >= splits["test"]["forecast_origin_date"].min():
        raise ValueError("validation และ test มีวันที่ทับกัน")
    return splits, int((~assigned).sum())


def main() -> None:
    if not LABEL_PATH.exists():
        raise FileNotFoundError(f"ไม่พบ {LABEL_PATH}; ให้เตรียมและตรวจข้อมูลก่อน")
    validation_path = ROOT / "reports" / "generated" / "validation_summary.json"
    if not validation_path.exists():
        raise FileNotFoundError("ยังไม่มีรายงาน Data Validation; ให้รัน scripts/validate_data.py ก่อน")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(LABEL_PATH.read_bytes()).hexdigest()
    config_digest = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
    if (
        validation.get("status") != "passed"
        or validation.get("labels_sha256") != digest
        or validation.get("configuration_sha256") != config_digest
    ):
        raise ValueError("Data Validation ไม่ตรงกับไฟล์ข้อมูลหรือ config ล่าสุด; ให้รัน validate_data.py ใหม่")
    panel = pd.read_csv(
        LABEL_PATH,
        compression="gzip",
        dtype={"sku_id": "string"},
        parse_dates=["forecast_origin_date"],
    )
    features, omitted_warmup = build_features(panel, config)
    splits, omitted_boundary = split_by_time(features, config)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "source_labeled_rows": len(panel),
        "omitted_warmup_rows": omitted_warmup,
        "omitted_split_boundary_rows": omitted_boundary,
        "forecast_horizon_days": int(config["forecast_horizon_days"]),
        "configuration_sha256": config_digest,
        "source_labels_sha256": digest,
        "feature_columns": [
            column
            for column in features.columns
            if column not in {"sku_id", "forecast_origin_date", "demand_next_7d_units"}
        ],
        "splits": {},
    }
    for name, frame in splits.items():
        frame["forecast_origin_date"] = frame["forecast_origin_date"].dt.strftime("%Y-%m-%d")
        path = OUTPUT_DIR / f"{name}_features_7d.csv.gz"
        frame.to_csv(path, index=False, compression="gzip")
        summary["splits"][name] = {
            "rows": len(frame),
            "skus": int(frame["sku_id"].nunique()),
            "first_origin_date": frame["forecast_origin_date"].min(),
            "last_origin_date": frame["forecast_origin_date"].max(),
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("สร้าง features และ time split สำเร็จ")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
