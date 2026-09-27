"""FastAPI endpoints, structured request logs and Prometheus metrics."""

import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from app.runtime import InvalidRecords, ModelRuntime

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("serving")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def log_event(event: str, **fields):
    LOGGER.info(
        json.dumps(
            {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields},
            ensure_ascii=False,
        )
    )


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[dict[str, Any]] = Field(min_length=1, max_length=10000)


class PredictionResponse(BaseModel):
    request_id: str
    model_name: str
    model_version: str
    data_kind: str
    predictions: list[float]


def create_app(model_dir: str | Path | None = None) -> FastAPI:
    registry = CollectorRegistry()
    requests = Counter("serving_requests_total", "HTTP responses", ["method", "route", "status"], registry=registry)
    duration = Histogram(
        "serving_request_duration_seconds",
        "HTTP handler latency",
        ["route"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
        registry=registry,
    )
    predictions = Counter(
        "serving_predictions_total", "Successfully predicted rows", ["model_version"], registry=registry
    )
    failures = Counter("serving_prediction_failures_total", "Inference failures", registry=registry)
    ready = Gauge("serving_model_ready", "1 when model loaded, otherwise 0", registry=registry)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.runtime = None
        path = Path(model_dir or os.environ.get("MODEL_DIR", ROOT / "artifacts" / "demo"))
        try:
            application.state.runtime = ModelRuntime(path)
            ready.set(1)
            log_event(
                "model_loaded",
                model_version=application.state.runtime.manifest.model_version,
                data_kind=application.state.runtime.manifest.data_kind,
            )
        except Exception as exc:
            ready.set(0)
            log_event("model_load_failed", error_type=type(exc).__name__, reason=str(exc))
        yield
        ready.set(0)

    application = FastAPI(title="CP413008 — Person 4 Model Serving", version="1.0.0", lifespan=lifespan)

    @application.middleware("http")
    async def observe(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = supplied if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", supplied) else uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log_event("unhandled_error", request_id=request.state.request_id, error_type=type(exc).__name__)
            response = JSONResponse(
                status_code=500, content={"error": "internal_error", "request_id": request.state.request_id}
            )
        route = getattr(request.scope.get("route"), "path", "unmatched")
        elapsed = time.perf_counter() - started
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Process-Time-Ms"] = f"{elapsed * 1000:.3f}"
        if route != "/metrics":
            requests.labels(request.method, route, str(response.status_code)).inc()
            duration.labels(route).observe(elapsed)
            log_event(
                "http_request",
                request_id=request.state.request_id,
                method=request.method,
                route=route,
                status=response.status_code,
                latency_ms=round(elapsed * 1000, 3),
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_envelope(request: Request, exc: RequestValidationError):
        # Omit raw input values and exception objects from responses/logs.
        errors = [{"location": list(error["loc"]), "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "details": errors, "request_id": request.state.request_id},
        )

    def get_runtime() -> ModelRuntime:
        runtime = application.state.runtime
        if runtime is None:
            raise HTTPException(status_code=503, detail="Model is unavailable; check service logs")
        return runtime

    @application.get("/health")
    def health():
        runtime = application.state.runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={"status": "not_ready", "model_loaded": False})
        return {
            "status": "ok",
            "model_loaded": True,
            "model_name": runtime.manifest.model_name,
            "model_version": runtime.manifest.model_version,
            "data_kind": runtime.manifest.data_kind,
        }

    @application.get("/schema")
    def schema():
        return get_runtime().public_schema()

    @application.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(content=generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.post("/predict", response_model=PredictionResponse)
    def predict(payload: PredictionRequest, request: Request):
        runtime = get_runtime()
        try:
            frame = runtime.validate(payload.records)
        except InvalidRecords as exc:
            return JSONResponse(
                status_code=422,
                content={"error": "validation_error", "details": exc.errors, "request_id": request.state.request_id},
            )
        try:
            values = runtime.predict(frame)
        except Exception as exc:
            failures.inc()
            log_event("prediction_failed", request_id=request.state.request_id, error_type=type(exc).__name__)
            return JSONResponse(
                status_code=500, content={"error": "prediction_failed", "request_id": request.state.request_id}
            )
        predictions.labels(runtime.manifest.model_version).inc(len(values))
        return PredictionResponse(
            request_id=request.state.request_id,
            model_name=runtime.manifest.model_name,
            model_version=runtime.manifest.model_version,
            data_kind=runtime.manifest.data_kind,
            predictions=values,
        )

    return application


app = create_app()
