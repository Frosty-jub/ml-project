"""Local-demo supervisor: reload MLflow Serving when production alias changes."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .orchestration import context, stop_process
from .registry import ROOT


def main():
    status = {"version": None}
    stop = threading.Event()
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                with urllib.request.urlopen("http://127.0.0.1:5001/ping", timeout=1) as response:
                    ready = response.status == 200 and status["version"] is not None
            except OSError:
                ready = False
            self.send_response(200 if ready else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ready": ready, **status}).encode())
    health = ThreadingHTTPServer(("0.0.0.0", 5002), Health)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    process = None
    version = None
    def terminate():
        if process is not None:
            stop_process(process)
    try:
        while not stop.is_set():
            try:
                client, name = context()
                aliases = client.get_registered_model(name).aliases
                desired = str(aliases["production"]) if "production" in aliases else None
            except Exception as exc:
                print(f"Waiting for Registry: {exc}", flush=True)
                stop.wait(5)
                continue
            if desired != version or (process is not None and process.poll() is not None):
                status["version"] = None
                terminate()
                process = None
                version = desired
                if version:
                    process = subprocess.Popen([sys.executable, "-m", "mlflow", "models", "serve",
                        "-m", f"models:/{name}/{version}", "--host", "0.0.0.0", "-p", "5001",
                        "--env-manager", "local"], cwd=ROOT, start_new_session=(os.name == "posix"))
                    status["version"] = version
            stop.wait(3)
    finally:
        terminate()
        health.shutdown()


if __name__ == "__main__":
    main()
