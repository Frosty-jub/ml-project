"""Save demonstrable responses from the real running HTTP service."""

import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18005")
    parser.add_argument("--output", default="reports/http_evidence.json")
    args = parser.parse_args()
    evidence = {"url": args.url, "checks": []}
    with httpx.Client(base_url=args.url, timeout=10, trust_env=False) as client:
        for path, expected in [("/health", 200), ("/schema", 200), ("/openapi.json", 200)]:
            response = client.get(path)
            evidence["checks"].append(
                {
                    "endpoint": path,
                    "status": response.status_code,
                    "expected": expected,
                    "passed": response.status_code == expected,
                    "body": response.json() if path != "/openapi.json" else {"title": response.json()["info"]["title"]},
                }
            )
        for name, expected in [
            ("valid_request.json", 200),
            ("missing_value_request.json", 200),
            ("invalid_request.json", 422),
        ]:
            payload = json.loads((Path("examples") / name).read_text("utf-8"))
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
