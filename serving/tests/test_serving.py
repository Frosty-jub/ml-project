"""Behavioral checks: real model, bad data, readiness and observability."""

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime import ModelRuntime
from scripts.train_demo import build_demo

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "demo"
VALID = json.loads((ROOT / "examples" / "valid_request.json").read_text("utf-8"))


@pytest.fixture(scope="session", autouse=True)
def demo_bundle():
    if not MODEL.exists():
        build_demo(MODEL)


@pytest.fixture
def client():
    with TestClient(create_app(MODEL)) as instance:
        yield instance


def test_health_and_model_identity(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["data_kind"] == "synthetic_demo_only"


def test_serving_matches_training_pipeline_and_preserves_column_order(client):
    original = VALID["records"][0]
    reordered = dict(reversed(list(original.items())))
    response = client.post("/predict", json={"records": [reordered]}, headers={"X-Request-ID": "integration-001"})
    runtime = ModelRuntime(MODEL)
    expected = runtime.pipeline.predict(runtime.validate([original]))
    assert response.status_code == 200
    np.testing.assert_allclose(response.json()["predictions"], expected, rtol=0, atol=1e-12)
    assert response.json()["request_id"] == "integration-001"
    assert response.headers["X-Request-ID"] == "integration-001"


def test_missing_value_uses_fitted_imputer(client):
    row = {**VALID["records"][0], "lag_1": None}
    response = client.post("/predict", json={"records": [row]})
    assert response.status_code == 200
    assert np.isfinite(response.json()["predictions"][0])


@pytest.mark.parametrize(
    "change",
    [
        {"lag_1": "160"},
        {"lag_1": True},
        {"lag_1": []},
        {"lag_1": {}},
        {"lag_7": -1},
        {"lag_7": None},
        {"day_of_week": 7},
        {"day_of_week": 2.5},
        {"extra": 1},
        {"lag_1": 10**400},
    ],
)
def test_invalid_features_rejected_without_inference(client, change):
    assert client.post("/predict", json={"records": [{**VALID["records"][0], **change}]}).status_code == 422
    metrics = client.get("/metrics").text
    assert "serving_predictions_total{" not in metrics


def test_missing_feature_and_empty_batch(client):
    row = VALID["records"][0].copy()
    row.pop("lag_7")
    assert client.post("/predict", json={"records": [row]}).status_code == 422
    assert client.post("/predict", json={"records": []}).status_code == 422


def test_batch_limit_and_envelope(client):
    assert client.post("/predict", json={"records": VALID["records"] * 65}).status_code == 422
    assert client.post("/predict", json={**VALID, "unexpected": True}).status_code == 422
    assert client.post("/predict", json={"records": ["not-a-row"]}).status_code == 422


def test_nonfinite_json_and_broken_json(client):
    for literal in ("NaN", "Infinity", "-Infinity"):
        raw = json.dumps(VALID).replace("160.0", literal)
        assert client.post("/predict", content=raw, headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/predict", content="{bad", headers={"Content-Type": "application/json"}).status_code == 422


def test_unavailable_model_is_not_healthy(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/predict", json=VALID).status_code == 503
        assert "serving_model_ready 0.0" in client.get("/metrics").text


def test_mismatched_checksum_refuses_to_load(tmp_path):
    (tmp_path / "model.joblib").write_bytes(b"wrong-model")
    (tmp_path / "metadata.json").write_text((MODEL / "metadata.json").read_text("utf-8"), encoding="utf-8")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 503


def test_inference_failure_returns_error_without_leaking_internal_details(client):
    def broken(frame):
        raise RuntimeError("private internal detail")

    client.app.state.runtime.pipeline.predict = broken
    response = client.post("/predict", json=VALID)
    assert response.status_code == 500
    assert "private internal detail" not in response.text
    assert "serving_prediction_failures_total 1.0" in client.get("/metrics").text


def test_metrics_expose_request_latency_prediction_and_validation(client):
    assert client.post("/predict", json=VALID).status_code == 200
    assert client.post("/predict", json={"records": []}).status_code == 422
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "serving_request_duration_seconds_bucket" in metrics.text
    assert 'serving_predictions_total{model_version="demo-v1"} 1.0' in metrics.text
    assert 'status="422"' in metrics.text


def test_monitoring_events_only_capture_valid_predictions(client, tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("MONITORING_EVENTS_PATH", str(events))
    payload = {"records": [VALID["records"][0], VALID["records"][0]]}
    response = client.post("/predict", json=payload, headers={"X-Request-ID": "monitor-001"})
    assert response.status_code == 200
    assert client.post("/predict", json={"records": []}).status_code == 422
    rows = [json.loads(line) for line in events.read_text("utf-8").splitlines()]
    assert [(row["request_id"], row["row_index"]) for row in rows] == [
        ("monitor-001", 0), ("monitor-001", 1)
    ]
    assert [row["prediction"] for row in rows] == response.json()["predictions"]
    assert all(row["data_kind"] == "synthetic_demo_only" for row in rows)


def test_observation_write_failure_is_visible_without_losing_prediction(client, tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("block")
    monkeypatch.setenv("MONITORING_EVENTS_PATH", str(blocker / "events.jsonl"))
    assert client.post("/predict", json=VALID).status_code == 200
    assert "serving_observation_write_failures_total 1.0" in client.get("/metrics").text


def test_unknown_routes_use_bounded_metric_label(client):
    client.get("/random-route-123")
    metrics = client.get("/metrics").text
    assert 'route="unmatched"' in metrics
    assert "random-route-123" not in metrics
