"""Kaggle single-cell runner for only the Tokenization step."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def find_sparse_dir() -> Path:
    candidates = [
        Path("/kaggle/input/vietlegalgraphrag-source/VietLegalGraphRAG/pipeline/05_sparse_retrieval"),
    ]
    for path in candidates:
        if path.exists():
            return path
    input_dir = Path("/kaggle/input")
    if input_dir.exists():
        matches = sorted(input_dir.glob("**/VietLegalGraphRAG/pipeline/05_sparse_retrieval"))
        if matches:
            return matches[0]
    return candidates[0]


def find_chunking_file(name: str) -> Path:
    candidates = [
        Path(f"/kaggle/input/vietnamese-legal-documents-cleaned/legal_chunking_dataset/{name}"),
        Path(f"/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/{name}"),
    ]
    for path in candidates:
        if path.exists():
            return path
    input_dir = Path("/kaggle/input")
    if input_dir.exists():
        matches = sorted(input_dir.glob(f"*/legal_chunking_dataset/{name}"))
        if matches:
            return matches[0]
        matches = sorted(input_dir.glob(f"**/{name}"))
        for path in matches:
            if path.parent.name == "legal_chunking_dataset":
                return path
    return candidates[0]


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

SPARSE_DIR = Path(os.environ.get("SPARSE_DIR", str(find_sparse_dir())))
CHUNKS_PATH = Path(os.environ.get("CHUNKS_PATH", str(find_chunking_file("chunks.parquet"))))
METADATA_PATH = Path(os.environ.get("METADATA_PATH", str(find_chunking_file("metadata.parquet"))))
WORK_DIR = Path(os.environ.get("SPARSE_WORK_DIR", "/kaggle/working/legal_sparse"))

# Read splitting configurations
NUM_SPLITS = int(os.environ.get("NUM_SPLITS", "3"))
SPLIT_INDEX = int(os.environ.get("SPLIT_INDEX", "1"))
EXPORT_NDJSON = os.environ.get("EXPORT_NDJSON", "0") == "1"


def run_step(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], cwd=SPARSE_DIR, check=True)


def require_path(name: str, path: Path, env_var: str | None = None) -> None:
    if not path.exists():
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
