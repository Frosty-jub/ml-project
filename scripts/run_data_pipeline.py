"""Run the complete data pipeline from the UCI archive to model-ready splits."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEPS = ["download_data.py", "prepare_data.py", "validate_data.py", "build_features.py"]


def main() -> None:
    for step in STEPS:
        print(f"\n=== {step} ===", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / step)], cwd=ROOT, check=True)
    print("\nData pipeline เสร็จครบทุกขั้น")


if __name__ == "__main__":
    main()
