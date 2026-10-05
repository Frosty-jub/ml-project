"""Send prepared records after checking the loaded serving schema."""

import json
from urllib.request import Request, urlopen

import numpy as np


def send_prediction_request(url: str, payload: dict, names: list[str]) -> dict:
    base = url.rstrip("/")
    with urlopen(base + "/schema", timeout=30) as response:
        schema = json.load(response)
    if [row["name"] for row in schema["features"]] != names:
        raise ValueError("API feature names/order do not match the training manifest")
    if len(payload["records"]) > schema["max_batch_size"]:
        raise ValueError("Too many SKUs for the API batch limit; select fewer with --sku")
    request = Request(base + "/predict", data=json.dumps(payload, allow_nan=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if any(result.get(key) != schema.get(key) for key in ("model_name", "model_version", "data_kind")):
        raise ValueError("API model changed between schema check and prediction; retry with the intended version")
    values = np.asarray(result.get("predictions"), dtype=float)
    if values.shape != (len(payload["records"]),) or not np.isfinite(values).all():
        raise ValueError("API returned invalid predictions")
    return result
