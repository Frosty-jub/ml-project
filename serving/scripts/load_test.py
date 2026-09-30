"""Measure real HTTP latency/throughput with bounded concurrent clients."""

import argparse
import asyncio
import json
import platform
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np


async def benchmark(args):
    payload = json.loads(Path(args.payload).read_text("utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list) or not payload["records"]:
        raise ValueError("Payload must contain a nonempty records list")
    slo = json.loads(Path(args.slo).read_text("utf-8-sig"))
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    elapsed_times, successful_times, outcomes = [], [], Counter()
    errors = []
    receipts = []
    async with httpx.AsyncClient(
        base_url=args.url.rstrip("/"), limits=limits, timeout=args.timeout, trust_env=False
    ) as client:
        health = await client.get("/health")
        health.raise_for_status()
        model = health.json()
        def record_receipt(response):
            body = response.json()
            if (body.get('model_name') != model.get('model_name')
                    or str(body.get('model_version')) != str(model.get('model_version'))):
                raise ValueError('Model changed during load test')
            if args.receipts:
                receipts.append({'request_id': body['request_id'], 'predictions': body['predictions'],
                                 'model_name': body['model_name'], 'model_version': body['model_version']})

        for _ in range(args.warmup):
            warmup = await client.post("/predict", json=payload)
            warmup.raise_for_status()
            record_receipt(warmup)
        queue = asyncio.Queue()
        for number in range(args.requests):
            queue.put_nowait(number)

        async def worker():
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                started = time.perf_counter()
                status = "transport_error"
                ok = False
                try:
                    response = await client.post("/predict", json=payload)
                    status = str(response.status_code)
                    if response.status_code == 200:
                        values = response.json().get("predictions")
                        ok = (
                            isinstance(values, list)
                            and len(values) == len(payload["records"])
                            and all(isinstance(v, (int, float)) and np.isfinite(v) for v in values)
                        )
                        if ok:
                            record_receipt(response)
                    if not ok and len(errors) < 5:
                        errors.append({"status": status, "body": response.text[:300]})
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    ok = False
                    if len(errors) < 5:
                        errors.append({"status": status, "error": type(exc).__name__})
                duration = (time.perf_counter() - started) * 1000
                elapsed_times.append(duration)
                outcomes[status] += 1
                if ok:
                    successful_times.append(duration)
                queue.task_done()

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        wall = time.perf_counter() - started
    successful = len(successful_times)
    measured = {
        "p50_ms": float(np.percentile(successful_times, 50)) if successful else None,
        "p95_ms": float(np.percentile(successful_times, 95)) if successful else None,
        "mean_ms": statistics.mean(successful_times) if successful else None,
        "throughput_rps": successful / wall,
        "error_rate_percent": (args.requests - successful) / args.requests * 100,
    }
    checks = {
        "p50": measured["p50_ms"] is not None and measured["p50_ms"] <= slo["p50_ms_max"],
        "p95": measured["p95_ms"] is not None and measured["p95_ms"] <= slo["p95_ms_max"],
        "throughput": measured["throughput_rps"] >= slo["throughput_rps_min"],
        "errors": measured["error_rate_percent"] <= slo["error_rate_percent_max"],
        "single_record_workload": len(payload["records"]) == slo["records_per_request"],
    }
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "environment": args.environment,
        "client_platform": platform.platform(),
        "client_python": platform.python_version(),
        "model": model,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "warmup_excluded": args.warmup,
        "records_per_request": len(payload["records"]),
        "wall_seconds": wall,
        "successful_requests": successful,
        "status_counts": dict(outcomes),
        "measured": measured,
        "slo": slo,
        "checks": checks,
        "slo_passed": all(checks.values()),
        "all_request_p95_ms": float(np.percentile(elapsed_times, 95)),
        "error_samples": errors,
        "limitation": "Short client-observed load test; not proof of long-term availability or performance on other machines.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.receipts:
        Path(args.receipts).write_text(json.dumps(receipts, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["slo_passed"] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18005")
    parser.add_argument("--payload", default="examples/valid_request.json")
    parser.add_argument("--slo", default="slo.json")
    parser.add_argument("--output", default="reports/load_test.json")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--receipts", help="Save request IDs and predictions for exact event reconciliation")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error("requests/concurrency/timeout must be positive and warmup must be >= 0")
    raise SystemExit(asyncio.run(benchmark(args)))


if __name__ == "__main__":
    main()
