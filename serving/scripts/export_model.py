"""Export an approved Registry version into a versioned serving bundle."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
SERVING_ROOT = ROOT / "serving"
for import_root in (ROOT, SERVING_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.demand_forecasting.training.models import FeatureOrderedModel
from app.runtime import FeatureSpec, Manifest, ModelRuntime


def export_bundle(
    pipeline: Pipeline,
    sample: pd.DataFrame,
    features: list[dict],
    destination: str | Path,
    model_name: str,
    model_version: str,
    data_kind: str = "group_project",
    max_batch_size: int = 64,
) -> Path:
    if not isinstance(pipeline, Pipeline):
        raise TypeError("Provide a fitted sklearn Pipeline including preprocessing")
    parsed = [FeatureSpec.model_validate(feature) for feature in features]
    names = [feature.name for feature in parsed]
    if list(sample.columns) != names or list(getattr(pipeline, "feature_names_in_", [])) != names:
        raise ValueError("Pipeline, sample and schema must have the same feature names/order")
    if sample.empty:
        raise ValueError("Provide at least one sample row")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    if model_path.exists() or (destination / "metadata.json").exists():
        raise FileExistsError("Export to a new version directory; existing models are preserved")
    joblib.dump(pipeline, model_path)
    manifest = Manifest(
        model_name=model_name,
        model_version=model_version,
        data_kind=data_kind,
        model_format="sklearn_pipeline",
        sklearn_version=sklearn.__version__,
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        max_batch_size=max_batch_size,
        features=parsed,
    )
    (destination / "metadata.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    payload = {"records": json.loads(sample.head(3).to_json(orient="records"))}
    runtime = ModelRuntime(destination)
    runtime.predict(runtime.validate(payload["records"]))
    (destination / "sample_request.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destination


def export_lightgbm_bundle(
    model,
    sample: pd.DataFrame,
    destination: str | Path,
    model_name: str,
    model_version: str,
    data_kind: str = "group_project",
    max_batch_size: int = 64,
) -> Path:
    """Export the group's FeatureOrderedModel as a native LightGBM model file."""
    names = list(getattr(model, "feature_names", []))
    inner_model = getattr(model, "model", None)
    booster = getattr(inner_model, "booster_", None)
    if not names or booster is None:
        raise TypeError("Expected the registered FeatureOrderedModel wrapping a fitted LightGBM estimator")
    if list(sample.columns) != names:
        raise ValueError("Sample columns must match the model's feature names and order")
    if sample.empty or booster.num_feature() != len(names):
        raise ValueError("Sample must be non-empty and the booster feature count must match the model schema")

    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Export to an empty version directory; existing model bundles are preserved")
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.txt"
    booster.save_model(str(model_path))
    manifest = Manifest(
        model_name=model_name,
        model_version=model_version,
        data_kind=data_kind,
        model_format="lightgbm_booster",
        sklearn_version=None,
        lightgbm_version=lgb.__version__,
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        max_batch_size=max_batch_size,
        features=[FeatureSpec(name=name, type="number", nullable=False) for name in names],
    )
    (destination / "metadata.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    payload = {"records": json.loads(sample.head(3).to_json(orient="records"))}
    runtime = ModelRuntime(destination)
    actual = np.asarray(runtime.predict(runtime.validate(payload["records"])), dtype=np.float64)
    expected = np.asarray(model.predict(sample.head(3)), dtype=np.float64).reshape(-1)
    if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=0, atol=1e-5):
        raise ValueError("Exported LightGBM bundle predictions do not match the Registry model")
    (destination / "sample_request.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destination


def export_feature_ordered_joblib_bundle(
    model: FeatureOrderedModel,
    sample: pd.DataFrame,
    destination: str | Path,
    model_name: str,
    model_version: str,
    data_kind: str = "group_project",
    max_batch_size: int = 64,
) -> Path:
    """Export the registered FeatureOrderedModel as a source-backed joblib bundle."""
    if not isinstance(model, FeatureOrderedModel):
        raise TypeError("Expected the registered FeatureOrderedModel")
    names = list(model.feature_names)
    if not names or list(sample.columns) != names:
        raise ValueError("Sample columns must match the model's feature names and order")
    if sample.empty:
        raise ValueError("Sample must contain at least one row")

    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Export to an empty version directory; existing model bundles are preserved")
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    joblib.dump(model, model_path)
    manifest = Manifest(
        model_name=model_name,
        model_version=model_version,
        data_kind=data_kind,
        model_format="feature_ordered_joblib",
        sklearn_version=sklearn.__version__,
        lightgbm_version=lgb.__version__,
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        max_batch_size=max_batch_size,
        features=[FeatureSpec(name=name, type="number", nullable=False) for name in names],
    )
    (destination / "metadata.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    payload = {"records": json.loads(sample.head(3).to_json(orient="records"))}
    runtime = ModelRuntime(destination)
    actual = np.asarray(runtime.predict(runtime.validate(payload["records"])), dtype=np.float64)
    expected = np.asarray(model.predict(sample.head(3)), dtype=np.float64).reshape(-1)
    if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=0, atol=1e-5):
        raise ValueError("Exported FeatureOrderedModel predictions do not match the Registry model")
    (destination / "sample_request.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destination


def export_registered_model(version: str, destination: str | Path | None = None) -> Path:
    """Export a quality-gated Registry version using the real validation feature schema."""
    import mlflow
    import mlflow.sklearn

    policy_path = ROOT / "config" / "model_registry.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    model_name = policy["registered_model_name"]
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    client = mlflow.MlflowClient()
    version_info = client.get_model_version(model_name, version)
    if version_info.tags.get("gate_passed") != "true":
        raise ValueError(f"Registry version {version} has not passed the validation quality gate")
    model = mlflow.sklearn.load_model(f"models:/{model_name}/{version}")

    feature_manifest_path = ROOT / "reports" / "generated" / "feature_split_manifest.json"
    if not feature_manifest_path.is_file():
        raise FileNotFoundError("Feature manifest missing; run the data pipeline first")
    feature_manifest = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
    features = list(feature_manifest.get("feature_columns", []))
    if features != list(getattr(model, "feature_names", [])):
        raise ValueError("Registry model feature order does not match the current feature manifest")
    validation_path = ROOT / feature_manifest["splits"]["validation"]["path"]
    sample = pd.read_csv(validation_path, compression="gzip", usecols=features, nrows=3)[features]
    if len(sample) < 1 or not np.isfinite(sample.to_numpy(dtype=np.float32)).all():
        raise ValueError("Validation sample is empty or contains non-finite features")

    if not isinstance(model, FeatureOrderedModel):
        raise TypeError("Registry model is not the expected FeatureOrderedModel")
    if destination is None:
        destination = ROOT / "serving" / "artifacts" / f"group-v{version}-joblib"
    return export_feature_ordered_joblib_bundle(
        model=model,
        sample=sample,
        destination=destination,
        model_name=model_name,
        model_version=str(version),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Approved MLflow Registry version to export")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    path = export_registered_model(args.version, args.destination)
    print(f"Exported Registry model to {path}")


if __name__ == "__main__":
    main()
