"""Airflow task entrypoints; nonzero exits stop downstream tasks.

Shared artifacts require one active run and no concurrent manual training.
Run state is keyed by Airflow run_id, never by a hard-coded model version.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import signal
import socket
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from . import registry


def state_path() -> Path:
    run_id = os.environ.get("PIPELINE_RUN_ID")
    if not run_id:
        raise ValueError("PIPELINE_RUN_ID is required")
    key = hashlib.sha256(run_id.encode()).hexdigest()[:24]
    return registry.ROOT / "artifacts" / "orchestration" / f"{key}.json"


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(path)


def load_state() -> dict:
    return json.loads(state_path().read_text(encoding="utf-8"))


def require_pass(result: dict) -> None:
    if not result.get("passed"):
        raise ValueError(f"Quality gate failed: {result}")


def context():
    mlflow = registry.configure_mlflow()
    name = registry.read_json(registry.POLICY_PATH)["registered_model_name"]
    return mlflow.MlflowClient(), name


def stop_process(process) -> None:
    """Stop MLflow and its Uvicorn children so the next task can reuse the port."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


@contextmanager
def temporary_server(version: str):
    """Benchmark a candidate on an isolated port, never the production port."""
    _, name = context()
    # A fresh port prevents a previous server still shutting down from answering.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([
        sys.executable, "-m", "mlflow", "models", "serve", "-m", f"models:/{name}/{version}",
        "--host", "127.0.0.1", "-p", str(port), "--env-manager", "local",
    ], cwd=registry.ROOT, start_new_session=(os.name == "posix"))
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Candidate serving process exited")
            try:
                with urllib.request.urlopen(url + "/ping", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise TimeoutError("Candidate server did not become ready")
        yield url
    finally:
        stop_process(process)


def benchmark(version: str) -> dict:
    with temporary_server(version) as url:
        result = registry.benchmark_version(version, url)
    # Registry CLI prints failed serving gates but does not itself exit nonzero.
    require_pass(result["gate"])
    return result


def register() -> None:
    gate, _, _ = registry.check_candidate()
    require_pass(gate)
    client, name = context()
    before = {v.version for v in client.search_model_versions(f"name='{name}'")}
    if registry.register_candidate() != 0:
        raise ValueError("Registration gate rejected candidate")
    created = [v for v in client.search_model_versions(f"name='{name}'")
               if v.version not in before and v.tags.get("source_model_sha256") == gate["model_sha256"]]
    if len(created) != 1:
        raise RuntimeError("Cannot identify this run's registered version")
    version = str(created[0].version)
    client.set_model_version_tag(name, version, "airflow_run_id", os.environ["PIPELINE_RUN_ID"])
    save_state({"version": version, "model_sha256": gate["model_sha256"],
                "aliases_before": registry.alias_version(client.get_registered_model(name))})


def restore_aliases(client, name: str, aliases: dict) -> None:
    current = registry.alias_version(client.get_registered_model(name))
    for alias in ("production", "champion", "previous"):
        if alias in aliases:
            client.set_registered_model_alias(name, alias, aliases[alias])
        elif alias in current:
            client.delete_registered_model_alias(name, alias)


def release() -> None:
    state = load_state()
    client, name = context()
    aliases = registry.alias_version(client.get_registered_model(name))
    if aliases != state["aliases_before"]:
        raise ValueError("Aliases changed during run; refusing concurrent promotion")
    url = os.environ.get("PRODUCTION_URL", "http://serving:5001")
    try:
        registry.promote(state["version"])
        deadline = time.monotonic() + 120
        while True:
            try:
                # Supervisor reports the exact version whose server is healthy.
                with urllib.request.urlopen(url.replace(":5001", ":5002") + "/health", timeout=3) as response:
                    health = json.load(response)
                if str(health.get("version")) == state["version"]:
                    break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Production did not load promoted version")
            time.sleep(2)
        result = registry.benchmark_version(state["version"], url)
        require_pass(result["gate"])
        state["production_benchmark"] = result
        state["released"] = True
        save_state(state)
    except Exception:
        restore_aliases(client, name, aliases)
        # The serving supervisor reloads/restops on this restored alias too.
        state["released"] = False
        state["aliases_restored"] = aliases
        save_state(state)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["gate", "register", "benchmark-candidate", "benchmark-previous", "release"])
    step = parser.parse_args().step
    if step == "gate":
        result, _, _ = registry.check_candidate()
        print(json.dumps(result, indent=2))
        require_pass(result)
    elif step == "register":
        register()
    elif step == "release":
        release()
    else:
        state = load_state()
        version = state["version"] if step == "benchmark-candidate" else state["aliases_before"].get("production")
        if version:
            state[step] = benchmark(version)
            save_state(state)
        else:
            print("First deployment: no previous production version to benchmark")


if __name__ == "__main__":
    main()
