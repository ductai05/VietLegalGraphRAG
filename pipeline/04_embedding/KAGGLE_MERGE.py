"""Kaggle launcher: repair missing member rows and build compact FAISS indexes.

The five member datasets remain read-only inputs. This launcher deliberately
does not materialize a second 30 GB merged vector directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# === Configuration ===
ALLOW_CPU_REPAIR = False
FAISS_FACTORY = "IVF4096,PQ64x8"
FAISS_TRAIN_SIZE = "200000"
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
CHUNKS = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet"
METADATA = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet"
REPAIR_SHARDS = f"{WORK}/data/repair_shards"
REPAIR_WORK = f"{WORK}/data/repair_work"
FAISS_OUTPUT = f"{WORK}/faiss_members"

SEARCH_ROOTS = [
    "/kaggle/input/datasets/brdh7940/member-1",
    "/kaggle/input/datasets/dinhducanhkhoa/embedding2",
    "/kaggle/input/datasets/cieldt/vietlegalgraphrag-legalembedding-member3",
    "/kaggle/input/datasets/nguyentrantrungkien/embedding4",
    "/kaggle/input/datasets/nguynlhongtrung/member-5",
    "/kaggle/working",
]
# =====================


def search_root_args() -> list[str]:
    return [
        item
        for root in SEARCH_ROOTS
        if Path(root).exists()
        for item in ("--search-root", root)
    ]


def ensure_canonical_payload() -> tuple[Path, bool]:
    for root in SEARCH_ROOTS:
        path = Path(root)
        if path.exists():
            candidates = list(path.rglob("embed_payload_v0.1.parquet"))
            if candidates:
                return max(candidates, key=lambda item: item.stat().st_size), False
    output = Path(WORK) / "data"
    subprocess.run(
        [
            "python",
            "prepare_embedding_data.py",
            "--chunks",
            CHUNKS,
            "--metadata",
            METADATA,
            "--output-dir",
            str(output),
            "--version",
            "v0.1",
            "--chunker-version",
            "v0.1",
        ],
        check=True,
    )
    return output / "embed_payload_v0.1.parquet", True


def main() -> None:
    os.chdir(PIPELINE)
    subprocess.run(["pip", "install", "-q", "-r", "requirements.txt"], check=True)

    roots = search_root_args()
    canonical_payload, generated_payload = ensure_canonical_payload()
    repair_cmd = [
        "python",
        "repair_missing_shards.py",
        *roots,
        "--canonical-payload",
        str(canonical_payload),
        "--output-dir",
        REPAIR_SHARDS,
        "--work-dir",
        REPAIR_WORK,
    ]
    if ALLOW_CPU_REPAIR:
        repair_cmd.append("--allow-cpu")
    print("=== Step 1: verify members, accept duplicates, encode only missing chunks ===")
    subprocess.run(repair_cmd, check=True)

    print("\n=== Step 2: build compact deduplicated per-member FAISS indexes ===")
    subprocess.run(
        [
            "python",
            "build_faiss_members.py",
            *roots,
            "--repair-dir",
            REPAIR_SHARDS,
            "--output-dir",
            FAISS_OUTPUT,
            "--factory",
            FAISS_FACTORY,
            "--train-size",
            FAISS_TRAIN_SIZE,
        ],
        check=True,
    )
    shutil.rmtree(REPAIR_WORK, ignore_errors=True)
    if generated_payload:
        canonical_payload.unlink(missing_ok=True)
        for name in ("prepare_manifest.json", "table_repair_candidates.parquet", "prepare.log"):
            (canonical_payload.parent / name).unlink(missing_ok=True)
    print(f"\nQueryable FAISS artifact: {FAISS_OUTPUT}")
    print(
        "Publish that directory as the Kaggle output dataset. "
        "The five original member datasets remain its required inputs."
    )
    print(
        f"Smoke test: python dense_retrieval.py --faiss-dir {FAISS_OUTPUT} "
        '--chunks <chunks.parquet> --query "Điều kiện cấp giấy phép xây dựng là gì?"'
    )


if __name__ == "__main__":
    main()
