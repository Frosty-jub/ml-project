"""Person 2 exports the SAME fitted pipeline that was evaluated in training."""

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline

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
