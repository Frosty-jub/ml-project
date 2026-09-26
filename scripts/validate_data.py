"""Validate the daily sales series and every seven-day training label."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DAILY_PATH = ROOT / "data" / "interim" / "sku_daily_sales.csv.gz"
LABEL_PATH = ROOT / "data" / "processed" / "sku_daily_demand_7d.csv.gz"
CONFIG_PATH = ROOT / "config" / "pipeline.json"
REPORT_PATH = ROOT / "reports" / "generated" / "validation_summary.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Data Validation ไม่ผ่าน: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_table(path: Path, date_column: str, required: set[str]) -> pd.DataFrame:
    require(path.exists(), f"ไม่พบไฟล์ {path}")
    frame = pd.read_csv(path, compression="gzip", dtype={"sku_id": "string"})
    require(required.issubset(frame.columns), f"{path.name} ขาดคอลัมน์ {sorted(required - set(frame.columns))}")
    require(not frame[list(required)].isna().any().any(), f"{path.name} มีค่าว่างในคอลัมน์หลัก")
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    require(frame[date_column].notna().all(), f"{path.name} มีวันที่อ่านไม่ได้")
    require(frame["sku_id"].str.strip().ne("").all(), f"{path.name} มี SKU ว่าง")
    for column in required - {"sku_id", date_column}:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        require(frame[column].notna().all(), f"{path.name}: {column} มีค่าที่ไม่ใช่ตัวเลข")
        require(frame[column].ge(0).all(), f"{path.name}: {column} มีค่าติดลบ")
        require(frame[column].mod(1).eq(0).all(), f"{path.name}: {column} ต้องเป็นจำนวนเต็ม")
        frame[column] = frame[column].astype("int64")
    require(
        not frame.duplicated(["sku_id", date_column]).any(),
        f"{path.name} มีคู่ SKU-วันซ้ำ",
    )
    return frame.sort_values(["sku_id", date_column], kind="stable").reset_index(drop=True)


def validate(daily: pd.DataFrame, labels: pd.DataFrame, horizon_days: int) -> dict[str, object]:
    require(not daily.empty and not labels.empty, "ตารางรายวันหรือ label ว่าง")
    require(horizon_days > 0, "forecast horizon ต้องมากกว่า 0")
    last_observed = daily["date"].max()
    last_origin = last_observed - pd.Timedelta(days=horizon_days)
    gap = daily.groupby("sku_id", sort=False)["date"].diff()
    require(gap.dropna().eq(pd.Timedelta(days=1)).all(), "วันที่ในแต่ละ SKU ไม่ต่อเนื่องกัน")
    require(
        daily.groupby("sku_id", sort=False)["date"].max().eq(last_observed).all(),
        "บาง SKU ไม่ถูกเติมวันถึงวันสุดท้ายของชุดข้อมูล",
    )
    require(labels["forecast_origin_date"].max() == last_origin, "วัน origin สุดท้ายไม่ตรง horizon")
    require(labels["forecast_origin_date"].le(last_origin).all(), "มี label ที่อนาคตไม่ครบ")

    # Independent check: cumulative sales through t+7 minus cumulative sales through t.
    cumulative = daily.groupby("sku_id", sort=False)["daily_sold_units"].cumsum()
    expected_target = cumulative.groupby(daily["sku_id"], sort=False).shift(-horizon_days) - cumulative
    expected = daily.loc[daily["date"].le(last_origin)].copy()
    expected["expected_target"] = expected_target.loc[expected.index].to_numpy()
    expected = expected.reset_index(drop=True)
    require(len(expected) == len(labels), "จำนวน label ไม่เท่าจำนวน origin ที่ควรมี")
    require(expected["sku_id"].equals(labels["sku_id"]), "ชุด SKU ของ label ไม่ตรงข้อมูลรายวัน")
    require(
        expected["date"].equals(labels["forecast_origin_date"]),
        "วัน origin ของ label ไม่ตรงข้อมูลรายวัน",
    )
    require(
        expected["daily_sold_units"].equals(labels["daily_sold_units"]),
        "ยอดขายรายวันที่ใส่ใน label ไม่ตรงข้อมูลรายวัน",
    )
    require(expected["expected_target"].notna().all(), "มีช่วงอนาคตที่ข้อมูลไม่ครบเจ็ดวัน")
    wrong_target = expected["expected_target"].ne(labels["demand_next_7d_units"])
    require(not wrong_target.any(), f"target 7 วันคำนวณผิด {int(wrong_target.sum()):,} แถว")

    return {
        "status": "passed",
        "horizon_days": horizon_days,
        "full_daily_rows": len(daily),
        "labeled_rows": len(labels),
        "full_daily_skus": int(daily["sku_id"].nunique()),
        "labeled_skus": int(labels["sku_id"].nunique()),
        "first_date": daily["date"].min().date().isoformat(),
        "last_observed_date": last_observed.date().isoformat(),
        "last_origin_date": last_origin.date().isoformat(),
        "duplicate_keys": 0,
        "missing_required_values": 0,
        "negative_or_fractional_units": 0,
        "incorrect_targets": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", type=Path, default=DAILY_PATH)
    parser.add_argument("--labels", type=Path, default=LABEL_PATH)
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    daily = load_table(args.daily, "date", {"sku_id", "date", "daily_sold_units"})
    labels = load_table(
        args.labels,
        "forecast_origin_date",
        {"sku_id", "forecast_origin_date", "daily_sold_units", "demand_next_7d_units"},
    )
    summary = validate(daily, labels, int(config["forecast_horizon_days"]))
    summary["daily_sha256"] = sha256(args.daily)
    summary["labels_sha256"] = sha256(args.labels)
    summary["configuration_sha256"] = sha256(CONFIG_PATH)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Data Validation ผ่าน")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
