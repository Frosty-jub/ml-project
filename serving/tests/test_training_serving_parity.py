"""Run the real serving API with a fitted group-format model and shared features."""

# ruff: noqa: E402 -- imports below require the repository path when run from serving/.

import hashlib
import json
import sys
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app
from src.demand_forecasting.features import build_features
from src.demand_forecasting.serving_features import prepare_prediction_request
from src.demand_forecasting.training.models import FeatureOrderedModel


def test_raw_history_to_api_matches_offline_features_and_model(tmp_path, record_property):
    config = json.loads((ROOT / "config/pipeline.json").read_text("utf-8"))
    dates = pd.date_range("2020-01-01", periods=100)
    panel = pd.DataFrame({"sku_id": "parity-fixture", "forecast_origin_date": dates,
                          "daily_sold_units": (np.arange(100) % 17) + 1,
                          "demand_next_7d_units": (np.arange(100) % 13) * 7 + 3})
    offline, _ = build_features(panel, config)
    names = [name for name in offline if name not in {"sku_id", "forecast_origin_date", "demand_next_7d_units"}]
    training = offline.loc[offline.forecast_origin_date.lt("2020-03-01")]
    estimator = lgb.LGBMRegressor(n_estimators=8, num_leaves=4, min_child_samples=2, n_jobs=1,
                                 random_state=7, verbosity=-1).fit(
        training[names].to_numpy(dtype=np.float32), training.demand_next_7d_units)
    model = FeatureOrderedModel(estimator, names)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    model_path = bundle / "model.joblib"
    joblib.dump(model, model_path)
    (bundle / "metadata.json").write_text(json.dumps({
        "model_name": "training-serving-parity-test", "model_version": "test-v1",
        "data_kind": "synthetic_test_fixture", "model_format": "feature_ordered_joblib",
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__, "lightgbm_version": lgb.__version__,
        "features": [{"name": name, "type": "number", "nullable": False} for name in names],
    }), encoding="utf-8")
    feature_error = prediction_error = 0.0
    with TestClient(create_app(bundle)) as client:
        assert client.get("/health").json()["model_version"] == "test-v1"
        for origin in ("2020-03-01", "2020-03-05", "2020-03-10"):
            payload, keys = prepare_prediction_request(panel, origin, config, {"feature_columns": names})
            expected_frame = offline.loc[offline.forecast_origin_date.eq(origin), names]
            actual_frame = pd.DataFrame(payload["records"])
            assert list(actual_frame.columns) == names
            np.testing.assert_array_equal(actual_frame.to_numpy(), expected_frame.to_numpy())
            feature_error = max(feature_error, float(np.max(np.abs(
                actual_frame.to_numpy() - expected_frame.to_numpy()))))
            # JSON object key order is irrelevant; the API restores model order.
            reordered = {"records": [dict(reversed(list(row.items()))) for row in payload["records"]]}
            response = client.post("/predict", json=reordered)
            assert response.status_code == 200
            assert response.json()["model_name"] == "training-serving-parity-test"
            assert response.json()["data_kind"] == "synthetic_test_fixture"
            expected = model.predict(expected_frame)
            actual = response.json()["predictions"]
            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-6)
            prediction_error = max(prediction_error, float(np.max(np.abs(actual - expected))))
            assert keys[0]["forecast_origin_date"] == origin
    record_property("data_kind", "synthetic_test_fixture")
    record_property("forecast_origins_checked", 3)
    record_property("feature_count", len(names))
    record_property("max_feature_absolute_error", feature_error)
    record_property("max_prediction_absolute_error", prediction_error)
