"""Kaggle launcher — verify + merge 5 member embedding outputs, then build Qdrant.

Hướng dẫn chạy
--------------
1. Notebook Kaggle: bật GPU để encode lại riêng các chunk bị thiếu.
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
   - giữ lại embedding đầu tiên cho mỗi `chunk_id`, bỏ bản trùng
   - encode riêng các `chunk_id` còn thiếu
   - ghi bộ shard hoàn chỉnh vào `/kaggle/working/legal_embedding/data/shards`
   - (tuỳ chọn) build Qdrant local nếu `BUILD_QDRANT = True`

Mapping member:
  1 = brdh7940
  2 = dinhducanhkhoa
  3 = cieldt (dataset input)
  4 = nguyentrantrungkien
  5 = nguynlhongtrung
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from member_shards_utils import _load_manifests, discover_member_roots

# === Cấu hình ===
BUILD_QDRANT = False  # True chỉ khi còn đủ disk (~20GB working thường KHÔNG đủ full Qdrant)
ALLOW_CPU_REPAIR = False  # True chỉ khi chấp nhận encode missing chunks rất chậm trên CPU
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
MERGED_SHARDS = f"{WORK}/data/shards"
QDRANT_STORAGE = f"{WORK}/qdrant/qdrant_storage"
REPAIR_WORK = f"{WORK}/data/repair_work"

SEARCH_ROOTS = [
    "/kaggle/input/datasets/brdh7940/member-1",
    "/kaggle/input/datasets/dinhducanhkhoa/embedding2",
    "/kaggle/input/datasets/cieldt/vietlegalgraphrag-legalembedding-member3",
    "/kaggle/input/datasets/nguyentrantrungkien/embedding4",
    "/kaggle/input/datasets/nguynlhongtrung/member-5",
    "/kaggle/working",  # fallback nếu ai đó tải thẳng vào working
]
# =================




def main() -> None:
    os.chdir(PIPELINE)
    subprocess.run(["pip", "install", "-q", "-r", "requirements.txt"], check=True)

    roots = [str(Path(path)) for path in SEARCH_ROOTS]
    member_roots = discover_member_roots([Path(path) for path in SEARCH_ROOTS])
    canonical_payload = member_roots[1].parent / "embed_payload_v0.1.parquet"
    if not canonical_payload.exists():
        raise FileNotFoundError(f"Canonical payload is missing: {canonical_payload}")
    canonical_ids = {
        chunk_id
        for batch in pq.ParquetFile(canonical_payload).iter_batches(
            batch_size=100_000, columns=["chunk_id"]
        )
        for chunk_id in batch.column(0).to_pylist()
    }
    manifests = _load_manifests(member_roots)
    seen_ids: set[str] = set()
    for entries in manifests.values():
        for gpu_dir, manifest in entries:
            for info in manifest["shards"].values():
                payload_path = gpu_dir / info["payload"]
                actual_chunk_ids = pq.read_table(payload_path, columns=["chunk_id"]).column(
                    "chunk_id"
                ).to_pylist()
                seen_ids.update(actual_chunk_ids)
    missing_ids = canonical_ids - seen_ids
    print(
        f"Existing outputs: unique={len(seen_ids):,} "
        f"missing_to_encode={len(missing_ids):,}"
    )
    if missing_ids:
        print(f"Encoding missing chunks now: {len(missing_ids):,}")

    repair_cmd = [
        "python",
        "repair_member_shards.py",
        *[item for root in roots for item in ("--search-root", root)],
        "--output-dir",
        MERGED_SHARDS,
        "--work-dir",
        REPAIR_WORK,
    ]
    if ALLOW_CPU_REPAIR:
        repair_cmd.append("--allow-cpu")
    print("=== Step 1: deduplicate existing outputs + encode missing chunks ===")
    subprocess.run(repair_cmd, check=True)

    manifest = Path(MERGED_SHARDS) / "manifest.json"
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    missing_encoded = manifest_data.get("repair", {}).get("missing_encoded")
    vector_count = len(list(Path(MERGED_SHARDS).glob("vectors_*.npy")))
    print(f"\nMerge complete: {manifest}")
    if missing_encoded is not None:
        print(f"Missing chunks encoded: {missing_encoded:,}")
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

    print("\n=== Step 2: build Qdrant (local embedded) ===")
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
