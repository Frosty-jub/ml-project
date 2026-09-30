"""Save demonstrable responses from the real running HTTP service."""

import argparse
import copy
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18005")
    parser.add_argument("--output", default="reports/http_evidence.json")
    parser.add_argument("--bundle-dir", type=Path, default=Path("artifacts/group-v1-joblib"))
    args = parser.parse_args()
    evidence = {"url": args.url, "checks": []}
    bundle_dir = args.bundle_dir
    bundle_metadata_path = bundle_dir / "metadata.json"
    if bundle_metadata_path.is_file() and (bundle_dir / "sample_request.json").is_file():
        bundle_metadata = json.loads(bundle_metadata_path.read_text("utf-8"))
        valid_payload = json.loads((bundle_dir / "sample_request.json").read_text("utf-8"))
        group_bundle = True
    else:
        bundle_metadata = {}
        valid_payload = json.loads((Path("examples") / "valid_request.json").read_text("utf-8"))
        group_bundle = False

    with httpx.Client(base_url=args.url, timeout=10, trust_env=False) as client:
        for path, expected in [("/health", 200), ("/schema", 200), ("/openapi.json", 200)]:
            response = client.get(path)
            passed = response.status_code == expected
            body = response.json() if path != "/openapi.json" else {"title": response.json()["info"]["title"]}
            if path == "/health" and group_bundle and response.status_code == 200:
                passed = passed and str(body.get("model_version")) == str(bundle_metadata["model_version"])
            evidence["checks"].append(
                {
                    "endpoint": path,
                    "status": response.status_code,
                    "expected": expected,
                    "passed": passed,
                    "body": body,
                }
            )

        invalid_payload = copy.deepcopy(valid_payload)
        invalid_payload["records"][0]["__unexpected_integration_field__"] = 0
        prediction_cases = [("valid_request", valid_payload, 200), ("invalid_request", invalid_payload, 422)]
        if group_bundle:
            missing_payload = copy.deepcopy(valid_payload)
            missing_payload["records"][0].pop(bundle_metadata["features"][0]["name"])
            prediction_cases.append(("missing_feature_request", missing_payload, 422))
        else:
            payload = json.loads((Path("examples") / "missing_value_request.json").read_text("utf-8"))
            prediction_cases.append(("missing_value_request", payload, 200))

        for name, payload, expected in prediction_cases:
            response = client.post("/predict", json=payload)
            evidence["checks"].append(
                {
                    "endpoint": "/predict",
                    "example": name,
                    "status": response.status_code,
                    "expected": expected,
                    "passed": response.status_code == expected,
                    "body": response.json(),
                }
            )
        response = client.get("/metrics")
        evidence["checks"].append(
            {
                "endpoint": "/metrics",
                "status": response.status_code,
                "expected": 200,
                "passed": response.status_code == 200 and "serving_request_duration_seconds_bucket" in response.text,
            }
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.with_suffix(".prom").write_text(response.text, encoding="utf-8")
    evidence["all_passed"] = all(check["passed"] for check in evidence["checks"])
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    raise SystemExit(0 if evidence["all_passed"] else 1)


if __name__ == "__main__":
    main()
