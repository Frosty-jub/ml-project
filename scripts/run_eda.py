"""Profile Online Retail II and regenerate the reproducible EDA report."""

from __future__ import annotations

import gc
import hashlib
import json
from html import escape
from pathlib import Path

import pandas as pd

from prepare_data import normalize_sku


ROOT = Path(__file__).resolve().parents[1]
RAW_XLSX = ROOT / "data" / "raw" / "online_retail_II.xlsx"
RAW_ZIP = ROOT / "data" / "raw" / "online_retail_II.zip"
PANEL_CSV = ROOT / "data" / "processed" / "sku_daily_demand_7d.csv.gz"
REPORT = ROOT / "reports" / "eda_summary.md"
FIGURES = ROOT / "reports" / "figures"
CONFIG_PATH = ROOT / "config" / "pipeline.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def write_line_svg(labels: list[str], values: list[float], title: str, path: Path) -> None:
    width, height = 1000, 430
    left, right, top, bottom = 105, 35, 65, 75
    plot_width, plot_height = width - left - right, height - top - bottom
    maximum = max(values) * 1.08 if values else 1
    maximum = max(maximum, 1)
    points = [
        (left + i * plot_width / max(len(values) - 1, 1), top + plot_height * (1 - v / maximum))
        for i, v in enumerate(values)
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="35" font-family="Arial,sans-serif" font-size="23" font-weight="700" fill="#17212f">{escape(title)}</text>',
    ]
    for tick in range(5):
        value = maximum * tick / 4
        y = top + plot_height * (1 - tick / 4)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5eaf0"/>')
        parts.append(f'<text x="{left-12}" y="{y+5:.1f}" text-anchor="end" font-family="Arial,sans-serif" font-size="13" fill="#536171">{value:,.0f}</text>')
    if points:
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        parts.append(f'<polyline points="{polyline}" fill="none" stroke="#1769aa" stroke-width="3"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#1769aa"/>')
    label_step = max(1, (len(labels) - 1) // 8)
    for i in range(0, len(labels), label_step):
        x = left + i * plot_width / max(len(labels) - 1, 1)
        parts.append(f'<text x="{x:.1f}" y="{height-32}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#536171">{escape(labels[i])}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_bar_svg(labels: list[str], values: list[float], title: str, path: Path) -> None:
    width, left, right, top, row_height = 1000, 190, 115, 72, 35
    height = top + len(labels) * row_height + 35
    plot_width = width - left - right
    maximum = max(values) if values else 1
    maximum = max(maximum, 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="35" font-family="Arial,sans-serif" font-size="23" font-weight="700" fill="#17212f">{escape(title)}</text>',
    ]
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        y = top + i * row_height
        bar_width = value / maximum * plot_width
        parts.append(f'<text x="{left-12}" y="{y+19}" text-anchor="end" font-family="Arial,sans-serif" font-size="14" fill="#344456">{escape(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="24" rx="3" fill="#1769aa"/>')
        parts.append(f'<text x="{left+bar_width+8:.1f}" y="{y+18}" font-family="Arial,sans-serif" font-size="13" fill="#344456">{value:,.0f}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def profile_raw() -> dict[str, object]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    excluded_codes = set(config["preparation"]["excluded_stock_codes"])
    sheets = pd.read_excel(RAW_XLSX, sheet_name=None, engine="openpyxl")
    sheet_counts = {name: len(frame) for name, frame in sheets.items()}
    raw = pd.concat(sheets.values(), ignore_index=True)
    missing = raw.isna().sum().to_dict()
    duplicate_rows = int(raw.duplicated().sum())
    invoice = raw["Invoice"].astype("string").str.strip()
    sku = normalize_sku(raw["StockCode"])
    quantity = pd.to_numeric(raw["Quantity"], errors="coerce")
    price = pd.to_numeric(raw["Price"], errors="coerce")
    invoice_date = pd.to_datetime(raw["InvoiceDate"], errors="coerce")
    cancelled = invoice.str.upper().str.startswith("C", na=False)
    keep = invoice.notna() & sku.notna() & invoice_date.notna() & quantity.gt(0) & ~cancelled
    sales = pd.DataFrame(
        {
            "invoice": invoice,
            "sku_id": sku,
            "description": raw["Description"].astype("string"),
            "quantity": quantity,
            "invoice_date": invoice_date,
        }
    ).loc[keep]
    excluded_rows = int(sales["sku_id"].str.upper().isin(excluded_codes).sum())
    sales["month"] = sales["invoice_date"].dt.to_period("M").astype(str)
    monthly = sales.groupby("month", sort=True)["quantity"].sum()
    top_skus = sales.groupby("sku_id", sort=False)["quantity"].sum().nlargest(10)
    letter_only = sales.loc[~sales["sku_id"].str.contains(r"\d", na=False)]
    code_candidates = (
        letter_only.groupby("sku_id")
        .agg(lines=("quantity", "size"), units=("quantity", "sum"), example_description=("description", "first"))
        .sort_values("lines", ascending=False)
        .head(15)
    )
    outliers = sales.nlargest(5, "quantity")[["invoice", "sku_id", "description", "quantity", "invoice_date"]]
    result = {
        "source_rows": len(raw),
        "sheet_counts": sheet_counts,
        "missing": missing,
        "duplicate_rows": duplicate_rows,
        "cancelled_rows": int(cancelled.sum()),
        "nonpositive_after_cancellation": int((~cancelled & quantity.le(0)).sum()),
        "nonpositive_price_rows": int(price.le(0).sum()),
        "positive_sales_rows": len(sales),
        "excluded_non_product_rows": excluded_rows,
        "excluded_codes": sorted(excluded_codes),
        "first_date": invoice_date.min().date().isoformat(),
        "last_date": invoice_date.max().date().isoformat(),
        "distinct_skus": int(sku.nunique()),
        "quantity_quantiles": quantity.loc[keep].quantile([0.5, 0.9, 0.99, 0.999]).to_dict(),
        "max_positive_quantity": float(quantity.loc[keep].max()),
        "monthly": monthly,
        "top_skus": top_skus,
        "code_candidates": code_candidates,
        "outliers": outliers,
    }
    del sheets, raw, sales, letter_only
    gc.collect()
    return result


def profile_panel() -> dict[str, object]:
    panel = pd.read_csv(
        PANEL_CSV,
        compression="gzip",
        dtype={"sku_id": "string"},
        parse_dates=["forecast_origin_date"],
    )
    per_sku = panel.groupby("sku_id", sort=False)
    zero_share = panel["daily_sold_units"].eq(0).groupby(panel["sku_id"]).mean()
    coverage = per_sku.size()
    histogram = pd.cut(
        zero_share,
        bins=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        include_lowest=True,
        labels=[f"{i * 10}–{(i + 1) * 10}%" for i in range(10)],
    ).value_counts(sort=False)
    result = {
        "rows": len(panel),
        "skus": int(panel["sku_id"].nunique()),
        "first_origin": panel["forecast_origin_date"].min().date().isoformat(),
        "last_origin": panel["forecast_origin_date"].max().date().isoformat(),
        "duplicate_sku_date": int(panel.duplicated(["sku_id", "forecast_origin_date"]).sum()),
        "missing": panel.isna().sum().to_dict(),
        "zero_day_rows": int(panel["daily_sold_units"].eq(0).sum()),
        "zero_target_rows": int(panel["demand_next_7d_units"].eq(0).sum()),
        "negative_daily_rows": int(panel["daily_sold_units"].lt(0).sum()),
        "negative_target_rows": int(panel["demand_next_7d_units"].lt(0).sum()),
        "target_quantiles": panel["demand_next_7d_units"].quantile([0.5, 0.9, 0.99, 0.999]).to_dict(),
        "target_max": int(panel["demand_next_7d_units"].max()),
        "zero_share_sku_median": float(zero_share.median()),
        "sku_zero_share_ge_90": int(zero_share.ge(0.9).sum()),
        "coverage_min": int(coverage.min()),
        "coverage_median": int(coverage.median()),
        "coverage_max": int(coverage.max()),
        "zero_histogram": histogram,
    }
    del panel
    gc.collect()
    return result


def write_report(raw: dict[str, object], panel: dict[str, object]) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    monthly = raw["monthly"]
    top_skus = raw["top_skus"]
    zero_histogram = panel["zero_histogram"]
    write_line_svg(monthly.index.tolist(), monthly.astype(float).tolist(), "Monthly positive units sold", FIGURES / "monthly_units.svg")
    write_bar_svg(top_skus.index.astype(str).tolist(), top_skus.astype(float).tolist(), "Top 10 SKUs by units sold", FIGURES / "top_skus.svg")
    write_bar_svg(zero_histogram.index.astype(str).tolist(), zero_histogram.astype(float).tolist(), "SKUs by zero-sale-day share", FIGURES / "zero_day_share.svg")

    missing_rows = [[name, f"{count:,}", f"{count / raw['source_rows']:.1%}"] for name, count in raw["missing"].items()]
    candidate_rows = [
        [sku, f"{int(row.lines):,}", f"{row.units:,.0f}", row.example_description]
        for sku, row in raw["code_candidates"].iterrows()
    ]
    outlier_rows = [
        [row.invoice, row.sku_id, row.description, f"{row.quantity:,.0f}", row.invoice_date.date().isoformat()]
        for row in raw["outliers"].itertuples(index=False)
    ]
    quantile_rows = [
        [f"{int(level * 1000) / 10:g}%", f"{raw['quantity_quantiles'][level]:,.0f}", f"{panel['target_quantiles'][level]:,.0f}"]
        for level in [0.5, 0.9, 0.99, 0.999]
    ]
    lines = [
        "# รายงาน EDA ข้อมูล Online Retail II",
        "",
        "รายงานนี้สร้างจากข้อมูลดิบและตาราง SKU รายวันที่เตรียมแล้วด้วย `python scripts/run_eda.py` จากโฟลเดอร์หลักของโครงงาน แหล่งข้อมูล: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)",
        "",
        f"SHA-256 ของ ZIP ต้นทาง: `{sha256(RAW_ZIP)}`",
        "",
        "## ข้อมูลดิบ",
        "",
        f"ข้อมูลมี {raw['source_rows']:,} แถวจากสอง sheet: " + ", ".join(f"`{name}` {count:,} แถว" for name, count in raw["sheet_counts"].items()) + ".",
        "",
        markdown_table(
            ["สิ่งที่ตรวจ", "จำนวนแถว"],
            [
                ["แถวซ้ำกันทุกคอลัมน์ (ยังไม่ลบ)", f"{raw['duplicate_rows']:,}"],
                ["Invoice ยกเลิกที่ขึ้นต้น C", f"{raw['cancelled_rows']:,}"],
                ["Quantity ≤ 0 หลังตัด invoice ยกเลิก", f"{raw['nonpositive_after_cancellation']:,}"],
                ["Price ≤ 0 (ยังไม่ตัดด้วยกฎนี้)", f"{raw['nonpositive_price_rows']:,}"],
                ["แถวขายบวกก่อนตัดรหัสที่ไม่ใช่สินค้า", f"{raw['positive_sales_rows']:,}"],
                ["แถวรหัสที่ไม่ใช่สินค้าที่ตัดออก", f"{raw['excluded_non_product_rows']:,}"],
                ["แถวขายบวกที่ใช้ในตารางรายวัน", f"{raw['positive_sales_rows'] - raw['excluded_non_product_rows']:,}"],
                ["จำนวนรหัส SKU ในไฟล์ดิบ", f"{raw['distinct_skus']:,}"],
            ],
        ),
        "",
        "### ค่าว่างในข้อมูลดิบ",
        "",
        markdown_table(["คอลัมน์", "แถวที่ว่าง", "สัดส่วน"], missing_rows),
        "",
        "### รหัสที่อาจไม่ใช่สินค้าคงคลัง",
        "",
        "ตารางนี้เป็นรายการรหัสที่ **ไม่มีตัวเลขในรหัส** จากข้อมูลดิบ รหัสตัวอักษรบางตัวอาจเป็นสินค้าจริง และรหัสค่าบริการบางตัวอาจมีตัวเลข",
        "",
        "กฎที่ใช้งานจริงอยู่ใน `config/pipeline.json`: ตัด " + ", ".join(f"`{code}`" for code in raw["excluded_codes"]) + " และยังคงแถวที่เหมือนกันทุกคอลัมน์ไว้ เหตุผลอยู่ใน `docs/data_pipeline_feature_engineering.md`",
        "",
        markdown_table(["StockCode", "แถวขายบวก", "หน่วยขายบวก", "ตัวอย่างคำอธิบาย"], candidate_rows),
        "",
        "### จำนวนขายต่อบรรทัดและค่ามากผิดปกติ",
        "",
        markdown_table(["เปอร์เซ็นไทล์", "Quantity ต่อบรรทัด", "Target รวม 7 วัน"], quantile_rows),
        "",
        f"จำนวนขายบวกต่อบรรทัดสูงสุด: {raw['max_positive_quantity']:,.0f} หน่วย รายการที่สูงมากควรตรวจว่าเป็นยอดขายส่งหรือข้อมูลผิด ไม่ควรลบด้วยเกณฑ์ตัวเลขโดยไม่มีเหตุผล",
        "",
        markdown_table(["Invoice", "SKU", "Description", "Quantity", "วันที่"], outlier_rows),
        "",
        "## แนวโน้มยอดขาย",
        "",
        "กราฟนี้รวมจำนวนขายบวกจากข้อมูลดิบหลังกรอง invoice ยกเลิกและ Quantity ที่ไม่เป็นบวก โดยยังไม่ลบแถวซ้ำหรือรหัสค่าบริการ จึงใช้สำรวจข้อมูลก่อนกฎ clean สุดท้าย",
        "",
        "![จำนวนหน่วยขายบวกแยกตามเดือน](figures/monthly_units.svg)",
        "",
        "![SKU 10 อันดับแรกตามหน่วยขายบวก](figures/top_skus.svg)",
        "",
        "## ตาราง SKU รายวันสำหรับพยากรณ์",
        "",
        markdown_table(
            ["สิ่งที่ตรวจ", "ผล"],
            [
                ["แถว SKU × วัน", f"{panel['rows']:,}"],
                ["SKU ที่มีวัน origin พร้อม label", f"{panel['skus']:,}"],
                ["ช่วงวัน origin", f"{panel['first_origin']} ถึง {panel['last_origin']}"],
                ["คู่ SKU–วันซ้ำ", f"{panel['duplicate_sku_date']:,}"],
                ["แถวที่ยอดขายรายวันเป็น 0", f"{panel['zero_day_rows']:,} ({panel['zero_day_rows'] / panel['rows']:.1%})"],
                ["แถวที่ target 7 วันเป็น 0", f"{panel['zero_target_rows']:,} ({panel['zero_target_rows'] / panel['rows']:.1%})"],
                ["จำนวนขายรายวันติดลบ", f"{panel['negative_daily_rows']:,}"],
                ["Target ติดลบ", f"{panel['negative_target_rows']:,}"],
                ["เปอร์เซ็นไทล์กลางของสัดส่วนวันขาย 0 ต่อ SKU", f"{panel['zero_share_sku_median']:.1%}"],
                ["SKU ที่มีวันขาย 0 ตั้งแต่ 90% ขึ้นไป", f"{panel['sku_zero_share_ge_90']:,}"],
                ["จำนวนวันต่อ SKU (ต่ำสุด / กลาง / สูงสุด)", f"{panel['coverage_min']:,} / {panel['coverage_median']:,} / {panel['coverage_max']:,}"],
            ],
        ),
        "",
        "![การกระจายสัดส่วนวันที่ไม่มียอดขายต่อ SKU](figures/zero_day_share.svg)",
        "",
        "## การตัดสินใจที่ต้องทำก่อนฝึกโมเดล",
        "",
        "1. ทบทวนการคงแถวที่เหมือนกันทุกคอลัมน์เมื่อมีหลักฐานเพิ่มเติม เช่น รหัสบรรทัดธุรกรรม เพราะข้อมูลนี้ยังแยกธุรกรรมที่เหมือนกันไม่ได้",
        "2. ให้ทีมทบทวนรายการรหัสที่ตัดออกใน `config/pipeline.json` และรหัสกำกวม เช่น `M` ก่อนล็อกชุดข้อมูลสำหรับการทดลองโมเดล",
        "3. พิจารณา SKU ที่มีวันขาย 0 มากหรือมีประวัติสั้น เพราะบาง SKU อาจเลิกขายหรือเริ่มขายใกล้วันสิ้นสุดข้อมูล",
        "4. ตรวจธุรกรรมปริมาณสูงและราคาที่ไม่เป็นบวกก่อนตัดหรือเก็บ โดยอย่ากรอง outlier จากตัวเลขอย่างเดียว",
        "5. ยืนยันกับทีมว่าการเติมวันไม่มีรายการขายเป็น 0 เหมาะกับการสาธิตหรือไม่ เพราะข้อมูลนี้ไม่มีสถานะสินค้าคงเหลือหรือช่วงของหมด",
        "",
        "รายงานนี้เป็น EDA เพื่อประกอบการตัดสินใจ ส่วน Data Validation ที่หยุด pipeline เมื่อข้อมูลผิดอยู่ใน `scripts/validate_data.py`",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not RAW_XLSX.exists() or not RAW_ZIP.exists() or not PANEL_CSV.exists():
        raise FileNotFoundError("ไม่พบข้อมูลดิบหรือข้อมูลที่เตรียมแล้ว ให้รัน download_data.py และ prepare_data.py ก่อน")
    raw = profile_raw()
    panel = profile_panel()
    write_report(raw, panel)
    print(f"EDA report: {REPORT}")
    print(f"Raw rows: {raw['source_rows']:,}; prepared rows: {panel['rows']:,}; exact duplicate rows: {raw['duplicate_rows']:,}")


if __name__ == "__main__":
    main()
