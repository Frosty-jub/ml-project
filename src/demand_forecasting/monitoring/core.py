"""Strict observation joins, drift statistics and alert decisions."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.demand_forecasting.training.metrics import evaluate


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include an offset")
    return parsed.astimezone(timezone.utc)


def load_events(path: Path) -> list[dict]:
    result = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["request_id"], int(row["row_index"]))
        if key in seen:
            raise ValueError(f"Duplicate prediction key: {key}")
        seen.add(key)
        row["row_index"] = key[1]
        timestamp(row["timestamp"])
        if not isinstance(row["features"], dict) or not row["features"]:
            raise ValueError("Observation needs nonempty features")
        if not math.isfinite(float(row["prediction"])):
            raise ValueError("Prediction must be finite")
        result.append(row)
    if not result:
        raise ValueError("No prediction observations")
    return result


def join_labels(events: list[dict], path: Path | None, horizon_days: int) -> list[dict]:
    labels = {}
    if path is not None:
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (row["request_id"], int(row["row_index"]))
                if key in labels:
                    raise ValueError(f"Duplicate actual label: {key}")
                actual = float(row["actual"])
                if not math.isfinite(actual) or actual < 0:
                    raise ValueError(f"Invalid actual demand: {key}")
                labels[key] = (actual, timestamp(row["observed_at"]))
    seen = set()
    joined = []
    for event in events:
        row = dict(event)
        key = (row["request_id"], row["row_index"])
        if key in labels:
            actual, observed = labels[key]
            if observed < timestamp(row["timestamp"]) + timedelta(days=horizon_days):
                raise ValueError(f"Label arrived before seven-day horizon: {key}")
            row["actual"] = actual
            seen.add(key)
        joined.append(row)
    if set(labels) != seen:
        raise ValueError(f"Labels without matching predictions: {sorted(set(labels) - seen)[:3]}")
    return joined


def identity(rows: list[dict]) -> dict:
    fields = ("model_name", "model_version", "data_kind")
    first = {field: rows[0][field] for field in fields}
    names = list(rows[0]["features"])
    for row in rows:
        if any(row[field] != first[field] for field in fields):
            raise ValueError("Do not mix model versions or synthetic and real observations")
        if list(row["features"]) != names:
            raise ValueError("Feature names/order changed within the observation stream")
    return {**first, "feature_names": names}


def distribution(rows: list[dict], features: list[str]) -> dict:
    output = {}
    for name in features:
        values = [row["features"][name] for row in rows]
        nonnull = [value for value in values if value is not None]
        if nonnull and all(isinstance(v, (int, float)) and not isinstance(v, bool) and
                           math.isfinite(v) for v in nonnull):
            # Preserve zero/nonzero and tails via fixed reference quantile boundaries.
            edges = np.unique(np.quantile(nonnull, np.linspace(0, 1, 11)[1:-1])).tolist()
            counts = np.bincount(np.searchsorted(edges, nonnull, side="right"), minlength=len(edges) + 1)
            output[name] = {"kind": "numeric", "edges": edges,
                            "proportions": (counts / len(values)).tolist(),
                            "null_ratio": (len(values) - len(nonnull)) / len(values)}
        else:
            categories = {}
            for value in values:
                key = json.dumps(value, ensure_ascii=False, sort_keys=True)
                categories[key] = categories.get(key, 0) + 1
            output[name] = {"kind": "categorical",
                            "proportions": {k: v / len(values) for k, v in categories.items()}}
    return output


def drift(rows: list[dict], reference: dict) -> dict:
    result = {}
    for name, baseline in reference.items():
        values = [row["features"][name] for row in rows]
        n = len(values)
        if baseline["kind"] == "numeric":
            nonnull = [float(value) for value in values if value is not None]
            if any(not math.isfinite(value) for value in nonnull):
                raise ValueError(f"Nonfinite observed feature: {name}")
            counts = np.bincount(np.searchsorted(baseline["edges"], nonnull, side="right"),
                                 minlength=len(baseline["proportions"]) )
            current = np.array([*counts, n - len(nonnull)], dtype=float) / n
            original = np.array([*baseline["proportions"], baseline["null_ratio"]], dtype=float)
            # Laplace-like smoothing avoids infinite PSI for empty reference bins.
            p = np.maximum(original, 1e-6)
            q = np.maximum(current, 1e-6)
            score = float(np.sum((q - p) * np.log(q / p)))
            result[name] = {"metric": "PSI", "value": round(score, 6)}
        else:
            current = {}
            for value in values:
                key = json.dumps(value, ensure_ascii=False, sort_keys=True)
                current[key] = current.get(key, 0) + 1 / n
            before = baseline["proportions"]
            score = .5 * sum(abs(before.get(k, 0) - current.get(k, 0))
                             for k in before.keys() | current.keys())
            result[name] = {"metric": "TVD", "value": round(score, 6)}
    return result


def labelled_metrics(rows: list[dict], minimum: int) -> dict | None:
    labelled = [row for row in rows if "actual" in row]
    if len(labelled) < minimum:
        return None
    scores = evaluate(np.array([row["actual"] for row in labelled]),
                      np.array([row["prediction"] for row in labelled]))
    return {"rows": len(labelled), **scores}


def build_reference(rows: list[dict], minimum: int) -> dict:
    model = identity(rows)
    metrics = labelled_metrics(rows, minimum)
    if len(rows) < minimum or metrics is None:
        raise ValueError("Reference requires enough mature labelled rows")
    return {"identity": model, "rows": len(rows), "metrics": metrics,
            "distribution": distribution(rows, model["feature_names"]),
            "period": [min(row["timestamp"] for row in rows), max(row["timestamp"] for row in rows)]}


def analyze(rows: list[dict], reference: dict, policy: dict) -> dict:
    if identity(rows) != reference["identity"]:
        raise ValueError("Model version, data kind or feature schema differs from reference")
    start = min(timestamp(row["timestamp"]) for row in rows)
    days = int(policy["window_days"])
    groups = {}
    for row in rows:
        bucket = (timestamp(row["timestamp"]) - start).days // days
        groups.setdefault(bucket, []).append(row)
    windows = []
    consecutive = 0
    previous_index = None
    for index, group in sorted(groups.items()):
        if previous_index is not None and index != previous_index + 1:
            consecutive = 0
        previous_index = index
        item = {"window": index, "rows": len(group), "start": min(r["timestamp"] for r in group),
                "end": max(r["timestamp"] for r in group), "labelled_rows": sum("actual" in r for r in group),
                "alerts": []}
        if len(group) < policy["minimum_window_rows"]:
            item["status"] = "insufficient_data"
            consecutive = 0
            windows.append(item)
            continue
        item["drift"] = drift(group, reference["distribution"])
        shifted = [name for name, value in item["drift"].items()
                   if value["value"] >= policy["numeric_psi_alert" if value["metric"] == "PSI"
                                             else "categorical_tvd_alert"]]
        if shifted:
            item["alerts"].append({"type": "data_drift", "features": shifted})
        metrics = labelled_metrics(group, policy["minimum_labelled_rows"])
        item["metrics"] = metrics
        if metrics is None:
            item["label_status"] = "pending_mature_labels"
            consecutive = 0
        else:
            old = reference["metrics"]["MAE"]
            degraded = (metrics["MAE"] >= old * policy["mae_ratio_alert"]
                        and metrics["MAE"] - old >= policy["mae_absolute_increase_alert"])
            if degraded:
                item["alerts"].append({"type": "performance_degradation", "MAE": metrics["MAE"]})
                if not shifted:
                    item["alerts"].append({"type": "suspected_concept_drift",
                                           "reason": "MAE increased while monitored feature distribution stayed stable"})
                consecutive += 1
            else:
                consecutive = 0
        item["status"] = "alert" if item["alerts"] else "ok"
        item["consecutive_degraded_windows"] = consecutive
        windows.append(item)
    return {"identity": reference["identity"], "windows": windows,
            "retraining_trigger": consecutive >= policy["consecutive_degraded_windows_to_retrain"],
            "policy": policy}
