"""Save installed versions, Docker status and representative service logs."""

import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def capture(arguments):
    result = subprocess.run(
        arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False
    )
    return {"command": arguments, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main():
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    packages = {item.metadata["Name"]: item.version for item in importlib.metadata.distributions()}
    status = capture(["docker", "compose", "ps", "--format", "json"])
    logs = capture(["docker", "compose", "logs", "--no-color", "--tail", "30", "serving"])
    server_code = "import sys,platform,json,importlib.metadata as m; print(json.dumps({'python':sys.version,'platform':platform.platform(),'versions':{p:m.version(p) for p in ['fastapi','uvicorn','scikit-learn','pandas','numpy','prometheus-client']}}))"
    server = capture(["docker", "compose", "exec", "-T", "serving", "python", "-c", server_code])
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "client_python": sys.version,
        "client_platform": platform.platform(),
        "client_packages": packages,
        "docker_status": status,
        "server_environment": server,
    }
    (reports / "environment.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (reports / "docker_logs.txt").write_text(logs["stdout"] + logs["stderr"], encoding="utf-8")
    print(
        json.dumps(
            {
                "environment_saved": str(reports / "environment.json"),
                "logs_saved": str(reports / "docker_logs.txt"),
                "docker_status_exit_code": status["exit_code"],
                "server_environment_exit_code": server["exit_code"],
            }
        )
    )
    raise SystemExit(0 if status["exit_code"] == server["exit_code"] == logs["exit_code"] == 0 else 1)


if __name__ == "__main__":
    main()
