"""Measure a registered model through an actual MLflow HTTP serving endpoint."""

from __future__ import annotations

import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .training.train import ROOT


def load_probe(features: list[str], batch_size: int) -> pd.DataFrame:
    path = ROOT / "data" / "processed" / "validation_features_7d.csv.gz"
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}; run the data pipeline first")
    frame = pd.read_csv(path, compression="gzip", usecols=features, nrows=max(batch_size * 20, 1000))
    if len(frame) < batch_size:
        raise ValueError("Validation split has fewer rows than the benchmark batch")
    return frame[features].sample(n=batch_size, random_state=42).reset_index(drop=True)


def post_predictions(url: str, payload: bytes) -> np.ndarray:
    request = urllib.request.Request(url.rstrip("/") + "/invocations", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if not isinstance(body, dict) or "predictions" not in body:
        raise ValueError("Serving endpoint did not return predictions")
    return np.asarray(body["predictions"], dtype=np.float64).reshape(-1)


def benchmark_http(model, features: list[str], url: str, policy: dict) -> dict:
    batch_size = int(policy["benchmark_batch_size"])
    warmup = int(policy["benchmark_warmup_requests"])
    measured = int(policy["benchmark_measured_requests"])
    concurrency = int(policy["benchmark_concurrency"])
    if batch_size < 1 or warmup < 1 or measured < 2 or concurrency < 1:
        raise ValueError("Invalid benchmark sample sizes")
    frame = load_probe(features, batch_size)
    payload = json.dumps({"dataframe_split": {"columns": features,
                          "data": frame.to_numpy(dtype=float).tolist()}}).encode("utf-8")
    expected = np.asarray(model.predict(frame), dtype=np.float64).reshape(-1)
    def request_once() -> float:
        started = time.perf_counter()
        actual = post_predictions(url, payload)
        elapsed = time.perf_counter() - started
        if actual.shape != expected.shape or not np.isfinite(actual).all() or not np.allclose(actual, expected, rtol=1e-5, atol=1e-5):
            raise ValueError("HTTP endpoint predictions do not match the selected model version")
        return elapsed

    for _ in range(warmup):
        request_once()
    latencies = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(request_once) for _ in range(measured)]
        for future in as_completed(futures):
            latencies.append(future.result())
    wall_seconds = time.perf_counter() - started
    return {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "url": url.rstrip("/"), "batch_size": batch_size,
        "warmup_requests": warmup, "measured_requests": measured,
        "concurrency": concurrency,
        "latency_p50_ms": float(np.percentile(latencies, 50) * 1000),
        "latency_p95_ms": float(np.percentile(latencies, 95) * 1000),
        "throughput_predictions_per_second": float(batch_size * measured / wall_seconds),
        "throughput_requests_per_second": float(measured / wall_seconds),
        "environment": "http_serving",
    }


def serving_gate(result: dict, policy: dict) -> dict:
    checks = {
        "latency_p50": math.isfinite(result["latency_p50_ms"]) and result["latency_p50_ms"] >= 0 and result["latency_p50_ms"] <= float(policy["maximum_latency_p50_ms"]),
        "latency_p95": math.isfinite(result["latency_p95_ms"]) and result["latency_p95_ms"] >= result["latency_p50_ms"] and result["latency_p95_ms"] <= float(policy["maximum_latency_p95_ms"]),
        "throughput": math.isfinite(result["throughput_predictions_per_second"]) and result["throughput_predictions_per_second"] >= float(policy["minimum_throughput_predictions_per_second"]),
        "request_count": result["measured_requests"] >= int(policy["benchmark_measured_requests"]),
        "batch_size": result["batch_size"] == int(policy["benchmark_batch_size"]),
        "concurrency": result["concurrency"] == int(policy["benchmark_concurrency"]),
    }
    return {"passed": all(checks.values()), "checks": checks}
