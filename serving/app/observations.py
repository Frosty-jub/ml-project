"""Append validated inference observations for delayed-label monitoring."""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()


def record_predictions(path: str, request_id: str, manifest, records: list[dict], predictions: list[float]) -> None:
    if len(records) != len(predictions):
        raise ValueError("Observation row count does not match predictions")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        json.dumps({
            "timestamp": timestamp, "request_id": request_id, "row_index": index,
            "model_name": manifest.model_name, "model_version": manifest.model_version,
            "data_kind": manifest.data_kind, "features": row, "prediction": prediction,
        }, ensure_ascii=False, allow_nan=False) + "\n"
        for index, (row, prediction) in enumerate(zip(records, predictions))
    ]
    # One write per request prevents rows of concurrent batches from interleaving.
    with _LOCK:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, "".join(lines).encode("utf-8"))
        finally:
            os.close(fd)
