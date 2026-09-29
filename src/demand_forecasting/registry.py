"""Track completed experiments and manage the validated forecasting model in MLflow.

Run from the repository root: python -m src.demand_forecasting.registry --help
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .training.train import OUTPUT_DIR, ROOT
from .serving_benchmark import benchmark_http, serving_gate
from .training.models import FeatureOrderedModel


POLICY_PATH = ROOT / "config" / "model_registry.json"
MODEL_PATH = OUTPUT_DIR / "final_candidate_model.joblib"
METADATA_PATH = OUTPUT_DIR / "final_candidate_metadata.json"
FOLD_PATH = OUTPUT_DIR / "experiment3_fold_metrics.json"


def read_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}; run Experiments 2 and 3 first")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evaluate_gate(metadata: dict, fold_rows: list[dict], model: object, policy: dict) -> dict:
    """Use the recorded validation folds and a live model probe; never inspect test rows."""
    checks: dict[str, bool] = {}
    features = metadata.get("feature_order")
    checks["feature_schema"] = (
        isinstance(features, list) and bool(features)
        and all(isinstance(name, str) and name for name in features)
        and len(features) == len(set(features))
        and getattr(model, "feature_names", None) == features
    )
    candidate = metadata.get("aggregate_metrics", {})
    baseline = metadata.get("baseline_metrics", {})
    trial_id = metadata.get("model_name")
    expected = int(policy["expected_folds"])
    minimum_wins = int(policy["minimum_fold_wins"])
    candidate_mae = candidate.get("MAE")
    baseline_mae = baseline.get("MAE")
    checks["metrics_finite"] = all(
        finite_number(row.get(metric)) and row[metric] >= 0
        for row in (candidate, baseline) for metric in ("MAE", "RMSE", "WAPE")
    )
    checks["beats_baseline"] = (
        finite_number(candidate_mae) and finite_number(baseline_mae)
        and candidate_mae < baseline_mae
    )
    candidate_folds = [row for row in fold_rows if row.get("trial_id") == trial_id]
    baseline_folds = [row for row in fold_rows if row.get("trial_id") == "historical_7d_sum"]
    candidate_by_fold = {row.get("fold"): row for row in candidate_folds}
    baseline_by_fold = {row.get("fold"): row for row in baseline_folds}
    checks["complete_folds"] = (
        len(candidate_folds) == expected and len(baseline_folds) == expected
        and len(candidate_by_fold) == expected and len(baseline_by_fold) == expected
        and set(candidate_by_fold) == set(baseline_by_fold)
        and all(finite_number(row.get("MAE")) and row["MAE"] >= 0
                for row in candidate_folds + baseline_folds)
    )
    fold_definitions = metadata.get("fold_date_ranges")
    checks["validation_protocol"] = False
    if (isinstance(fold_definitions, list) and len(fold_definitions) == expected
            and all(isinstance(row, dict) and isinstance(row.get("fold"), str)
                    for row in fold_definitions)):
        checks["validation_protocol"] = (
            {row["fold"] for row in fold_definitions} == set(candidate_by_fold)
        )
    wins = 0
    if checks["complete_folds"]:
        wins = sum(candidate_by_fold[name]["MAE"] < baseline_by_fold[name]["MAE"]
                   for name in candidate_by_fold)
        checks["aggregate_matches_folds"] = (
            abs(sum(row["MAE"] for row in candidate_folds) / expected - candidate_mae) < 1e-5
            and abs(sum(row["MAE"] for row in baseline_folds) / expected - baseline_mae) < 1e-5
            and candidate.get("folds_won_vs_baseline") == wins
        ) if finite_number(candidate_mae) and finite_number(baseline_mae) else False
    else:
        checks["aggregate_matches_folds"] = False
    checks["wins_required_folds"] = checks["complete_folds"] and wins >= minimum_wins
    checks["pretest_only"] = metadata.get("test_set_used") is False
    checks["prediction_integrity"] = False
    checks["rejects_wrong_feature_order"] = False
    if checks["feature_schema"]:
        try:
            probe = pd.DataFrame(np.zeros((2, len(features)), dtype=np.float32), columns=features)
            predicted = np.asarray(model.predict(probe), dtype=np.float64)
            checks["prediction_integrity"] = bool(
                predicted.shape == (2,) and np.isfinite(predicted).all() and (predicted >= 0).all()
            )
            if len(features) > 1:
                try:
                    model.predict(probe[features[::-1]])
                except ValueError:
                    checks["rejects_wrong_feature_order"] = True
            else:
                checks["rejects_wrong_feature_order"] = True
        except (TypeError, ValueError):
            pass
    return {
        "passed": all(checks.values()), "checks": checks,
        "candidate_mae": candidate_mae, "baseline_mae": baseline_mae,
        "folds_won": wins, "expected_folds": expected,
    }


def check_candidate() -> tuple[dict, dict, object]:
    metadata = read_json(METADATA_PATH)
    folds = read_json(FOLD_PATH)
    policy = read_json(POLICY_PATH)
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Missing {MODEL_PATH}; run Experiment 3 first")
    model = joblib.load(MODEL_PATH)
    result = evaluate_gate(metadata, folds, model, policy)
    result["model_sha256"] = sha256(MODEL_PATH)
    result["metadata_sha256"] = sha256(METADATA_PATH)
    result["policy_sha256"] = sha256(POLICY_PATH)
    result["validation_folds_sha256"] = canonical_sha256(metadata.get("fold_date_ranges"))
    return result, metadata, model


def configure_mlflow():
    import mlflow

    # A database backend supports the Registry. Override this for a shared server.
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    return mlflow


def log_trials() -> None:
    mlflow = configure_mlflow()
    policy = read_json(POLICY_PATH)
    mlflow.set_experiment(policy["experiment_name"])
    count = 0
    first_trials_path = OUTPUT_DIR / "tuning_results.csv"
    if not first_trials_path.is_file():
        raise FileNotFoundError(f"Missing {first_trials_path}; run Experiment 1 first")
    with first_trials_path.open(encoding="utf-8", newline="") as source:
        first_trials = list(csv.DictReader(source))
    if not first_trials:
        raise ValueError("Experiment 1 has no trial results")
    for index, trial in enumerate(first_trials, start=1):
        trial_id = f"experiment1-{index}-{trial['model']}"
        with mlflow.start_run(run_name=trial_id):
            mlflow.set_tags({"experiment_number": "1", "trial_id": trial_id,
                             "source_sha256": sha256(first_trials_path),
                             "validation_strategy": "single holdout", "validation_only": "true"})
            params = json.loads(trial["hyperparameters"])
            mlflow.log_params({**{key: str(value) for key, value in params.items()},
                               "model": trial["model"], "train_rows": trial["train_rows"]})
            for key in ("MAE", "RMSE", "WAPE"):
                if trial[key]:
                    value = float(trial[key])
                    if finite_number(value):
                        mlflow.log_metric(key.lower(), value)
            mlflow.log_dict(trial, "validation/trial.json")
        count += 1
    for number in (2, 3):
        trial_path = OUTPUT_DIR / f"experiment{number}_trials.json"
        fold_path = OUTPUT_DIR / f"experiment{number}_fold_metrics.json"
        trials, folds = read_json(trial_path), read_json(fold_path)
        for trial in trials:
            trial_id = trial["trial_id"]
            trial_folds = [row for row in folds if row["trial_id"] == trial_id]
            if len(trial_folds) != int(policy["expected_folds"]):
                raise ValueError(f"Incomplete fold metrics for Experiment {number} {trial_id}")
            with mlflow.start_run(run_name=f"experiment{number}-{trial_id}"):
                mlflow.set_tags({"experiment_number": str(number), "trial_id": trial_id,
                                 "source_sha256": sha256(trial_path), "validation_only": "true"})
                params = {key: str(value) for key, value in trial.get("parameters", {}).items()}
                params.update({"model": str(trial["model"]), "fold_count": str(len(trial_folds))})
                mlflow.log_params(params)
                for key in ("MAE", "MAE_std", "RMSE", "WAPE", "folds_won_vs_baseline"):
                    value = trial.get(key)
                    if finite_number(value):
                        mlflow.log_metric(key.lower(), value)
                for index, fold in enumerate(trial_folds):
                    for key in ("MAE", "RMSE", "WAPE"):
                        value = fold.get(key)
                        if finite_number(value):
                            mlflow.log_metric(f"fold_{key.lower()}", value, step=index)
                mlflow.log_dict(trial, "validation/trial.json")
                mlflow.log_dict(trial_folds, "validation/folds.json")
            count += 1
    print(f"Tracked {count} validation trials in {policy['experiment_name']}")


def register_candidate() -> int:
    gate, metadata, model = check_candidate()
    mlflow = configure_mlflow()
    policy = read_json(POLICY_PATH)
    mlflow.set_experiment(policy["experiment_name"])
    with mlflow.start_run(run_name=f"final-{metadata.get('model_name', 'candidate')}") as run:
        mlflow.set_tags({"trial_id": str(metadata.get("model_name", "unknown")), "validation_only": "true",
                         "gate_passed": str(gate["passed"]).lower(),
                         "source_model_sha256": gate["model_sha256"]})
        mlflow.log_params({key: str(value) for key, value in metadata.get("hyperparameters", {}).items()})
        mlflow.log_metrics({key: value for key, value in
                            {"validation_mae": gate["candidate_mae"],
                             "baseline_mae": gate["baseline_mae"],
                             "folds_won": gate["folds_won"]}.items() if finite_number(value)})
        mlflow.log_dict(gate, "quality/gate.json")
        mlflow.log_dict(metadata, "quality/source_metadata.json")
        if not gate["passed"]:
            print(f"Quality gate failed: {[name for name, ok in gate['checks'].items() if not ok]}; run {run.info.run_id}")
            return 2
        import mlflow.sklearn
        from mlflow.models import infer_signature

        features = metadata["feature_order"]
        # A double-valued signature accepts ordinary pandas float64 inputs; the
        # FeatureOrderedModel converts to float32 before calling LightGBM.
        example = pd.DataFrame(np.zeros((2, len(features)), dtype=np.float64), columns=features)
        signature = infer_signature(example, model.predict(example))
        info = mlflow.sklearn.log_model(
            model, name="candidate", signature=signature, input_example=example,
            serialization_format="cloudpickle", code_paths=[str(ROOT / "src")],
            registered_model_name=policy["registered_model_name"],
        )
        version = info.registered_model_version
        client = mlflow.MlflowClient()
        for key, value in {"gate_passed": "true", "validation_mae": gate["candidate_mae"],
                           "baseline_mae": gate["baseline_mae"], "folds_won": gate["folds_won"],
                           "source_model_sha256": gate["model_sha256"],
                           "validation_folds_sha256": gate["validation_folds_sha256"],
                           "source_experiment": "3"}.items():
            client.set_model_version_tag(policy["registered_model_name"], version, key, str(value))
    print(f"Registered {policy['registered_model_name']} version {version}; run {run.info.run_id}")
    return 0


def register_experiments() -> None:
    """Register one saved selected model per experiment; reuse existing versions."""
    mlflow = configure_mlflow()
    import mlflow.sklearn
    from mlflow.models import infer_signature

    policy = read_json(POLICY_PATH)
    name = policy["registered_model_name"]
    mlflow.set_experiment(policy["experiment_name"])
    client = mlflow.MlflowClient()
    existing = {item.tags.get("source_model_sha256"): item.version
                for item in client.search_model_versions(f"name='{name}'")}
    features = read_json(OUTPUT_DIR / "feature_list.json")["features"]
    fold_definitions = read_json(OUTPUT_DIR / "validation_folds.json")
    baseline = read_json(OUTPUT_DIR / "baseline_metrics.json")
    for number, path in ((1, OUTPUT_DIR / "best_model.joblib"),
                         (2, OUTPUT_DIR / "best_candidate_model.joblib"),
                         (3, MODEL_PATH)):
        if number == 1 and not path.exists():
            print("Skipping Experiment 1: source model is unavailable")
            continue
        digest = sha256(path)
        if digest in existing:
            client.set_model_version_tag(name, existing[digest], "source_experiment", str(number))
            print(f"Experiment {number}: existing version {existing[digest]}")
            continue
        loaded = joblib.load(path)
        model = FeatureOrderedModel(loaded, features) if number == 1 else loaded
        if getattr(model, "feature_names", None) != features:
            raise ValueError(f"Experiment {number} model feature schema does not match")
        if number == 1:
            summary = read_json(OUTPUT_DIR / "validation_metrics.json")
            candidate_mae = summary["MAE"]
            gate = {"passed": False, "reason": "Experiment 1 uses a single validation split; reference only"}
            fold_hash = "single_validation_split"
            wins = 0
        elif number == 2:
            metadata = read_json(OUTPUT_DIR / "experiment2_training_metadata.json")
            rows = read_json(OUTPUT_DIR / "experiment2_fold_metrics.json")
            trial = metadata["selected_trial"]
            candidate_rows = {row["fold"]: row for row in rows if row["trial_id"] == trial}
            baseline_rows = {row["fold"]: row for row in rows if row["trial_id"] == "historical_7d_sum"}
            wins = sum(candidate_rows[key]["MAE"] < baseline_rows[key]["MAE"] for key in candidate_rows)
            candidate = {**metadata["selected_metrics"], "folds_won_vs_baseline": wins}
            evidence = {"feature_order": features, "aggregate_metrics": candidate,
                        "baseline_metrics": baseline, "model_name": trial,
                        "fold_date_ranges": fold_definitions, "test_set_used": False}
            gate = evaluate_gate(evidence, rows, model, policy)
            candidate_mae = candidate["MAE"]
            fold_hash = canonical_sha256(fold_definitions)
        else:
            gate, metadata, model = check_candidate()
            candidate_mae = gate["candidate_mae"]
            wins = gate["folds_won"]
            fold_hash = gate["validation_folds_sha256"]
        example = pd.DataFrame(np.zeros((2, len(features)), dtype=np.float64), columns=features)
        with mlflow.start_run(run_name=f"selected-experiment{number}") as run:
            mlflow.set_tags({"source_experiment": str(number), "gate_passed": str(gate["passed"]).lower()})
            mlflow.log_dict(gate, "quality/validation_gate.json")
            mlflow.log_metric("validation_mae", candidate_mae)
            signature = infer_signature(example, model.predict(example))
            info = mlflow.sklearn.log_model(
                model, name="selected_model", signature=signature, input_example=example,
                serialization_format="cloudpickle", code_paths=[str(ROOT / "src")],
                registered_model_name=name,
            )
            version = info.registered_model_version
            tags = {"source_experiment": number, "source_model_sha256": digest,
                    "gate_passed": str(gate["passed"]).lower(),
                    "validation_mae": candidate_mae, "baseline_mae": baseline["MAE"],
                    "folds_won": wins, "validation_folds_sha256": fold_hash}
            for key, value in tags.items():
                client.set_model_version_tag(name, version, key, str(value))
        existing[digest] = version
        print(f"Experiment {number}: registered version {version}; run {run.info.run_id}")


def benchmark_version(version: str, url: str) -> dict:
    mlflow = configure_mlflow()
    policy = read_json(POLICY_PATH)
    name = policy["registered_model_name"]
    client = mlflow.MlflowClient()
    candidate = client.get_model_version(name, version)
    if candidate.tags.get("gate_passed") != "true":
        raise ValueError(f"Version {version} is a reference model without a passing validation gate")
    uri = f"models:/{name}/{version}"
    model = mlflow.sklearn.load_model(uri)
    features = model.feature_names
    result = benchmark_http(model, features, url, policy)
    gate = serving_gate(result, policy)
    result["gate"] = gate
    mlflow.set_experiment(policy["experiment_name"])
    with mlflow.start_run(run_name=f"serving-benchmark-v{version}") as run:
        mlflow.set_tags({"kind": "serving_benchmark", "model_version": version})
        mlflow.log_metrics({key: result[key] for key in
                            ("latency_p50_ms", "latency_p95_ms", "throughput_predictions_per_second",
                             "throughput_requests_per_second")})
        mlflow.log_dict(result, "serving/benchmark.json")
    tags = {"latency_p50_ms": result["latency_p50_ms"],
            "latency_p95_ms": result["latency_p95_ms"],
            "throughput_predictions_per_second": result["throughput_predictions_per_second"],
            "benchmark_batch_size": result["batch_size"],
            "benchmark_concurrency": result["concurrency"],
            "benchmark_measured_requests": result["measured_requests"],
            "benchmark_at_utc": result["measured_at_utc"],
            "benchmark_url": result["url"], "benchmark_run_id": run.info.run_id,
            "serving_gate_passed": str(gate["passed"]).lower()}
    for key, value in tags.items():
        client.set_model_version_tag(name, version, key, str(value))
    return result


def require_serving_gate(version, policy: dict) -> None:
    tags = version.tags
    if tags.get("gate_passed") != "true" or tags.get("serving_gate_passed") != "true":
        raise ValueError(f"Version {version.version} has not passed validation and serving gates")
    required = {"latency_p50_ms": float, "latency_p95_ms": float,
                "throughput_predictions_per_second": float,
                "benchmark_batch_size": int, "benchmark_measured_requests": int,
                "benchmark_concurrency": int}
    if any(key not in tags for key in required) or not tags.get("benchmark_url") or not tags.get("benchmark_run_id"):
        raise ValueError(f"Version {version.version} lacks serving measurements")
    measurements = {key: cast(tags[key]) for key, cast in required.items()}
    measurements["batch_size"] = measurements.pop("benchmark_batch_size")
    measurements["measured_requests"] = measurements.pop("benchmark_measured_requests")
    measurements["concurrency"] = measurements.pop("benchmark_concurrency")
    if not serving_gate(measurements, policy)["passed"]:
        raise ValueError(f"Version {version.version} fails current serving thresholds")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(tags["benchmark_at_utc"])
    if age.total_seconds() < 0 or age.total_seconds() > float(policy["maximum_benchmark_age_hours"]) * 3600:
        raise ValueError(f"Version {version.version} serving benchmark is stale")


def alias_version(model) -> dict[str, str]:
    return {alias: str(version) for alias, version in model.aliases.items()}


def promote(version: str, fallback_version: str | None = None) -> None:
    mlflow = configure_mlflow()
    policy = read_json(POLICY_PATH)
    name = policy["registered_model_name"]
    client = mlflow.MlflowClient()
    model = client.get_registered_model(name)
    aliases = alias_version(model)
    candidate = client.get_model_version(name, version)
    require_serving_gate(candidate, policy)
    if aliases.get("production") == version:
        print(f"Version {version} is already production")
        return
    champion_version = aliases.get("production") or aliases.get("champion")
    if champion_version is not None:
        champion = client.get_model_version(name, champion_version)
        if (not candidate.tags.get("validation_folds_sha256") or
                candidate.tags["validation_folds_sha256"] != champion.tags.get("validation_folds_sha256")):
            raise ValueError("Candidate and champion use different validation folds")
        candidate_mae = float(candidate.tags["validation_mae"])
        champion_mae = float(champion.tags["validation_mae"])
        allowed = champion_mae * (1 + float(policy["maximum_champion_mae_regression_pct"]) / 100)
        if not math.isfinite(candidate_mae) or candidate_mae > allowed:
            raise ValueError(f"Version {version} MAE {candidate_mae} exceeds champion limit {allowed}")
        fallback_version = champion_version
    if fallback_version is not None:
        fallback = client.get_model_version(name, fallback_version)
        require_serving_gate(fallback, policy)
        if fallback.tags.get("validation_folds_sha256") != candidate.tags.get("validation_folds_sha256"):
            raise ValueError("Fallback and production use different validation folds")
        client.set_registered_model_alias(name, "previous", fallback_version)
    client.set_registered_model_alias(name, "production", version)
    client.set_registered_model_alias(name, "champion", version)
    print(f"Promoted {name} version {version}; previous={fallback_version or 'none'}")


def rollback() -> None:
    mlflow = configure_mlflow()
    name = read_json(POLICY_PATH)["registered_model_name"]
    client = mlflow.MlflowClient()
    aliases = alias_version(client.get_registered_model(name))
    previous = aliases.get("previous")
    champion = aliases.get("production")
    if previous is None or champion is None or previous == champion:
        raise ValueError("Rollback requires distinct champion and previous aliases")
    client.set_registered_model_alias(name, "production", previous)
    client.set_registered_model_alias(name, "champion", previous)
    client.set_registered_model_alias(name, "previous", champion)
    print(f"Rolled back {name} to version {previous}; previous={champion}")


def status() -> None:
    mlflow = configure_mlflow()
    name = read_json(POLICY_PATH)["registered_model_name"]
    client = mlflow.MlflowClient()
    model = client.get_registered_model(name)
    print(json.dumps({"model": name, "aliases": alias_version(model),
                      "versions": [{"version": item.version, "tags": item.tags}
                                   for item in client.search_model_versions(f"name='{name}'")]}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "track", "register", "register-experiments", "rollback", "status"):
        commands.add_parser(command)
    promote_parser = commands.add_parser("promote")
    promote_parser.add_argument("version")
    promote_parser.add_argument("--fallback-version")
    benchmark_parser = commands.add_parser("benchmark")
    benchmark_parser.add_argument("version")
    benchmark_parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if args.command == "check":
        gate, _, _ = check_candidate()
        print(json.dumps(gate, indent=2))
        return 0 if gate["passed"] else 2
    if args.command == "track":
        log_trials()
    elif args.command == "register":
        return register_candidate()
    elif args.command == "register-experiments":
        register_experiments()
    elif args.command == "benchmark":
        print(json.dumps(benchmark_version(args.version, args.url), indent=2))
    elif args.command == "promote":
        promote(args.version, args.fallback_version)
    elif args.command == "rollback":
        rollback()
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
