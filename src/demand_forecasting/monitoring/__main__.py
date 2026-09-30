"""Run with python -m src.demand_forecasting.monitoring from repository root."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.request
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np

from src.demand_forecasting.monitoring.core import (
    analyze,
    build_reference,
    identity,
    join_labels,
    load_events,
    timestamp,
)
from src.demand_forecasting.training.metrics import evaluate

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "config" / "monitoring.json"


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def events_with_labels(args, policy):
    return join_labels(load_events(args.events), args.labels, policy["forecast_horizon_days"])


def service_status(url: str, policy: dict) -> dict:
    """Read the person-4 health endpoint and process-lifetime Prometheus counters."""
    root = url.rstrip("/")
    with urllib.request.urlopen(root + "/health", timeout=5) as response:
        health = json.load(response)
    with urllib.request.urlopen(root + "/metrics", timeout=5) as response:
        metrics = response.read().decode("utf-8")
    counters = {}
    for match in re.finditer(r'^serving_requests_total\{[^}]*status="(\d+)"[^}]*\} ([0-9.]+)$',
                             metrics, flags=re.MULTILINE):
        counters[match.group(1)] = counters.get(match.group(1), 0) + float(match.group(2))
    total = sum(counters.values())
    error_rate = sum(v for k, v in counters.items() if int(k) >= 500) / total if total else 0.0
    failure = re.search(r"^serving_observation_write_failures_total ([0-9.]+)$", metrics, re.MULTILINE)
    writes_failed = float(failure.group(1)) if failure else 0.0
    buckets = []
    for match in re.finditer(
        r'^serving_request_duration_seconds_bucket\{[^}]*route="/predict"[^}]*le="([^"]+)"[^}]*\} ([0-9.]+)$',
        metrics, flags=re.MULTILINE,
    ):
        buckets.append((float(match.group(1)), float(match.group(2))))
    buckets.sort()
    p95_bound = next((bound for bound, count in buckets if buckets and count >= .95 * buckets[-1][1]),
                     None) if buckets and buckets[-1][1] else None
    alerts = []
    if health.get("status") != "ok":
        alerts.append("model_not_ready")
    if error_rate > policy["maximum_http_error_rate"]:
        alerts.append("http_5xx_rate")
    if writes_failed:
        alerts.append("observation_write_failed")
    if p95_bound is not None and (not math.isfinite(p95_bound) or
                                  p95_bound > policy["maximum_http_p95_seconds"]):
        alerts.append("http_p95_latency")
    # This counter is cumulative since process start; short-window service SLOs use load_test.py.
    return {"health": health, "http_5xx_rate_since_restart": error_rate,
            "http_requests_since_restart": total, "observation_write_failures_since_restart": writes_failed,
            "http_p95_bucket_upper_bound_seconds_since_restart":
                p95_bound if p95_bound is None or math.isfinite(p95_bound) else "above_last_finite_bucket",
            "alerts": alerts}


def retrain(args, policy):
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not report.get("retraining_trigger"):
        raise ValueError("Monitoring policy has not triggered retraining")
    if report.get("source_sha256") != {
        "events": hashlib.sha256(args.events.read_bytes()).hexdigest(),
        "labels": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
    }:
        raise ValueError("Monitoring inputs changed after trigger; run check again")
    rows = events_with_labels(args, policy)
    model_identity = identity(rows)
    if model_identity != report["identity"]:
        raise ValueError("Retraining events do not match the monitoring report")
    if model_identity["data_kind"] != "group_project" and not (
        args.allow_demo and model_identity["data_kind"] == "synthetic_demo_only"
    ):
        raise ValueError("Retraining requires group_project observations; use --allow-demo for simulation")
    matured = sorted((row for row in rows if "actual" in row), key=lambda row: row["timestamp"])
    if len(matured) < args.minimum_rows:
        raise ValueError("Not enough mature labelled observations to retrain")
    days = sorted({timestamp(row["timestamp"]).date() for row in matured})
    if len(days) < 3:
        raise ValueError("Retraining needs at least three observation dates")
    split_day = days[max(1, int(len(days) * 0.8))]
    split_at = timestamp(split_day.isoformat() + "T00:00:00+00:00")
    gap = timedelta(days=policy["forecast_horizon_days"])
    training = [row for row in matured if timestamp(row["timestamp"]) + gap < split_at]
    holdout = [row for row in matured if timestamp(row["timestamp"]) >= split_at]
    if len(training) < args.minimum_train or len(holdout) < args.minimum_holdout:
        raise ValueError("Too few train/holdout rows after seven-day label embargo")
    features = model_identity["feature_names"]
    if any(any(not isinstance(row["features"][name], (int, float)) or
               not np.isfinite(row["features"][name]) for name in features)
           for row in matured):
        raise ValueError("Real-model retraining requires finite numeric features")
    def matrix(items):
        return np.array([[row["features"][name] for name in features] for row in items], dtype=np.float32)
    y_train = np.array([row["actual"] for row in training])
    y_holdout = np.array([row["actual"] for row in holdout])
    current = joblib.load(args.current_model)  # Trusted team-generated artifact only.
    if list(getattr(current, "feature_names", [])) != features:
        raise ValueError("Champion feature order differs from live observations")
    import lightgbm
    from lightgbm import LGBMRegressor

    from src.demand_forecasting.training.models import FeatureOrderedModel
    params = json.loads(args.params.read_text(encoding="utf-8"))
    champion_predictions = current.predict(matrix(holdout))
    if not np.allclose(champion_predictions, [row["prediction"] for row in holdout], rtol=1e-5, atol=1e-5):
        raise ValueError("Champion artifact does not reproduce the recorded live predictions")
    champion = evaluate(y_holdout, champion_predictions)
    estimator = LGBMRegressor(random_state=42, **params)
    estimator.fit(matrix(training), y_train)
    candidate = FeatureOrderedModel(estimator, features)
    candidate_scores = evaluate(y_holdout, candidate.predict(matrix(holdout)))
    approved_for_review = candidate_scores["MAE"] < champion["MAE"]
    args.output.mkdir(parents=True, exist_ok=False)
    joblib.dump(candidate, args.output / "candidate_model.joblib")
    result = {
        "source_model": model_identity, "trigger_report_sha256": hashlib.sha256(args.report.read_bytes()).hexdigest(),
        "source_events_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
        "source_labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
        "training_rows": len(training), "holdout_rows": len(holdout),
        "embargo_days": policy["forecast_horizon_days"], "holdout_start": split_at.isoformat(),
        "champion": champion, "candidate": candidate_scores, "candidate_beats_champion": approved_for_review,
        "registered_or_promoted": False, "model_type": "LightGBM", "parameters": params,
        "data_kind": model_identity["data_kind"],
        "lightgbm_version": lightgbm.__version__,
    }
    save_json(args.output / "candidate_review.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Monitor seven-day SKU demand, then train a reviewable candidate")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("reference", "check", "retrain", "simulate"):
        command = commands.add_parser(name)
        if name == "simulate":
            command.add_argument("--output-dir", required=True, type=Path)
        else:
            command.add_argument("--events", required=True, type=Path)
            command.add_argument("--labels", type=Path)
            command.add_argument("--output", required=True, type=Path)
    commands.choices["check"].add_argument("--reference", required=True, type=Path)
    commands.choices["check"].add_argument("--health-url", help="Optional person-4 API base URL")
    command = commands.choices["retrain"]
    command.add_argument("--report", required=True, type=Path)
    command.add_argument("--current-model", required=True, type=Path)
    command.add_argument("--params", type=Path, default=ROOT / "artifacts/training/final_candidate_params.json")
    command.add_argument("--minimum-rows", type=int, default=100)
    command.add_argument("--minimum-train", type=int, default=50)
    command.add_argument("--minimum-holdout", type=int, default=20)
    command.add_argument("--allow-demo", action="store_true", help="Train a demo candidate; never promote it")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if args.command == "simulate":
        from src.demand_forecasting.monitoring.simulate import generate
        result = generate(args.output_dir)
    elif args.command == "retrain":
        if args.labels is None:
            parser.error("retrain requires --labels")
        result = retrain(args, policy)
    else:
        rows = events_with_labels(args, policy)
        if args.command == "reference":
            result = build_reference(rows, policy["minimum_labelled_rows"])
        else:
            reference = json.loads(args.reference.read_text(encoding="utf-8"))
            result = analyze(rows, reference, policy)
            result["source_sha256"] = {
                "events": hashlib.sha256(args.events.read_bytes()).hexdigest(),
                "labels": hashlib.sha256(args.labels.read_bytes()).hexdigest() if args.labels else None,
            }
            if args.health_url:
                try:
                    result["service"] = service_status(args.health_url, policy)
                except (OSError, ValueError) as exc:
                    result["service"] = {"alerts": ["service_unreachable"], "error_type": type(exc).__name__}
        save_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
