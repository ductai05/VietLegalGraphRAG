"""Shared utilities for the VietLegal dense embedding pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

MODEL_NAME = "darklethelong/vnlegal-lal"
QUERY_PREFIX = (
    "Instruct: Given a Vietnamese legal question, "
    "retrieve relevant legal passages that answer the question\nQuery: "
)
VECTOR_SIZE = 1024
COLLECTION_NAME = "legal_chunks_dense_v1"
P100_TORCH_INSTALL = (
    "pip install --force-reinstall --no-cache-dir torch==2.10.0 "
    "--index-url https://download.pytorch.org/whl/cu126"
)

PAYLOAD_FIELDS = [
    "chunk_id",
    "doc_id",
    "chunk_type",
    "source",
    "document_number",
    "title",
    "legal_type",
    "issuing_authority",
    "issuance_date",
    "issuance_date_ts",
    "effect_date_ts",
    "effectless_date_ts",
    "effect_status",
    "expansion_status",
    "linh_vuc",
    "nganh",
    "section_path",
    "parent_id",
    "raw_table_id",
    "table_id",
    "summary_of",
    "answer_source",
    "do_not_answer_from_summary",
    "table_columns",
    "procedure_name",
]


def setup_logging(log_path: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_faiss_module() -> Any:
    """Import the faiss-cpu module with an actionable dependency error."""
    try:
        import faiss
    except ModuleNotFoundError as exc:
        if exc.name != "faiss":
            raise
        raise ModuleNotFoundError(
            "FAISS retrieval/build requires faiss-cpu in this Python environment. "
            "Install it with `python -m pip install faiss-cpu`, then verify with "
            "`python -c \"import faiss; print(faiss.__version__)\"`."
        ) from exc
    return faiss


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def batched(items: Sequence[Any], batch_size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def normalize_payload_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def row_to_payload(row: dict[str, Any], include_text: bool = False) -> dict[str, Any]:
    payload = {
        field: normalize_payload_value(row.get(field))
        for field in PAYLOAD_FIELDS
    }
    if include_text:
        payload["chunk_text"] = row.get("chunk_text") or ""
    return payload


def stable_point_id(chunk_id: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vietlegal-chunk:{chunk_id}"))


def validate_cuda_device(torch: Any, device: str) -> None:
    """Fail before model loading when the installed wheel cannot run on the GPU."""
    if not device.startswith("cuda"):
        return
    if not torch.cuda.is_available():
        raise RuntimeError(
            f"CUDA device {device!r} was requested, but torch.cuda.is_available() is False"
        )

    device_index = torch.device(device).index
    if device_index is None:
        device_index = torch.cuda.current_device()
    capability = torch.cuda.get_device_capability(device_index)
    required_arch = f"sm_{capability[0]}{capability[1]}"
    wheel_arches = set(torch.cuda.get_arch_list())
    if wheel_arches and required_arch not in wheel_arches:
        gpu_name = torch.cuda.get_device_name(device_index)
        install_hint = (
            f" On Kaggle P100, install a Pascal-compatible wheel before importing "
            f"torch, then restart the session:\n  !{P100_TORCH_INSTALL}"
            if required_arch == "sm_60"
            else ""
        )
        raise RuntimeError(
            f"{gpu_name} requires {required_arch}, but PyTorch {torch.__version__} "
            f"was built for {', '.join(sorted(wheel_arches))}.{install_hint} "
            "Alternatively run with --device cpu."
        )


def load_encoder(
    model_name: str = MODEL_NAME,
    device: str | None = None,
    cache_dir: str | None = None,
    attn_implementation: str | None = None,
):
    """Load tokenizer/model and return (tokenizer, model, device, revision)."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    validate_cuda_device(torch, resolved_device)
    dtype = torch.float16 if resolved_device.startswith("cuda") else torch.float32
    if resolved_device.startswith("cuda"):
        device_index = torch.device(resolved_device).index
        if device_index is None:
            device_index = torch.cuda.current_device()
        logging.info(
            "Using GPU %s/%s: %s, capability sm_%s%s, dtype=%s",
            device_index,
            torch.cuda.device_count(),
            torch.cuda.get_device_name(device_index),
            *torch.cuda.get_device_capability(device_index),
            dtype,
        )
    else:
        logging.warning("Using CPU with dtype=%s; full-corpus embedding will be slow", dtype)
    tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model_kwargs = {
        "cache_dir": cache_dir,
        "torch_dtype": dtype,
    }
    if attn_implementation:
        model_kwargs["attn_implementation"] = attn_implementation
    model = AutoModel.from_pretrained(model_name, **model_kwargs)
    model.to(resolved_device)
    model.eval()
    # Decoder-only embedding needs the final hidden state, never the KV cache.
    model.config.use_cache = False
    revision = getattr(model.config, "_commit_hash", None) or "unknown"
    return tokenizer, model, resolved_device, revision


def _forward_embeddings(
    batch_indices: list[int],
    texts: Sequence[str],
    tokenizer: Any,
    model: Any,
    device: str,
    *,
    max_length: int,
    is_query: bool,
    pad_to_multiple_of: int | None,
    use_pinned: bool,
) -> np.ndarray:
    """Run one forward pass; on CUDA OOM, split the batch in half and retry."""
    import torch
    import torch.nn.functional as functional

    batch = [texts[index] for index in batch_indices]
    if is_query:
        batch = [QUERY_PREFIX + text for text in batch]
    inputs = tokenizer(
        batch,
        padding=True,
        truncation=True,
        max_length=max_length,
        pad_to_multiple_of=pad_to_multiple_of,
        return_tensors="pt",
    ).to(device, non_blocking=use_pinned)
    seq_len = int(inputs["attention_mask"].shape[1])
    try:
        with torch.inference_mode():
            output = model(**inputs, use_cache=False)
        attention_mask = inputs["attention_mask"]
        last_indices = seq_len - 1 - attention_mask.flip(dims=[1]).argmax(dim=1)
        row_indices = torch.arange(len(batch), device=device)
        embeddings = output.last_hidden_state[row_indices, last_indices]
        return functional.normalize(embeddings.float(), p=2, dim=1).cpu().numpy()
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if len(batch_indices) <= 1:
            raise
        mid = len(batch_indices) // 2
        logging.warning(
            "CUDA OOM on batch rows=%s seq=%s; splitting into %s + %s",
            len(batch_indices),
            seq_len,
            mid,
            len(batch_indices) - mid,
        )
        left = _forward_embeddings(
            batch_indices[:mid],
            texts,
            tokenizer,
            model,
            device,
            max_length=max_length,
            is_query=is_query,
            pad_to_multiple_of=pad_to_multiple_of,
            use_pinned=use_pinned,
        )
        right = _forward_embeddings(
            batch_indices[mid:],
            texts,
            tokenizer,
            model,
            device,
            max_length=max_length,
            is_query=is_query,
            pad_to_multiple_of=pad_to_multiple_of,
            use_pinned=use_pinned,
        )
        return np.concatenate([left, right], axis=0)
    finally:
        del inputs


def encode_texts(
    texts: Sequence[str],
    tokenizer: Any,
    model: Any,
    device: str,
    *,
    batch_size: int,
    max_length: int,
    is_query: bool = False,
    show_progress: bool = True,
    sort_by_length: bool = False,
    token_budget: int | None = None,
    pad_to_multiple_of: int | None = 8,
) -> np.ndarray:
    """Encode texts with robust last-token pooling and L2 normalization."""
    import torch
    from tqdm.auto import tqdm

    if not texts:
        return np.empty((0, VECTOR_SIZE), dtype=np.float32)

    if sort_by_length or token_budget:
        lengths = tokenizer(
            list(texts),
            add_special_tokens=True,
            truncation=True,
            max_length=max_length,
            return_length=True,
        )["length"]
    else:
        lengths = [min(len(text), max_length) for text in texts]
    padded_lengths = (
        [
            min(
                max_length,
                ((length + pad_to_multiple_of - 1) // pad_to_multiple_of)
                * pad_to_multiple_of,
            )
            for length in lengths
        ]
        if pad_to_multiple_of
        else lengths
    )

    order = (
        sorted(range(len(texts)), key=lengths.__getitem__)
        if sort_by_length
        else list(range(len(texts)))
    )
    batches: list[list[int]] = []
    current: list[int] = []
    current_max_length = 0
    for index in order:
        next_max_length = max(current_max_length, padded_lengths[index])
        exceeds_budget = bool(
            token_budget
            and current
            and next_max_length * (len(current) + 1) > token_budget
        )
        if current and (len(current) >= batch_size or exceeds_budget):
            batches.append(current)
            current = []
            current_max_length = 0
        current.append(index)
        current_max_length = max(current_max_length, lengths[index])
    if current:
        batches.append(current)

    total_padded_tokens = sum(
        max(padded_lengths[index] for index in batch) * len(batch) for batch in batches
    )
    total_real_tokens = sum(lengths)
    logging.info(
        "Encoding plan: %s batches, max batch %s, %.1f%% padding, %s tokens",
        f"{len(batches):,}",
        f"{max(map(len, batches)):,}",
        100 * (total_padded_tokens - total_real_tokens) / max(total_padded_tokens, 1),
        f"{total_real_tokens:,}",
    )

    vectors = np.empty((len(texts), VECTOR_SIZE), dtype=np.float32)
    progress: Iterable[list[int]] = batches
    if show_progress:
        progress = tqdm(batches, desc="Encoding", unit="batch")
    started = time.perf_counter()

    # Pinned memory enables async (non-blocking) GPU→CPU copies, so the CPU can
    # prepare the next batch's tokenization while the transfer is in flight.
    use_pinned = device.startswith("cuda")
    pending: tuple[list[int], "torch.Tensor"] | None = None

    for batch_indices in progress:
        if pending is not None:
            prev_indices, prev_tensor = pending
            if use_pinned:
                torch.cuda.synchronize()
            vectors[prev_indices] = prev_tensor.numpy()
            pending = None

        embeddings = _forward_embeddings(
            batch_indices,
            texts,
            tokenizer,
            model,
            device,
            max_length=max_length,
            is_query=is_query,
            pad_to_multiple_of=pad_to_multiple_of,
            use_pinned=use_pinned,
        )

        if use_pinned:
            cpu_tensor = torch.empty(
                embeddings.shape, dtype=torch.float32, pin_memory=True
            )
            cpu_tensor.copy_(torch.from_numpy(embeddings), non_blocking=True)
            pending = (batch_indices, cpu_tensor)
        else:
            vectors[batch_indices] = embeddings

    # Flush the last batch.
    if pending is not None:
        prev_indices, prev_tensor = pending
        if use_pinned:
            torch.cuda.synchronize()
        vectors[prev_indices] = prev_tensor.numpy()

    elapsed = time.perf_counter() - started
    logging.info(
        "Encoded %s rows in %.1fs (%.1f rows/s, %.1f real tokens/s)",
        f"{len(texts):,}",
        elapsed,
        len(texts) / max(elapsed, 1e-9),
        total_real_tokens / max(elapsed, 1e-9),
    )
    return vectors
