import os
import subprocess
import time
from pathlib import Path

import pyarrow.parquet as pq
from tqdm.auto import tqdm

CHUNKS = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet"
METADATA = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet"
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
# T4 16GB: model ~1.2GB + activations. At max_length=1024, ~48 rows/batch fits (~3GB attn).
# token-budget=49152 (=48×1024). OOM auto-split in encode_texts handles edge cases.
BATCH_SIZE = "128"
TOKEN_BUDGET = "49152"
MAX_LENGTH = "1024"
ATTN_IMPL = "sdpa"
WORKER_STAGGER_S = 45
PYTORCH_ALLOC = "expandable_segments:True"


def tail_text(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return "(log missing)"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not content:
        return "(log empty)"
    return "\n".join(content[-lines:])


def check_gpus() -> None:
    """Validate GPUs in a throwaway subprocess.

    The parent notebook/script must NOT import torch before spawning workers.
    Importing torch and touching CUDA here would hold GPU-0 context and block
    the worker launched with CUDA_VISIBLE_DEVICES=0.
    """
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
total_shards = (total_rows + 9_999) // 10_000
split = (total_shards + 1) // 2
print(f"rows={total_rows:,} shards={total_shards} split={split}")

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
    "10000",
    "--attn-implementation",
    ATTN_IMPL,
    "--cache-dir",
    f"{WORK}/.cache",
    "--device",
    "cuda:0",
]

processes: list[tuple[subprocess.Popen, object, Path, Path]] = []
for gpu, start, stop in [(0, 0, split), (1, split, total_shards)]:
    if gpu == 1:
        time.sleep(WORKER_STAGGER_S)
    output = Path(f"{WORK}/data/shards_{gpu}")
    output.mkdir(parents=True, exist_ok=True)
    log_path = Path(f"{WORK}/gpu{gpu}.log")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["PYTORCH_CUDA_ALLOC_CONF"] = PYTORCH_ALLOC
    log = log_path.open("w", encoding="utf-8")
    print(f"launch gpu={gpu} shards=[{start}, {stop}) -> {output}")
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

progress = tqdm(total=total_shards, desc="T4 x2 embedding", unit="shard")
last_completed = 0
while any(process.poll() is None for process, _, _, _ in processes):
    for gpu, (process, log, _, log_path) in enumerate(processes):
        if process.poll() is not None and process.returncode != 0:
            log.flush()
            fail_worker(f"GPU {gpu} worker", log_path, process.returncode)

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

for gpu, (process, log, output, log_path) in enumerate(processes):
    returncode = process.wait()
    log.close()
    if returncode != 0:
        fail_worker(f"GPU {gpu} worker", log_path, returncode)
    shard_count = len(list(output.glob("vectors_shard_*.npy")))
    print(f"gpu={gpu} shards_done={shard_count} log={log_path}")

print("Embedding complete:", total_rows, "rows")
