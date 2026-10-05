"""Build an API request with the training feature function; optionally send it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.demand_forecasting.serving_client import send_prediction_request
from src.demand_forecasting.serving_features import (
    load_feature_contract,
    prepare_prediction_request,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=ROOT / "data/interim/sku_daily_sales.csv.gz")
    parser.add_argument("--origin", required=True, help="Closed sales date (YYYY-MM-DD)")
    parser.add_argument("--sku", action="append", help="Repeat to select SKUs; default selects all")
    parser.add_argument("--config", type=Path, default=ROOT / "config/pipeline.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "reports/generated/feature_split_manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", help="Optional serving base URL, e.g. http://127.0.0.1:18005")
    args = parser.parse_args()
    config, manifest = load_feature_contract(args.config, args.manifest)
    history = pd.read_csv(args.history, dtype={"sku_id": "string"})
    payload, keys = prepare_prediction_request(history, args.origin, config, manifest, args.sku)
    write_json(args.output, payload)
    receipt = {
        "row_keys": keys,
        "feature_columns": manifest["feature_columns"],
        "configuration_sha256": manifest["configuration_sha256"],
        "feature_manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "feature_code_sha256": hashlib.sha256((ROOT / "src/demand_forecasting/features.py").read_bytes()).hexdigest(),
        "history_sha256": hashlib.sha256(args.history.read_bytes()).hexdigest(),
        "request_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "forecast_timing": "after origin-day sales close; future rows and targets excluded",
    }
    if args.url:
        result = send_prediction_request(args.url, payload, manifest["feature_columns"])
        response_path = args.output.with_suffix(".response.json")
        write_json(response_path, result)
        receipt["model_name"] = result["model_name"]
        receipt["model_version"] = result["model_version"]
        receipt["data_kind"] = result["data_kind"]
        receipt["response_path"] = str(response_path)
    write_json(args.output.with_suffix(".metadata.json"), receipt)
    print(f"Prepared {len(keys)} records: {args.output}")


if __name__ == "__main__":
    main()
