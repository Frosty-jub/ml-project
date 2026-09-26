"""Create a daily SKU panel and seven-day-ahead demand target."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "data" / "raw" / "online_retail_II.xlsx"
OUTPUT_PATH = ROOT / "data" / "processed" / "sku_daily_demand_7d.csv.gz"
DAILY_PATH = ROOT / "data" / "interim" / "sku_daily_sales.csv.gz"
CONFIG_PATH = ROOT / "config" / "pipeline.json"

HEADER_ALIASES = {
    "invoice": "invoice_id",
    "invoiceno": "invoice_id",
    "stockcode": "sku_id",
    "quantity": "quantity",
    "invoicedate": "invoice_datetime",
    "price": "unit_price",
    "unitprice": "unit_price",
}
REQUIRED_COLUMNS = {"invoice_id", "sku_id", "quantity", "invoice_datetime"}


def canonical_header(name: object) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(name).lower())
    return HEADER_ALIASES.get(key, str(name).strip())


def normalize_sku(values: pd.Series) -> pd.Series:
    result = values.astype("string").str.strip()
    # Excel can represent numeric-looking item codes as floats.
    result = result.str.replace(r"^(\d+)\.0$", r"\1", regex=True)
    return result.mask(result.eq(""))


def load_source(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"ไม่พบ {path}. ให้รัน `python scripts/download_data.py` ก่อน"
        )

    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    if not sheets:
        raise ValueError("ไม่พบ worksheet ในไฟล์ต้นฉบับ")

    frames = []
    for sheet_name, frame in sheets.items():
        frame = frame.rename(columns={column: canonical_header(column) for column in frame.columns})
        missing = REQUIRED_COLUMNS.difference(frame.columns)
        if missing:
            raise ValueError(
                f"sheet {sheet_name!r} ขาดคอลัมน์ที่ต้องใช้: {', '.join(sorted(missing))}"
            )
        frames.append(frame.assign(source_sheet=sheet_name))

    return pd.concat(frames, ignore_index=True)


def build_daily_panel(
    source: pd.DataFrame, policy: dict[str, object], horizon_days: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    required_policy = {
        "exclude_cancelled_invoices": True,
        "exclude_non_positive_quantity": True,
        "keep_exact_duplicate_rows": True,
        "fill_missing_sku_days_with_zero": True,
    }
    if any(policy.get(name) is not expected for name, expected in required_policy.items()):
        raise ValueError("config/pipeline.json มีนโยบายที่ prepare_data.py ยังไม่รองรับ")
    if horizon_days <= 0:
        raise ValueError("forecast_horizon_days ต้องมากกว่า 0")
    row_count_source = len(source)
    frame = source[["invoice_id", "sku_id", "quantity", "invoice_datetime"]].copy()
    frame["invoice_id"] = frame["invoice_id"].astype("string").str.strip()
    frame["sku_id"] = normalize_sku(frame["sku_id"])
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
    frame["invoice_datetime"] = pd.to_datetime(frame["invoice_datetime"], errors="coerce")

    required = ["invoice_id", "sku_id", "quantity", "invoice_datetime"]
    invalid_counts = {column: int(frame[column].isna().sum()) for column in required}
    if any(invalid_counts.values()):
        raise ValueError(f"คอลัมน์หลักมีค่าว่างหรือแปลงชนิดไม่ได้: {invalid_counts}")
    if frame["quantity"].mod(1).ne(0).any():
        raise ValueError("Quantity ต้องเป็นจำนวนเต็ม")

    usable = frame
    cancelled = usable["invoice_id"].str.upper().str.startswith("C", na=False)
    positive_sales = usable.loc[~cancelled & usable["quantity"].gt(0)].copy()
    excluded_codes = set(policy["excluded_stock_codes"])
    non_product = positive_sales["sku_id"].str.upper().isin(excluded_codes)
    excluded_non_product_rows = int(non_product.sum())
    positive_sales = positive_sales.loc[~non_product].copy()
    positive_sales["date"] = positive_sales["invoice_datetime"].dt.normalize()

    if positive_sales.empty:
        raise ValueError("ไม่พบแถวขายที่ใช้สร้าง demand series ได้")

    daily = (
        positive_sales.groupby(["sku_id", "date"], as_index=False, sort=True)["quantity"]
        .sum()
        .rename(columns={"quantity": "daily_sold_units"})
    )
    daily["daily_sold_units"] = daily["daily_sold_units"].round().astype("int64")

    last_observed_date = daily["date"].max()
    last_origin_date = last_observed_date - pd.Timedelta(days=horizon_days)
    if last_origin_date < daily["date"].min():
        raise ValueError("ช่วงข้อมูลสั้นกว่า forecast horizon ที่กำหนด")

    rows = []
    daily_rows = []
    for sku_id, sku_sales in daily.groupby("sku_id", sort=True):
        first_sale_date = sku_sales["date"].min()
        full_dates = pd.date_range(first_sale_date, last_observed_date, freq="D")
        daily_units = sku_sales.set_index("date")["daily_sold_units"].reindex(
            full_dates, fill_value=0
        )
        # At origin t, sum units from t+1 through t+7, both endpoints included.
        target = daily_units.shift(-1).rolling(horizon_days, min_periods=horizon_days).sum().shift(
            -(horizon_days - 1)
        )
        daily_rows.append(
            pd.DataFrame(
                {
                    "sku_id": sku_id,
                    "date": full_dates,
                    "daily_sold_units": daily_units.to_numpy(),
                }
            )
        )
        panel = pd.DataFrame(
            {
                "sku_id": sku_id,
                "forecast_origin_date": full_dates,
                "daily_sold_units": daily_units.to_numpy(),
                "demand_next_7d_units": target.to_numpy(),
            }
        )
        rows.append(panel.loc[panel["forecast_origin_date"].le(last_origin_date)])

    result = pd.concat(rows, ignore_index=True)
    result["daily_sold_units"] = result["daily_sold_units"].astype("int64")
    result["demand_next_7d_units"] = result["demand_next_7d_units"].round().astype("int64")
    result = result.sort_values(["sku_id", "forecast_origin_date"], kind="stable")
    full_daily = pd.concat(daily_rows, ignore_index=True).sort_values(["sku_id", "date"], kind="stable")
    full_daily["daily_sold_units"] = full_daily["daily_sold_units"].astype("int64")
    result["forecast_origin_date"] = result["forecast_origin_date"].dt.strftime("%Y-%m-%d")
    full_daily["date"] = full_daily["date"].dt.strftime("%Y-%m-%d")

    summary = {
        "source_rows": row_count_source,
        "usable_rows": len(usable),
        "cancelled_rows": int(cancelled.sum()),
        "positive_sales_rows": len(positive_sales),
        "excluded_non_product_rows": excluded_non_product_rows,
        "excluded_stock_codes": sorted(excluded_codes),
        "kept_exact_duplicate_rows": bool(policy["keep_exact_duplicate_rows"]),
        "sku_count": int(result["sku_id"].nunique()),
        "first_sale_date": daily["date"].min().date().isoformat(),
        "last_observed_date": last_observed_date.date().isoformat(),
        "last_forecast_origin_date": last_origin_date.date().isoformat(),
        "prepared_rows": len(result),
        "full_daily_rows": len(full_daily),
    }
    return result, full_daily, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH, help="เส้นทาง workbook ต้นทาง")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="เส้นทาง CSV.gz ที่จะสร้าง")
    parser.add_argument("--daily-output", type=Path, default=DAILY_PATH, help="ตารางยอดขายรายวันเต็มช่วง")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = load_source(args.source)
    prepared, full_daily, summary = build_daily_panel(
        source, config["preparation"], config["forecast_horizon_days"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.daily_output.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(args.output, index=False, compression="gzip")
    full_daily.to_csv(args.daily_output, index=False, compression="gzip")
    print("เตรียมข้อมูลสำเร็จ")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"output: {args.output}")
    print(f"full daily output: {args.daily_output}")


if __name__ == "__main__":
    main()
