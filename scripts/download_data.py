"""Download the official UCI Online Retail II workbook."""

from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
ZIP_PATH = RAW_DIR / "online_retail_II.zip"
XLSX_PATH = RAW_DIR / "online_retail_II.xlsx"
SOURCE_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
EXPECTED_XLSX = "online_retail_II.xlsx"


def download_archive(destination: Path, force: bool = False) -> None:
    if destination.exists() and not force:
        print(f"พบไฟล์ ZIP แล้ว: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "CP413008-demand-forecasting/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with temporary_path.open("wb") as output:
                shutil.copyfileobj(response, output)
        if not zipfile.is_zipfile(temporary_path):
            raise ValueError("ไฟล์ที่ดาวน์โหลดไม่ใช่ ZIP ที่อ่านได้")
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def extract_workbook(archive_path: Path, destination: Path, force: bool = False) -> None:
    if destination.exists() and not force:
        print(f"พบ workbook แล้ว: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    with zipfile.ZipFile(archive_path) as archive:
        workbook_members = [
            name
            for name in archive.namelist()
            if Path(name).name.lower() == EXPECTED_XLSX.lower()
        ]
        if len(workbook_members) != 1:
            raise FileNotFoundError(
                f"คาดว่า ZIP จะมี {EXPECTED_XLSX} หนึ่งไฟล์ แต่พบ {len(workbook_members)} ไฟล์"
            )
        with archive.open(workbook_members[0]) as source, temporary_path.open("wb") as output:
            shutil.copyfileobj(source, output)
    temporary_path.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="ดาวน์โหลดและเขียนทับไฟล์เดิม")
    args = parser.parse_args()

    download_archive(ZIP_PATH, force=args.force)
    extract_workbook(ZIP_PATH, XLSX_PATH, force=args.force)
    print(f"พร้อมใช้: {XLSX_PATH}")


if __name__ == "__main__":
    main()
