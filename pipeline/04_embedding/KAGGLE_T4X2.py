import os
import subprocess
import time
from pathlib import Path

import pyarrow.parquet as pq
import torch
from tqdm.auto import tqdm

CHUNKS = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet"
METADATA = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet"
PIPELINE = "/kaggle/input/datasets/brdh7940/04-embedding/04_embedding"
WORK = "/kaggle/working/legal_embedding"
BATCH_SIZE = "256"
TOKEN_BUDGET = "32768"
MAX_LENGTH = "1024"
ATTN_IMPL = "sdpa"

assert torch.cuda.is_available()
assert torch.cuda.device_count() == 2
for gpu in range(2):
    assert torch.cuda.get_device_capability(gpu) == (7, 5)
    print(gpu, torch.cuda.get_device_name(gpu))

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
]

processes = []
for gpu, start, stop in [(0, 0, split), (1, split, total_shards)]:
    output = f"{WORK}/data/shards_{gpu}"
    Path(output).mkdir(parents=True, exist_ok=True)
    log = open(f"{WORK}/gpu{gpu}.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    processes.append(
        (
            subprocess.Popen(
                base
                + [
                    "--output-dir",
                    output,
                    "--shard-start",
                    str(start),
                    "--shard-stop",
                    str(stop),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            ),
            log,
            output,
        )
    )

progress = tqdm(total=total_shards, desc="T4 x2 embedding", unit="shard")
last_completed = 0
while any(process.poll() is None for process, _, _ in processes):
    completed = sum(
        len(list(Path(output).glob("vectors_shard_*.npy")))
        for _, _, output in processes
    )
    progress.update(max(0, completed - last_completed))
    last_completed = completed
    time.sleep(10)

completed = sum(
    len(list(Path(output).glob("vectors_shard_*.npy")))
    for _, _, output in processes
)
progress.update(max(0, completed - last_completed))
progress.close()

for process, log, _ in processes:
    assert process.wait() == 0
    log.close()

print("Embedding complete:", total_rows, "rows")
