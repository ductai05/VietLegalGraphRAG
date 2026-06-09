"""Kaggle launcher — chia embedding corpus cho 5 thành viên.

Hướng dẫn chạy
--------------
1. Notebook Kaggle: bật GPU (2× T4), bật Internet.
2. Add dataset:
   - `vietnamese-legal-documents-cleaned` (chunks + metadata)
   - `04-embedding` (thư mục pipeline này)
3. Sửa `MEMBER_ID` (1–5) cho đúng phần việc của bạn.
4. Chạy toàn bộ file (hoặc `%run KAGGLE_MEMBER.py`).
5. Không đổi `BATCH_SIZE`, `TOKEN_BUDGET`, `MAX_LENGTH`, `SHARD_SIZE`.
6. Sau khi xong: publish output
   `/kaggle/working/legal_embedding/data/shards_member_{MEMBER_ID}/`
   (gồm `gpu0/`, `gpu1/`, log) lên Kaggle Dataset.
   Không publish `.cache/` — model cache nằm ngoài `/kaggle/working`.
7. Gửi link dataset cho người merge shard + build Qdrant.

Phân công shard (tự tính theo số row thực tế)
---------------------------------------------
MEMBER_ID=1 → shard đầu corpus
MEMBER_ID=2 → shard tiếp theo
...
MEMBER_ID=5 → shard cuối corpus

Mỗi thành viên chỉ encode dải shard của mình; tên file giữ index global
(`vectors_shard_00112.npy`). Hai GPU ghi vào hai thư mục con để tránh tranh manifest.

Resume: chạy lại cùng `MEMBER_ID` — shard đã `done` trong manifest sẽ bị bỏ qua.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pyarrow.parquet as pq
from tqdm.auto import tqdm

# === CHỈ SỬA DÒNG NÀY ===
MEMBER_ID = 1  # 1 | 2 | 3 | 4 | 5
# ========================

NUM_MEMBERS = 5
SHARD_SIZE = 10_000

CHUNKS = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet"
METADATA = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet"
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
# Outside /kaggle/working so kernel output / dataset publish stays small (~GB not +1.2GB).
HF_CACHE = "/tmp/vnlegal_hf_cache"

BATCH_SIZE = "128"
TOKEN_BUDGET = "49152"
MAX_LENGTH = "1024"
ATTN_IMPL = "sdpa"
WORKER_STAGGER_S = 45
PYTORCH_ALLOC = "expandable_segments:True"


def member_shard_range(member_id: int, total_shards: int, num_members: int) -> tuple[int, int]:
    if not 1 <= member_id <= num_members:
        raise ValueError(f"MEMBER_ID must be 1..{num_members}, got {member_id}")
    base = total_shards // num_members
    extra = total_shards % num_members
    sizes = [base + (1 if index < extra else 0) for index in range(num_members)]
    start = sum(sizes[: member_id - 1])
    stop = start + sizes[member_id - 1]
    return start, stop


def gpu_jobs(shard_start: int, shard_stop: int) -> list[tuple[int, int, int]]:
    count = shard_stop - shard_start
    if count <= 0:
        raise ValueError(f"Empty shard range [{shard_start}, {shard_stop})")
    mid = shard_start + (count + 1) // 2
    jobs = [(0, shard_start, mid)]
    if mid < shard_stop:
        jobs.append((1, mid, shard_stop))
    return jobs


def tail_text(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return "(log missing)"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not content:
        return "(log empty)"
    return "\n".join(content[-lines:])


def check_gpus() -> None:
    subprocess.run(
        [
            "python",
            "-c",
            (
                "import torch; "
                "assert torch.cuda.is_available() and torch.cuda.device_count() == 2; "
                "assert all(torch.cuda.get_device_capability(i) == (7, 5) for i in range(2)); "
                "[print(i, torch.cuda.get_device_name(i)) for i in range(2)]"
            ),
        ],
        check=True,
    )


def fail_worker(label: str, log_path: Path, returncode: int) -> None:
    raise RuntimeError(
        f"{label} exited with code {returncode}.\n"
        f"Last lines of {log_path}:\n{tail_text(log_path)}"
    )


if MEMBER_ID < 1 or MEMBER_ID > NUM_MEMBERS:
    raise ValueError(f"Set MEMBER_ID to an integer from 1 to {NUM_MEMBERS}")

check_gpus()

os.chdir(PIPELINE)
subprocess.run(["pip", "install", "-q", "-r", "requirements.txt"], check=True)

subprocess.run(
    [
        "python",
        "prepare_embedding_data.py",
        "--chunks",
        CHUNKS,
        "--metadata",
        METADATA,
        "--output-dir",
        f"{WORK}/data",
        "--version",
        "v0.1",
        "--chunker-version",
        "v0.1",
    ],
    check=True,
)

payload = f"{WORK}/data/embed_payload_v0.1.parquet"
total_rows = pq.ParquetFile(payload).metadata.num_rows
total_shards = (total_rows + SHARD_SIZE - 1) // SHARD_SIZE
shard_start, shard_stop = member_shard_range(MEMBER_ID, total_shards, NUM_MEMBERS)
member_shards = shard_stop - shard_start

print(
    f"member={MEMBER_ID}/{NUM_MEMBERS} "
    f"rows={total_rows:,} total_shards={total_shards} "
    f"range=[{shard_start}, {shard_stop}) member_shards={member_shards}"
)

member_root = Path(f"{WORK}/data/shards_member_{MEMBER_ID}")
member_root.mkdir(parents=True, exist_ok=True)

base = [
    "python",
    "embed_shards.py",
    "--payload",
    payload,
    "--batch-size",
    BATCH_SIZE,
    "--token-budget",
    TOKEN_BUDGET,
    "--max-length",
    MAX_LENGTH,
    "--shard-size",
    str(SHARD_SIZE),
    "--attn-implementation",
    ATTN_IMPL,
    "--cache-dir",
    HF_CACHE,
    "--device",
    "cuda:0",
]

processes: list[tuple[subprocess.Popen, object, Path, Path]] = []
for gpu_index, start, stop in gpu_jobs(shard_start, shard_stop):
    if gpu_index == 1:
        time.sleep(WORKER_STAGGER_S)
    output = member_root / f"gpu{gpu_index}"
    output.mkdir(parents=True, exist_ok=True)
    log_path = member_root / f"gpu{gpu_index}.log"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["PYTORCH_CUDA_ALLOC_CONF"] = PYTORCH_ALLOC
    log = log_path.open("w", encoding="utf-8")
    print(f"launch gpu={gpu_index} shards=[{start}, {stop}) -> {output}")
    process = subprocess.Popen(
        base
        + [
            "--output-dir",
            str(output),
            "--shard-start",
            str(start),
            "--shard-stop",
            str(stop),
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    processes.append((process, log, output, log_path))

progress = tqdm(total=member_shards, desc=f"member {MEMBER_ID} embedding", unit="shard")
last_completed = 0
while any(process.poll() is None for process, _, _, _ in processes):
    for gpu_index, (process, log, _, log_path) in enumerate(processes):
        if process.poll() is not None and process.returncode != 0:
            log.flush()
            fail_worker(f"GPU {gpu_index} worker", log_path, process.returncode)

    completed = sum(
        len(list(output.glob("vectors_shard_*.npy")))
        for _, _, output, _ in processes
    )
    progress.update(max(0, completed - last_completed))
    last_completed = completed
    time.sleep(10)

completed = sum(
    len(list(output.glob("vectors_shard_*.npy")))
    for _, _, output, _ in processes
)
progress.update(max(0, completed - last_completed))
progress.close()

for gpu_index, (process, log, output, log_path) in enumerate(processes):
    returncode = process.wait()
    log.close()
    if returncode != 0:
        fail_worker(f"GPU {gpu_index} worker", log_path, returncode)
    shard_count = len(list(output.glob("vectors_shard_*.npy")))
    print(f"gpu={gpu_index} shards_done={shard_count} log={log_path}")

expected_rows = min(shard_stop * SHARD_SIZE, total_rows) - shard_start * SHARD_SIZE
print(
    f"Member {MEMBER_ID} complete. "
    f"Output: {member_root} (~{expected_rows:,} rows, shards [{shard_start}, {shard_stop}))"
)

legacy_cache = Path(WORK) / ".cache"
if legacy_cache.exists():
    shutil.rmtree(legacy_cache)
    print(f"Removed legacy model cache from output tree: {legacy_cache}")
