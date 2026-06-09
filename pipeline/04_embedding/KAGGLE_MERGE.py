"""Kaggle launcher — verify + merge 5 member embedding outputs, then build Qdrant.

Hướng dẫn chạy
--------------
1. Notebook Kaggle: bật GPU (không bắt buộc cho merge), bật Internet nếu build Qdrant.
2. Add dataset `04-embedding` (thư mục pipeline này).
3. Gather output từ 5 member — **mỗi kernel tải về thư mục riêng** để tránh ghi đè:

   !kaggle kernels output brdh7940/4-embedding -p /kaggle/working/member1
   !kaggle kernels output dinhducanhkhoa/chunking-2 -p /kaggle/working/member2
   !kaggle kernels output nguyentrantrungkien/member4 -p /kaggle/working/member4
   !kaggle kernels output nguynlhongtrung/embedding -p /kaggle/working/member5

   `kaggle kernels output` không có tuỳ chọn skip file — output cũ có thể kèm
   `legal_embedding/.cache/` (~1.2 GB/model). Sau khi tải, chạy:
   !rm -rf /kaggle/working/member*/legal_embedding/.cache
   hoặc để KAGGLE_MERGE tự dọn (bước 0).

4. Add dataset member 3 (ví dụ cieldt):
   `/kaggle/input/datasets/cieldt/vietlegalgraphrag-legalembedding-member3`

5. Chạy file này. Nó sẽ:
   - verify đủ 5 thư mục `shards_member_{1..5}`
   - merge vào `/kaggle/working/legal_embedding/data/shards`
   - (tuỳ chọn) build Qdrant local nếu `BUILD_QDRANT = True`

Mapping member:
  1 = brdh7940
  2 = dinhducanhkhoa
  3 = cieldt (dataset input)
  4 = nguyentrantrungkien
  5 = nguynlhongtrung
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# === Cấu hình ===
BUILD_QDRANT = False  # True chỉ khi còn đủ disk (~20GB working thường KHÔNG đủ full Qdrant)
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
MERGED_SHARDS = f"{WORK}/data/shards"
QDRANT_STORAGE = f"{WORK}/qdrant/qdrant_storage"

SEARCH_ROOTS = [
    "/kaggle/working/member1",
    "/kaggle/working/member2",
    "/kaggle/input/datasets/cieldt/vietlegalgraphrag-legalembedding-member3",
    "/kaggle/working/member4",
    "/kaggle/working/member5",
    "/kaggle/working",  # fallback nếu ai đó tải thẳng vào working
]
# =================


def prune_hf_cache(search_roots: list[str]) -> None:
    """Remove HuggingFace model cache accidentally saved under kernel output."""
    removed: list[str] = []
    for root in search_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for legal_root in root_path.rglob("legal_embedding"):
            cache_dir = legal_root / ".cache"
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir)
                removed.append(str(cache_dir))
    if removed:
        print("Removed HuggingFace cache from downloaded outputs:")
        for path in removed:
            print(f"  {path}")
    else:
        print("No legal_embedding/.cache directories found under member roots.")


def main() -> None:
    os.chdir(PIPELINE)
    subprocess.run(["pip", "install", "-q", "-r", "requirements.txt"], check=True)

    roots = [str(Path(path)) for path in SEARCH_ROOTS]
    print("=== Step 0: prune accidental .cache from kernel outputs ===")
    prune_hf_cache(roots)

    verify_cmd = [
        "python",
        "verify_member_shards.py",
        *[item for root in roots for item in ("--search-root", root)],
    ]
    print("=== Step 1: verify member shards ===")
    subprocess.run(verify_cmd, check=True)

    merge_cmd = [
        "python",
        "merge_member_shards.py",
        *[item for root in roots for item in ("--search-root", root)],
        "--output-dir",
        MERGED_SHARDS,
    ]
    print("\n=== Step 2: merge shards ===")
    subprocess.run(merge_cmd, check=True)

    manifest = Path(MERGED_SHARDS) / "manifest.json"
    vector_count = len(list(Path(MERGED_SHARDS).glob("vectors_shard_*.npy")))
    print(f"\nMerge complete: {manifest}")
    print(f"Vector shard files: {vector_count}")

    if not BUILD_QDRANT:
        print(
            "\nBUILD_QDRANT=False — dừng tại merged shards. "
            "Build Qdrant trên máy có đủ disk hoặc Qdrant server:"
        )
        print(
            f"  python build_qdrant.py --shards-dir {MERGED_SHARDS} "
            f"--url http://localhost:6333 --recreate"
        )
        return

    print("\n=== Step 3: build Qdrant (local embedded) ===")
    subprocess.run(
        [
            "python",
            "build_qdrant.py",
            "--shards-dir",
            MERGED_SHARDS,
            "--storage-dir",
            QDRANT_STORAGE,
            "--recreate",
        ],
        check=True,
    )
    print(f"Qdrant storage: {QDRANT_STORAGE}")


if __name__ == "__main__":
    main()
