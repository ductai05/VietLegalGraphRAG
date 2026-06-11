"""Kaggle single-cell runner for only the Tokenization step."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

SPARSE_DIR = Path(os.environ["SPARSE_DIR"]) if "SPARSE_DIR" in os.environ else None
CHUNKS_PATH = Path(os.environ["CHUNKS_PATH"]) if "CHUNKS_PATH" in os.environ else None
METADATA_PATH = Path(os.environ["METADATA_PATH"]) if "METADATA_PATH" in os.environ else None
WORK_DIR = Path(os.environ.get("SPARSE_WORK_DIR", "/kaggle/working/legal_sparse"))

# Read splitting configurations
NUM_SPLITS = int(os.environ.get("NUM_SPLITS", "3"))
SPLIT_INDEX = int(os.environ.get("SPLIT_INDEX", "1"))
EXPORT_NDJSON = os.environ.get("EXPORT_NDJSON", "0") == "1"


def run_step(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], cwd=SPARSE_DIR, check=True)


def require_path(name: str, path: Path | None, env_var: str | None = None) -> None:
    if path is None or not path.exists():
        hint = f" Override this path with the {env_var} environment variable." if env_var else ""
        raise FileNotFoundError(f"{name} not found: {path}.{hint}")


def main() -> None:
    require_path("SPARSE_DIR", SPARSE_DIR, "SPARSE_DIR")
    require_path("CHUNKS_PATH", CHUNKS_PATH, "CHUNKS_PATH")
    require_path("METADATA_PATH", METADATA_PATH, "METADATA_PATH")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"--- Running Tokenization Only ---")
    print(f"Split {SPLIT_INDEX} of {NUM_SPLITS}")
    
    data_dir = WORK_DIR / "data"
    
    args = [
        "scripts/prepare_sparse_data.py",
        "--chunks", str(CHUNKS_PATH),
        "--metadata", str(METADATA_PATH),
        "--output-dir", str(data_dir),
        "--version", "v0.1",
        "--num-splits", str(NUM_SPLITS),
        "--split-index", str(SPLIT_INDEX),
    ]
    if EXPORT_NDJSON:
        args.append("--export-ndjson")
        
    run_step(args)
    
    print(f"Tokenization split {SPLIT_INDEX}/{NUM_SPLITS} completed successfully.")
    print(f"Output files can be found at: {data_dir}")


if __name__ == "__main__":
    main()
