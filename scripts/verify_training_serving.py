"""Save feature/prediction parity evidence for a trusted exported model bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "serving"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app.runtime import ModelRuntime

from src.demand_forecasting.features import build_features
from src.demand_forecasting.serving_client import send_prediction_request
from src.demand_forecasting.serving_features import (
    load_feature_contract,
    prepare_prediction_request,
)


def verify_parity(
    history: pd.DataFrame, origin: str, config: dict, manifest: dict,
    model_dir: Path, url: str | None = None, skus: list[str] | None = None,
) -> dict:
    payload, keys = prepare_prediction_request(history, origin, config, manifest, skus)
    names = manifest["feature_columns"]
    panel = history.rename(columns={"date": "forecast_origin_date"}) if "forecast_origin_date" not in history else history
    panel = panel[["sku_id", "forecast_origin_date", "daily_sold_units"]].copy()
    panel["forecast_origin_date"] = pd.to_datetime(panel["forecast_origin_date"])
    panel = panel.loc[panel.sku_id.isin([row["sku_id"] for row in keys])]
    # Offline computation sees the full panel, including days after origin.
    offline, _ = build_features(panel, config)
    expected_frame = offline.loc[offline.forecast_origin_date.eq(origin), names]
    actual_frame = pd.DataFrame(payload["records"], columns=names)
    np.testing.assert_array_equal(actual_frame.to_numpy(), expected_frame.to_numpy())
    runtime = ModelRuntime(model_dir)
    if [spec.name for spec in runtime.manifest.features] != names:
        raise ValueError("Local bundle schema does not match the training manifest")
    if runtime.manifest.model_format == "lightgbm_booster":
        expected = np.maximum(runtime.pipeline.predict(expected_frame.to_numpy(dtype=np.float32)), 0.0)
    else:
        expected = runtime.pipeline.predict(expected_frame)
    if url:
        result = send_prediction_request(url, payload, names)
        for field in ("model_name", "model_version", "data_kind"):
            if result[field] != getattr(runtime.manifest, field):
                raise ValueError("HTTP endpoint does not use the expected local model version")
        # Names/versions alone do not identify model weights.
        from urllib.request import urlopen

        with urlopen(url.rstrip("/") + "/health", timeout=30) as response:
            health = json.load(response)
        if health.get("model_sha256") != runtime.manifest.model_sha256:
            raise ValueError("HTTP model checksum does not match the local bundle")
        transport = "HTTP"
    else:
        from app.main import create_app
        from fastapi.testclient import TestClient

        with TestClient(create_app(model_dir)) as client:
            response = client.post("/predict", json=payload)
            if response.status_code != 200:
                raise ValueError(f"API parity request failed with status {response.status_code}")
            result = response.json()
        transport = "FastAPI TestClient"
    actual = np.asarray(result["predictions"], dtype=float)
    expected = np.asarray(expected, dtype=float)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-6)
    return {
        "status": "passed", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_kind": runtime.manifest.data_kind, "model_name": runtime.manifest.model_name,
        "model_version": runtime.manifest.model_version, "model_sha256": runtime.manifest.model_sha256,
        "transport": transport, "row_count": len(keys), "feature_count": len(names),
        "feature_order_matches": True,
        "max_feature_absolute_error": float(np.max(np.abs(actual_frame.to_numpy() - expected_frame.to_numpy()))),
        "max_prediction_absolute_error": float(np.max(np.abs(actual - expected))),
        "prediction_absolute_tolerance": 1e-6,
        "feature_code_sha256": hashlib.sha256((ROOT / "src/demand_forecasting/features.py").read_bytes()).hexdigest(),
        "forecast_timing": "after origin-day sales close",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=ROOT / "data/interim/sku_daily_sales.csv.gz")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--sku", action="append")
    parser.add_argument("--config", type=Path, default=ROOT / "config/pipeline.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "reports/generated/feature_split_manifest.json")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--url", help="Optional live endpoint; otherwise use FastAPI TestClient")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Remove stale success evidence before evaluating this invocation.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"status": "running"}) + "\n", encoding="utf-8")
    try:
        config, manifest = load_feature_contract(args.config, args.manifest)
        history = pd.read_csv(args.history, dtype={"sku_id": "string"})
        report = verify_parity(history, args.origin, config, manifest, args.model_dir, args.url, args.sku)
        report["feature_manifest_sha256"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        report["configuration_sha256"] = manifest["configuration_sha256"]
        report["history_sha256"] = hashlib.sha256(args.history.read_bytes()).hexdigest()
    except Exception as exc:
        args.output.write_text(json.dumps({"status": "failed", "error_type": type(exc).__name__}) + "\n",
                               encoding="utf-8")
        raise
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Parity passed: {args.output}")


if __name__ == "__main__":
    main()
