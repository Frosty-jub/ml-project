"""Load a trusted sklearn pipeline and validate its serving contract."""

import hashlib
import json
import math
import threading
from pathlib import Path
import sys
from typing import Literal

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.pipeline import Pipeline


class FeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: Literal["number", "integer", "string"]
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: list[str] | None = None

    @model_validator(mode="after")
    def check_constraints(self):
        if self.type == "string" and (self.minimum is not None or self.maximum is not None):
            raise ValueError("String features cannot have numeric bounds")
        if self.type != "string" and self.choices is not None:
            raise ValueError("choices is only supported for string features")
        for bound in (self.minimum, self.maximum):
            if bound is not None and not math.isfinite(bound):
                raise ValueError("Bounds must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    data_kind: str = Field(min_length=1)
    model_format: Literal["sklearn_pipeline", "lightgbm_booster", "feature_ordered_joblib"] = "sklearn_pipeline"
    sklearn_version: str | None = None
    lightgbm_version: str | None = None
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    max_batch_size: int = Field(default=64, ge=1, le=10000)
    features: list[FeatureSpec] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_features(self):
        names = [feature.name for feature in self.features]
        if len(names) != len(set(names)):
            raise ValueError("Feature names must be unique")
        return self


class InvalidRecords(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("Input records do not match the model schema")
        self.errors = errors


class ModelRuntime:
    def __init__(self, model_dir: Path):
        self.manifest = Manifest.model_validate_json((model_dir / "metadata.json").read_text("utf-8"))
        model_path = model_dir / ("model.txt" if self.manifest.model_format == "lightgbm_booster" else "model.joblib")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != self.manifest.model_sha256:
            raise ValueError("Model checksum does not match metadata")
        expected = [feature.name for feature in self.manifest.features]
        if self.manifest.model_format == "sklearn_pipeline":
            if self.manifest.sklearn_version != sklearn.__version__:
                raise ValueError("Use the sklearn version recorded in metadata.json")
            self.pipeline = joblib.load(model_path)
            if not isinstance(self.pipeline, Pipeline):
                raise ValueError("Export the fitted preprocessing and estimator as one sklearn Pipeline")
            actual = list(getattr(self.pipeline, "feature_names_in_", []))
            if actual != expected:
                raise ValueError("Pipeline feature names/order must match metadata.json")
        elif self.manifest.model_format == "lightgbm_booster":
            if self.manifest.lightgbm_version != lgb.__version__:
                raise ValueError("Use the LightGBM version recorded in metadata.json")
            self.pipeline = lgb.Booster(model_file=str(model_path))
            if self.pipeline.num_feature() != len(expected):
                raise ValueError("LightGBM feature count must match metadata.json")
        else:
            if self.manifest.sklearn_version != sklearn.__version__:
                raise ValueError("Use the sklearn version recorded in metadata.json")
            if self.manifest.lightgbm_version != lgb.__version__:
                raise ValueError("Use the LightGBM version recorded in metadata.json")
            project_root = None
            for candidate in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
                if (candidate / "src" / "demand_forecasting" / "training" / "models.py").is_file():
                    project_root = candidate
                    break
            if project_root is None:
                raise ValueError("Project source for FeatureOrderedModel is missing from the serving image")
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from src.demand_forecasting.training.models import FeatureOrderedModel

            self.pipeline = joblib.load(model_path)
            if not isinstance(self.pipeline, FeatureOrderedModel):
                raise ValueError("Export a FeatureOrderedModel as model.joblib")
            actual = list(getattr(self.pipeline, "feature_names", []))
            if actual != expected:
                raise ValueError("FeatureOrderedModel feature names/order must match metadata.json")
        # Bound CPU inference to one operation; HTTP validation remains concurrent.
        self.inference_lock = threading.Lock()

    def validate(self, records: list[dict]) -> pd.DataFrame:
        errors = []
        if not 1 <= len(records) <= self.manifest.max_batch_size:
            raise InvalidRecords(
                [{"field": "records", "message": f"Provide 1..{self.manifest.max_batch_size} records"}]
            )
        names = [feature.name for feature in self.manifest.features]
        for index, row in enumerate(records):
            for missing in sorted(set(names) - set(row)):
                errors.append({"row": index, "field": missing, "message": "Required feature is missing"})
            for extra in sorted(set(row) - set(names)):
                errors.append({"row": index, "field": extra, "message": "Unknown feature"})
            for spec in self.manifest.features:
                if spec.name not in row:
                    continue
                value = row[spec.name]
                message = None
                if value is None:
                    if not spec.nullable:
                        message = "null is not allowed"
                elif spec.type == "string":
                    if not isinstance(value, str):
                        message = "Expected a string"
                    elif spec.choices is not None and value not in spec.choices:
                        message = "Value is not an allowed category"
                else:
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        message = "Expected a JSON number (numeric strings/booleans are not accepted)"
                    else:
                        try:
                            finite = math.isfinite(value)
                        except (ValueError, OverflowError):
                            finite = False
                        if not finite:
                            message = "Number must be finite"
                        elif spec.type == "integer" and not isinstance(value, int):
                            message = "Expected an integer"
                        elif spec.minimum is not None and value < spec.minimum:
                            message = f"Must be >= {spec.minimum}"
                        elif spec.maximum is not None and value > spec.maximum:
                            message = f"Must be <= {spec.maximum}"
                if message:
                    errors.append({"row": index, "field": spec.name, "message": message})
        if errors:
            raise InvalidRecords(errors)
        # Stable column order and numeric NaN are also used during training.
        numeric = {spec.name: float for spec in self.manifest.features if spec.type != "string"}
        if len(numeric) == len(names):
            return pd.DataFrame(records, columns=names, dtype=float)
        frame = pd.DataFrame(records, columns=names).astype(numeric)
        return frame.where(frame.notna(), np.nan)

    def predict(self, frame: pd.DataFrame) -> list[float]:
        with self.inference_lock:
            if self.manifest.model_format == "lightgbm_booster":
                result = np.asarray(self.pipeline.predict(frame.to_numpy(dtype=np.float32)), dtype=float)
                result = np.maximum(result, 0.0)
            elif self.manifest.model_format == "feature_ordered_joblib":
                result = np.asarray(self.pipeline.predict(frame), dtype=float)
            else:
                result = np.asarray(self.pipeline.predict(frame), dtype=float)
        if result.ndim != 1 or len(result) != len(frame) or not np.all(np.isfinite(result)):
            raise RuntimeError("Model must return one finite numeric prediction per record")
        return result.tolist()

    def public_schema(self) -> dict:
        return json.loads(self.manifest.model_dump_json(exclude={"model_sha256", "sklearn_version", "lightgbm_version"}))
