"""Consolidated shard management CLI tool for parallel Kaggle member runs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from pipeline.embedding.embedding_common import VECTOR_SIZE, atomic_write_json, read_json

SHARD_SIZE = 10_000
NUM_MEMBERS = 5

CONFIG_KEYS = (
    "embedding_model",
    "model_revision",
    "max_length",
    "normalize",
    "vector_dtype",
    "vector_size",
    "shard_size",
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


# =====================================================================
# Utilities
# =====================================================================

def member_shard_range(
    member_id: int, total_shards: int, num_members: int = NUM_MEMBERS
) -> tuple[int, int]:
    if not 1 <= member_id <= num_members:
        raise ValueError(f"member_id must be 1..{num_members}, got {member_id}")
    base = total_shards // num_members
    extra = total_shards % num_members
    sizes = [base + (1 if index < extra else 0) for index in range(num_members)]
    start = sum(sizes[: member_id - 1])
    stop = start + sizes[member_id - 1]
    return start, stop


def shard_key(shard_index: int) -> str:
    return f"{shard_index:05d}"


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def discover_member_roots(
    search_roots: list[Path], num_members: int = NUM_MEMBERS
) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.rglob("shards_member_*"):
            if not candidate.is_dir():
                continue
            suffix = candidate.name.removeprefix("shards_member_")
            if not suffix.isdigit():
                continue
            member_id = int(suffix)
            if not 1 <= member_id <= num_members:
                continue
            found.setdefault(member_id, candidate.resolve())
    missing = sorted(set(range(1, num_members + 1)) - set(found))
    if missing:
        searched = ", ".join(str(path) for path in search_roots)
        raise FileNotFoundError(
            f"Missing shards_member_* for member id(s) {missing}. Searched: {searched}"
        )
    return found


def find_payload_parquet(search_roots: list[Path]) -> Path:
    candidates: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        candidates.extend(root.rglob("embed_payload_v0.1.parquet"))
    if not candidates:
        raise FileNotFoundError("embed_payload_v0.1.parquet not found in search roots")
    return max(candidates, key=lambda path: path.stat().st_size)


def gpu_dirs(member_root: Path) -> list[Path]:
    dirs = sorted([d for d in member_root.glob("gpu*") if d.is_dir()])
    if not dirs:
        raise FileNotFoundError(f"No GPU output dir(s) (gpu*) found under {member_root}")
    return dirs


@dataclass
class MemberReport:
    member_id: int
    root: Path
    shard_start: int
    shard_stop: int
    shard_count: int
    row_count: int
    gpu_dirs: list[Path] = field(default_factory=list)


@dataclass
class VerifyReport:
    payload_path: Path
    total_rows: int
    total_shards: int
    members: list[MemberReport]
    shard_keys: list[str]
    row_count: int
    config: dict[str, Any]


def _load_manifests(member_roots: dict[int, Path]) -> dict[int, list[tuple[Path, dict[str, Any]]]]:
    manifests: dict[int, list[tuple[Path, dict[str, Any]]]] = {}
    for member_id, member_root in sorted(member_roots.items()):
        manifests[member_id] = []
        for gpu_dir in gpu_dirs(member_root):
            manifest_path = gpu_dir / "manifest.json"
            manifest = read_json(manifest_path)
            if not manifest or not manifest.get("shards"):
                raise ValueError(f"Empty or missing manifest: {manifest_path}")
            manifests[member_id].append((gpu_dir, manifest))
    return manifests


def _compare_config(reference: dict[str, Any], other: dict[str, Any], label: str) -> None:
    mismatches = {
        key: (reference.get(key), other.get(key))
        for key in CONFIG_KEYS
        if reference.get(key) != other.get(key)
    }
    if mismatches:
        raise ValueError(f"Inconsistent embedding config in {label}: {mismatches}")


def resolve_device(requested: str, allow_cpu: bool) -> str:
    import torch
    if requested.startswith("cuda") and not torch.cuda.is_available():
        if allow_cpu:
            logger.warning("CUDA is unavailable; encoding missing chunks on CPU.")
            return "cpu"
        raise RuntimeError(
            "CUDA is unavailable, but repairing/missing chunks require embedding inference. "
            "Enable CUDA or pass --allow-cpu."
        )
    return requested


# =====================================================================
# Verification
# =====================================================================

def verify_member_shards(
    search_roots: list[Path],
    *,
    num_members: int = NUM_MEMBERS,
    shard_size: int = SHARD_SIZE,
    spot_check_vectors: bool = True,
) -> VerifyReport:
    member_roots = discover_member_roots(search_roots, num_members)
    payload_path = member_roots[1].parent / "embed_payload_v0.1.parquet"
    if not payload_path.exists():
        payload_path = find_payload_parquet(search_roots)
    payload_file = pq.ParquetFile(payload_path)
    total_rows = payload_file.metadata.num_rows
    total_shards = (total_rows + shard_size - 1) // shard_size
    expected_chunk_ids = {
        chunk_id
        for batch in payload_file.iter_batches(batch_size=shard_size, columns=["chunk_id"])
        for chunk_id in batch.column(0).to_pylist()
    }
    if len(expected_chunk_ids) != total_rows:
        raise ValueError(f"Canonical payload has duplicate chunk_id values: {payload_path}")

    manifests = _load_manifests(member_roots)
    reference_manifest = manifests[1][0][1]
    reference_config = {key: reference_manifest.get(key) for key in CONFIG_KEYS}

    all_shards: dict[str, tuple[int, Path, dict[str, Any]]] = {}
    all_chunk_ids: dict[str, tuple[str, Path]] = {}
    duplicate_chunk_ids: list[tuple[str, str, Path, str, Path]] = []
    members: list[MemberReport] = []

    for member_id, entries in sorted(manifests.items()):
        shard_start, shard_stop = member_shard_range(member_id, total_shards, num_members)
        expected_keys = {shard_key(index) for index in range(shard_start, shard_stop)}
        seen_keys: set[str] = set()
        member_rows = 0
        gpu_paths = [gpu_dir for gpu_dir, _ in entries]

        for gpu_dir, manifest in entries:
            _compare_config(reference_config, manifest, str(gpu_dir))
            for key, info in manifest.get("shards", {}).items():
                if info.get("status") != "done":
                    raise ValueError(f"Shard {key} in {gpu_dir} is not done: {info}")
                if key in seen_keys:
                    raise ValueError(f"Duplicate shard {key} inside member {member_id}")
                seen_keys.add(key)

                vector_path = gpu_dir / info["vectors"]
                payload_path_shard = gpu_dir / info["payload"]
                if not vector_path.exists() or not payload_path_shard.exists():
                    raise FileNotFoundError(
                        f"Missing files for shard {key} in {gpu_dir}: "
                        f"{vector_path.name}, {payload_path_shard.name}"
                    )
                if info.get("rows") is None:
                    raise ValueError(f"Shard {key} in {gpu_dir} has no row count")

                actual_chunk_ids = (
                    pq.read_table(payload_path_shard, columns=["chunk_id"])
                    .column("chunk_id")
                    .to_pylist()
                )
                if len(actual_chunk_ids) != info["rows"]:
                    raise ValueError(
                        f"Payload row count mismatch for shard {key} in {gpu_dir}: "
                        f"{len(actual_chunk_ids)} vs {info['rows']}"
                    )
                for chunk_id in actual_chunk_ids:
                    if chunk_id in all_chunk_ids:
                        previous_key, previous_dir = all_chunk_ids[chunk_id]
                        duplicate_chunk_ids.append(
                            (chunk_id, previous_key, previous_dir, key, gpu_dir)
                        )
                    else:
                        all_chunk_ids[chunk_id] = (key, gpu_dir)

                if spot_check_vectors:
                    vectors = np.load(vector_path, mmap_mode="r")
                    if vectors.shape != (info["rows"], VECTOR_SIZE):
                        raise ValueError(
                            f"Vector shape mismatch for shard {key} in {gpu_dir}: "
                            f"{vectors.shape} vs ({info['rows']}, {VECTOR_SIZE})"
                        )
                    norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
                    if not np.allclose(norms, 1.0, atol=1e-2):
                        raise ValueError(f"Non-normalized vectors in shard {key} ({gpu_dir})")

                if key in all_shards:
                    previous_member, previous_dir, _ = all_shards[key]
                    raise ValueError(
                        f"Global duplicate shard {key}: member {previous_member}/{previous_dir} "
                        f"and member {member_id}/{gpu_dir}"
                    )
                all_shards[key] = (member_id, gpu_dir, info)
                member_rows += int(info["rows"])

        missing = sorted(expected_keys - seen_keys)
        extra = sorted(seen_keys - expected_keys)
        if missing:
            raise ValueError(f"Member {member_id} missing shard(s): {missing[:5]}{'...' if len(missing) > 5 else ''}")
        if extra:
            raise ValueError(f"Member {member_id} has unexpected shard(s): {extra[:5]}{'...' if len(extra) > 5 else ''}")

        members.append(
            MemberReport(
                member_id=member_id,
                root=member_roots[member_id],
                shard_start=shard_start,
                shard_stop=shard_stop,
                shard_count=len(seen_keys),
                row_count=member_rows,
                gpu_dirs=gpu_paths,
            )
        )

    expected_keys = {shard_key(index) for index in range(total_shards)}
    if set(all_shards) != expected_keys:
        missing_global = sorted(expected_keys - set(all_shards))
        extra_global = sorted(set(all_shards) - expected_keys)
        raise ValueError(
            f"Global shard set mismatch. missing={missing_global[:5]} extra={extra_global[:5]}"
        )

    row_count = sum(info["rows"] for _, _, info in all_shards.values())
    if row_count != total_rows:
        raise ValueError(f"Row count mismatch: shards sum to {row_count:,}, payload has {total_rows:,}")

    actual_chunk_ids = set(all_chunk_ids)
    missing_chunk_ids = expected_chunk_ids - actual_chunk_ids
    unexpected_chunk_ids = actual_chunk_ids - expected_chunk_ids
    if duplicate_chunk_ids or missing_chunk_ids or unexpected_chunk_ids:
        duplicate_examples = [
            f"{chunk_id}: shard {previous_key} in {previous_dir} and shard {key} in {gpu_dir}"
            for chunk_id, previous_key, previous_dir, key, gpu_dir
            in duplicate_chunk_ids[:5]
        ]
        raise ValueError(
            "Combined member outputs are not a complete unique corpus. "
            f"encoded_rows={row_count:,} unique_encoded_chunks={len(actual_chunk_ids):,} "
            f"duplicate_rows={len(duplicate_chunk_ids):,} "
            f"missing_chunks={len(missing_chunk_ids):,} "
            f"unexpected_chunks={len(unexpected_chunk_ids):,}. "
            f"duplicate_examples={duplicate_examples} "
            f"missing_examples={list(sorted(missing_chunk_ids))[:5]} "
            f"unexpected_examples={list(sorted(unexpected_chunk_ids))[:5]}"
        )

    return VerifyReport(
        payload_path=payload_path,
        total_rows=total_rows,
        total_shards=total_shards,
        members=members,
        shard_keys=sorted(all_shards),
        row_count=row_count,
        config=reference_config,
    )


def format_verify_report(report: VerifyReport) -> str:
    lines = [
        "Member shard verification PASSED",
        f"payload: {report.payload_path}",
        f"rows: {report.total_rows:,}",
        f"shards: {report.total_shards}",
        f"embedding_model: {report.config.get('embedding_model')}",
        f"model_revision: {report.config.get('model_revision')}",
        f"max_length: {report.config.get('max_length')}",
        "",
        "Per-member summary:",
    ]
    for member in report.members:
        lines.append(
            f"  member {member.member_id}: shards [{member.shard_start}, {member.shard_stop}) "
            f"count={member.shard_count} rows={member.row_count:,} root={member.root}"
        )
    lines.append("")
    lines.append(f"Global shard keys: {report.shard_keys[0]} .. {report.shard_keys[-1]}")
    lines.append(f"Total encoded rows: {report.row_count:,}")
    return "\n".join(lines)


# =====================================================================
# Merging Shards & FAISS
# =====================================================================

def merge_member_shards(
    search_roots: list[Path],
    output_dir: Path,
    *,
    num_members: int = NUM_MEMBERS,
    spot_check_vectors: bool = True,
) -> VerifyReport:
    report = verify_member_shards(
        search_roots,
        num_members=num_members,
        spot_check_vectors=spot_check_vectors,
    )
    if output_dir.exists():
        existing = list(output_dir.glob("vectors_shard_*.npy"))
        if existing:
            raise FileExistsError(
                f"{output_dir} already contains {len(existing)} vector shard(s). "
                "Use a new directory or remove it first."
            )
    output_dir.mkdir(parents=True, exist_ok=True)

    member_roots = discover_member_roots(search_roots, num_members)
    manifests = _load_manifests(member_roots)
    merged_shards: dict[str, Any] = {}

    for member_id, entries in sorted(manifests.items()):
        for gpu_dir, manifest in entries:
            for key, info in manifest["shards"].items():
                if key in merged_shards:
                    raise ValueError(f"Duplicate shard {key} while merging")
                vector_name = info["vectors"]
                payload_name = info["payload"]
                _link_or_copy(gpu_dir / vector_name, output_dir / vector_name)
                _link_or_copy(gpu_dir / payload_name, output_dir / payload_name)
                merged_shards[key] = {
                    "status": "done",
                    "rows": info["rows"],
                    "first_chunk_id": info.get("first_chunk_id"),
                    "last_chunk_id": info.get("last_chunk_id"),
                    "vectors": vector_name,
                    "payload": payload_name,
                }

    merged_manifest = dict(report.config)
    merged_manifest["shards"] = dict(sorted(merged_shards.items()))
    merged_manifest["completed_rows"] = report.row_count
    merged_manifest["member_merge"] = {
        "num_members": num_members,
        "member_roots": {str(member_id): str(member_roots[member_id]) for member_id in member_roots},
    }
    atomic_write_json(output_dir / "manifest.json", merged_manifest)
    return report


def merge_faiss_indexes(data_dir: Path, output_dir: Path):
    import faiss
    logger.info("=== Merging FAISS Indexes and Payloads ===")
    
    faiss_dir = data_dir / "legal_embedding_6" / "faiss_members"
    manifest_path = faiss_dir / "manifest.json"
    
    if not manifest_path.exists():
        logger.error(f"Missing FAISS manifest: {manifest_path}")
        sys.exit(1)
        
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
        
    indexes = manifest_data.get("indexes", {})
    ordered_names = ["member_1", "member_2", "member_3", "member_4", "member_5", "repair"]
    
    for name in ordered_names:
        if name not in indexes:
            logger.error(f"Index {name} not found in FAISS manifest")
            sys.exit(1)
        if indexes[name].get("status") != "done":
            logger.error(f"Index {name} status is not done")
            sys.exit(1)
            
    output_faiss_dir = output_dir / "faiss"
    output_faiss_dir.mkdir(parents=True, exist_ok=True)
    
    trained_src = faiss_dir / "trained.faiss"
    trained_dst = output_faiss_dir / "trained.faiss"
    if trained_src.exists():
        logger.info(f"Copying trained.faiss to {trained_dst}")
        _link_or_copy(trained_src, trained_dst)
        
    merged_index = None
    merged_tables = []
    current_shift = 0
    
    for name in ordered_names:
        idx_info = indexes[name]
        idx_file = faiss_dir / idx_info["index"]
        payload_file = faiss_dir / idx_info["payload"]
        
        logger.info(f"Loading {name} FAISS index: {idx_file}")
        idx = faiss.read_index(str(idx_file))
        
        logger.info(f"Loading {name} Arrow payload: {payload_file}")
        handle = pa.memory_map(str(payload_file), "r")
        table = ipc.open_file(handle).read_all()
        handle.close()
        
        if idx.ntotal != table.num_rows:
            logger.error(f"Row count mismatch in {name}: index={idx.ntotal}, payload={table.num_rows}")
            sys.exit(1)
            
        logger.info(f"Merging index {name} with shift {current_shift}")
        if merged_index is None:
            merged_index = idx
        else:
            merged_index.merge_from(idx, current_shift)
            
        merged_tables.append(table)
        current_shift += table.num_rows
        
    logger.info("Concatenating Arrow payload tables...")
    merged_table = pa.concat_tables(merged_tables)
    
    if merged_index.ntotal != merged_table.num_rows:
        logger.error(f"Merged row count mismatch: index={merged_index.ntotal}, table={merged_table.num_rows}")
        sys.exit(1)
        
    dest_index_path = output_faiss_dir / "merged.faiss"
    dest_payload_path = output_faiss_dir / "merged.payload.arrow"
    
    logger.info(f"Writing merged FAISS index to {dest_index_path}...")
    faiss.write_index(merged_index, str(dest_index_path))
    
    logger.info(f"Writing merged Arrow payload to {dest_payload_path}...")
    payload_sink = pa.OSFile(str(dest_payload_path), "wb")
    payload_writer = ipc.new_file(
        payload_sink,
        merged_table.schema,
        options=ipc.IpcWriteOptions(compression="zstd"),
    )
    payload_writer.write_table(merged_table)
    payload_writer.close()
    payload_sink.close()
    
    new_manifest = {
        "format": "faiss_members_v2_deduplicated",
        "indexes": {
            "merged": {
                "status": "done",
                "rows": merged_index.ntotal,
                "input_rows": manifest_data.get("completed_rows", merged_index.ntotal),
                "duplicates_removed": manifest_data.get("duplicates_removed", 0),
                "index": "merged.faiss",
                "payload": "merged.payload.arrow"
            }
        },
        "factory": manifest_data.get("factory", "IVF4096,PQ64x8"),
        "completed_rows": merged_index.ntotal,
        "unique_rows": merged_index.ntotal,
        "duplicates_removed": manifest_data.get("duplicates_removed", 0)
    }
    
    dest_manifest_path = output_faiss_dir / "manifest.json"
    with open(dest_manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False, indent=2)
        
    logger.info(f"FAISS indexes merge complete! Total rows: {merged_index.ntotal}")
    logger.info(f"Manifest written to: {dest_manifest_path}")


# =====================================================================
# Shards Repair & Missing Detection
# =====================================================================

def write_missing_payload(
    canonical_payload: Path, missing_ids: set[str], output_path: Path
) -> int:
    if output_path.exists():
        existing_ids = {
            chunk_id
            for batch in pq.ParquetFile(output_path).iter_batches(
                batch_size=100_000, columns=["chunk_id"]
            )
            for chunk_id in batch.column(0).to_pylist()
        }
        if existing_ids == missing_ids:
            return len(existing_ids)
    value_set = pa.array(sorted(missing_ids))
    writer: pq.ParquetWriter | None = None
    written = 0
    try:
        for batch in pq.ParquetFile(canonical_payload).iter_batches(batch_size=100_000):
            chunk_id = batch.column(batch.schema.get_field_index("chunk_id"))
            selected = pa.Table.from_batches([batch]).filter(
                pc.is_in(chunk_id, value_set=value_set)
            )
            if selected.num_rows == 0:
                continue
            if writer is None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                writer = pq.ParquetWriter(output_path, selected.schema, compression="zstd")
            writer.write_table(selected)
            written += selected.num_rows
    finally:
        if writer is not None:
            writer.close()
    if written != len(missing_ids):
        raise ValueError(f"Missing payload extraction wrote {written:,}/{len(missing_ids):,} rows")
    return written


def completed_output_ids(output_dir: Path) -> set[str]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return set()
    manifest = read_json(manifest_path)
    return {
        chunk_id
        for info in manifest.get("shards", {}).values()
        if info.get("status") == "done"
        for chunk_id in (
            pq.read_table(output_dir / info["payload"], columns=["chunk_id"])
            .column("chunk_id")
            .to_pylist()
        )
    }


def scan_member_ids(
    member_roots: dict[int, Path],
) -> tuple[set[str], int, dict[str, Any]]:
    manifests: dict[int, list[tuple[Path, dict[str, Any]]]] = {}
    for member_id, member_root in sorted(member_roots.items()):
        manifests[member_id] = []
        for gpu_dir in (member_root / "gpu0", member_root / "gpu1"):
            manifest = read_json(gpu_dir / "manifest.json")
            if manifest.get("shards"):
                manifests[member_id].append((gpu_dir, manifest))
    available = [entry for entries in manifests.values() for entry in entries]
    if not available:
        raise ValueError("No completed member manifests were found")
    reference = available[0][1]
    config = {key: reference.get(key) for key in CONFIG_KEYS}
    seen_ids: set[str] = set()
    duplicate_rows = 0
    for entries in manifests.values():
        for gpu_dir, manifest in entries:
            _compare_config(config, manifest, str(gpu_dir))
            for info in manifest["shards"].values():
                if info.get("status") != "done":
                    continue
                payload_path = gpu_dir / info["payload"]
                chunk_ids = (
                    pq.read_table(payload_path, columns=["chunk_id"])
                    .column("chunk_id")
                    .to_pylist()
                )
                for chunk_id in chunk_ids:
                    if chunk_id in seen_ids:
                        duplicate_rows += 1
                    else:
                        seen_ids.add(chunk_id)
    return seen_ids, duplicate_rows, config


def run_repair_member_shards(args) -> None:
    completed_manifest = read_json(args.output_dir / "manifest.json")
    if completed_manifest.get("repair") and completed_manifest.get("completed_rows"):
        logger.info(
            "Repair already complete: %d rows in %s",
            completed_manifest['completed_rows'], args.output_dir
        )
        return
    device = resolve_device(args.device, args.allow_cpu)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    member_roots = discover_member_roots(args.search_root, args.num_members)
    canonical_payload = member_roots[1].parent / "embed_payload_v0.1.parquet"
    if not canonical_payload.exists():
        raise FileNotFoundError(f"Member 1 full payload is missing: {canonical_payload}")

    canonical_file = pq.ParquetFile(canonical_payload)
    canonical_rows = canonical_file.metadata.num_rows
    canonical_ids = {
        chunk_id
        for batch in canonical_file.iter_batches(batch_size=100_000, columns=["chunk_id"])
        for chunk_id in batch.column(0).to_pylist()
    }
    if len(canonical_ids) != canonical_rows:
        raise ValueError(f"Canonical payload contains duplicate chunk IDs: {canonical_payload}")
    manifests = _load_manifests(member_roots)
    reference = manifests[1][0][1]
    config = {key: reference.get(key) for key in CONFIG_KEYS}
    merged_shards: dict[str, Any] = {}
    seen_ids: set[str] = set()
    duplicate_rows = 0

    for member_id, entries in sorted(manifests.items()):
        for gpu_dir, manifest in entries:
            _compare_config(config, manifest, str(gpu_dir))
            for key, info in sorted(manifest["shards"].items()):
                payload_path = gpu_dir / info["payload"]
                vector_path = gpu_dir / info["vectors"]
                table = pq.read_table(payload_path)
                vectors = np.load(vector_path, mmap_mode="r")
                chunk_ids = table.column("chunk_id").to_pylist()
                if len(chunk_ids) != len(vectors):
                    raise ValueError(f"Payload/vector row mismatch in {gpu_dir}, shard {key}")

                keep = np.zeros(len(chunk_ids), dtype=np.bool_)
                for index, chunk_id in enumerate(chunk_ids):
                    if chunk_id not in seen_ids:
                        keep[index] = True
                        seen_ids.add(chunk_id)
                duplicate_rows += int((~keep).sum())
                if not keep.any():
                    continue

                output_key = f"existing_{key}"
                output_vectors = args.output_dir / f"vectors_{output_key}.npy"
                output_payload = args.output_dir / f"payload_{output_key}.parquet"
                if output_vectors.exists() != output_payload.exists():
                    raise FileExistsError(
                        f"Incomplete repair shard; remove both files and rerun: "
                        f"{output_vectors}, {output_payload}"
                    )
                if not output_vectors.exists():
                    if keep.all():
                        _link_or_copy(vector_path, output_vectors)
                        _link_or_copy(payload_path, output_payload)
                    else:
                        with output_vectors.open("wb") as handle:
                            np.save(handle, np.asarray(vectors)[keep])
                        pq.write_table(
                            table.filter(pa.array(keep)), output_payload, compression="zstd"
                        )

                kept_ids = [chunk_id for chunk_id, should_keep in zip(chunk_ids, keep, strict=True) if should_keep]
                merged_shards[output_key] = {
                    "status": "done",
                    "rows": len(kept_ids),
                    "first_chunk_id": kept_ids[0],
                    "last_chunk_id": kept_ids[-1],
                    "vectors": output_vectors.name,
                    "payload": output_payload.name,
                    "source_member": member_id,
                }

    unexpected_ids = seen_ids - canonical_ids
    if unexpected_ids:
        raise ValueError(f"Existing outputs contain unexpected chunk IDs: {sorted(unexpected_ids)[:5]}")
    missing_ids = canonical_ids - seen_ids
    logger.info(
        "Existing outputs: unique=%d duplicates_removed=%d missing_to_encode=%d",
        len(seen_ids), duplicate_rows, len(missing_ids)
    )

    if missing_ids:
        logger.info(
            "Encoding missing chunks now: %d out of %d canonical chunks",
            len(missing_ids), len(canonical_ids)
        )
        missing_payload = args.work_dir / "missing_payload.parquet"
        repair_output = args.work_dir / "missing_encoded"
        write_missing_payload(canonical_payload, missing_ids, missing_payload)
        subprocess.run(
            [
                sys.executable,
                "embed_shards.py",
                "--payload",
                str(missing_payload),
                "--output-dir",
                str(repair_output),
                "--batch-size",
                args.batch_size,
                "--token-budget",
                args.token_budget,
                "--max-length",
                args.max_length,
                "--attn-implementation",
                args.attn_implementation,
                "--cache-dir",
                args.cache_dir,
                "--device",
                device,
            ],
            check=True,
        )
        repair_manifest = json.loads(
            (repair_output / "manifest.json").read_text(encoding="utf-8")
        )
        _compare_config(config, repair_manifest, str(repair_output))
        for key, info in sorted(repair_manifest["shards"].items()):
            output_key = f"repair_{key}"
            output_vectors = args.output_dir / f"vectors_{output_key}.npy"
            output_payload = args.output_dir / f"payload_{output_key}.parquet"
            _link_or_copy(repair_output / info["vectors"], output_vectors)
            _link_or_copy(repair_output / info["payload"], output_payload)
            merged_shards[output_key] = {
                **info,
                "vectors": output_vectors.name,
                "payload": output_payload.name,
            }

    completed_rows = sum(item["rows"] for item in merged_shards.values())
    if completed_rows != len(canonical_ids):
        raise ValueError(f"Repair output has {completed_rows:,}/{len(canonical_ids):,} rows")
    manifest = dict(config)
    manifest["shards"] = dict(sorted(merged_shards.items()))
    manifest["completed_rows"] = completed_rows
    manifest["repair"] = {
        "duplicates_removed": duplicate_rows,
        "missing_encoded": len(missing_ids),
        "canonical_payload": str(canonical_payload),
    }
    atomic_write_json(args.output_dir / "manifest.json", manifest)
    logger.info("Repair complete: %d unique rows in %s", completed_rows, args.output_dir)


def run_repair_missing_shards(args) -> None:
    member_roots = discover_member_roots(args.search_root, args.num_members)
    canonical_payload = args.canonical_payload or (
        member_roots[1].parent / "embed_payload_v0.1.parquet"
    )
    if not canonical_payload.exists():
        raise FileNotFoundError(f"Canonical payload is missing: {canonical_payload}")

    canonical_file = pq.ParquetFile(canonical_payload)
    canonical_ids = {
        chunk_id
        for batch in canonical_file.iter_batches(batch_size=100_000, columns=["chunk_id"])
        for chunk_id in batch.column(0).to_pylist()
    }
    if len(canonical_ids) != canonical_file.metadata.num_rows:
        raise ValueError(f"Canonical payload contains duplicate chunk IDs: {canonical_payload}")
    seen_ids, duplicate_rows, config = scan_member_ids(member_roots)
    unexpected_ids = seen_ids - canonical_ids
    if unexpected_ids:
        raise ValueError(f"Member outputs contain unexpected chunk IDs: {sorted(unexpected_ids)[:5]}")
    missing_ids = canonical_ids - seen_ids
    existing_repair_ids = completed_output_ids(args.output_dir)
    stale_repair_ids = existing_repair_ids - missing_ids
    if stale_repair_ids:
        raise ValueError(
            f"Existing repair output contains {len(stale_repair_ids):,} rows that are "
            f"no longer missing. Use a clean repair output directory. "
            f"Examples: {sorted(stale_repair_ids)[:5]}"
        )
    logger.info(
        "Member outputs: unique=%d duplicates_to_ignore=%d missing_to_encode=%d",
        len(seen_ids), duplicate_rows, len(missing_ids)
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        **config,
        "canonical_rows": len(canonical_ids),
        "member_rows": len(seen_ids),
        "member_duplicate_rows": duplicate_rows,
        "missing_encoded": len(missing_ids),
        "canonical_payload": str(canonical_payload),
    }
    if not missing_ids:
        atomic_write_json(args.output_dir / "repair_summary.json", summary)
        logger.info("No missing chunks; no repair vector shards were written.")
        return

    device = resolve_device(args.device, args.allow_cpu)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    missing_payload = args.work_dir / "missing_payload.parquet"
    write_missing_payload(canonical_payload, missing_ids, missing_payload)
    subprocess.run(
        [
            sys.executable,
            "embed_shards.py",
            "--payload",
            str(missing_payload),
            "--output-dir",
            str(args.output_dir),
            "--batch-size",
            args.batch_size,
            "--token-budget",
            args.token_budget,
            "--max-length",
            args.max_length,
            "--attn-implementation",
            args.attn_implementation,
            "--cache-dir",
            args.cache_dir,
            "--device",
            device,
        ],
        check=True,
    )
    manifest_path = args.output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["repair"] = summary
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(args.output_dir / "repair_summary.json", summary)
    logger.info("Encoded %d missing chunks into %s", len(missing_ids), args.output_dir)


# =====================================================================
# Main CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Consolidated member shard management tool.")
    subparsers = parser.add_subparsers(dest="action", required=True, help="Subcommand to run")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify embedding shards output from parallel runs.")
    p_verify.add_argument("--search-root", type=Path, action="append", required=True)
    p_verify.add_argument("--num-members", type=int, default=NUM_MEMBERS)
    p_verify.add_argument("--no-spot-check", action="store_true", help="Skip loading vector files for checks.")

    # merge-shards
    p_merge_shards = subparsers.add_parser("merge-shards", help="Merge shards from parallel runs.")
    p_merge_shards.add_argument("--search-root", type=Path, action="append", required=True)
    p_merge_shards.add_argument("--output-dir", type=Path, required=True)
    p_merge_shards.add_argument("--num-members", type=int, default=NUM_MEMBERS)
    p_merge_shards.add_argument("--no-spot-check", action="store_true", help="Skip loading vector files for checks.")

    # merge-faiss
    p_merge_faiss = subparsers.add_parser("merge-faiss", help="Merge member FAISS indexes and arrow payloads.")
    p_merge_faiss.add_argument("--data-dir", type=Path, required=True, help="Folder containing the member runs.")
    p_merge_faiss.add_argument("--output-dir", type=Path, required=True, help="Merged output folder.")

    # repair-member-shards
    p_repair_mem = subparsers.add_parser("repair-member-shards", help="Deduplicate member outputs and encode missing chunks.")
    p_repair_mem.add_argument("--search-root", type=Path, action="append", required=True)
    p_repair_mem.add_argument("--output-dir", type=Path, required=True)
    p_repair_mem.add_argument("--work-dir", type=Path, required=True)
    p_repair_mem.add_argument("--num-members", type=int, default=NUM_MEMBERS)
    p_repair_mem.add_argument("--batch-size", default="128")
    p_repair_mem.add_argument("--token-budget", default="49152")
    p_repair_mem.add_argument("--max-length", default="1024")
    p_repair_mem.add_argument("--attn-implementation", default="sdpa")
    p_repair_mem.add_argument("--cache-dir", default="/tmp/vnlegal_hf_cache")
    p_repair_mem.add_argument("--device", default="cuda:0")
    p_repair_mem.add_argument("--allow-cpu", action="store_true")

    # repair-missing-shards
    p_repair_miss = subparsers.add_parser("repair-missing-shards", help="Encode missing unique chunk IDs from read-only member sets.")
    p_repair_miss.add_argument("--search-root", type=Path, action="append", required=True)
    p_repair_miss.add_argument("--canonical-payload", type=Path, default=None)
    p_repair_miss.add_argument("--output-dir", type=Path, required=True)
    p_repair_miss.add_argument("--work-dir", type=Path, required=True)
    p_repair_miss.add_argument("--num-members", type=int, default=NUM_MEMBERS)
    p_repair_miss.add_argument("--batch-size", default="128")
    p_repair_miss.add_argument("--token-budget", default="49152")
    p_repair_miss.add_argument("--max-length", default="1024")
    p_repair_miss.add_argument("--attn-implementation", default="sdpa")
    p_repair_miss.add_argument("--cache-dir", default="/tmp/vnlegal_hf_cache")
    p_repair_miss.add_argument("--device", default="cuda:0")
    p_repair_miss.add_argument("--allow-cpu", action="store_true")

    args = parser.parse_args()

    if args.action == "verify":
        try:
            report = verify_member_shards(
                args.search_root,
                num_members=args.num_members,
                spot_check_vectors=not args.no_spot_check,
            )
            print(format_verify_report(report))
        except (FileNotFoundError, ValueError) as exc:
            print(f"VERIFICATION FAILED\n{exc}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "merge-shards":
        try:
            report = merge_member_shards(
                args.search_root,
                args.output_dir,
                num_members=args.num_members,
                spot_check_vectors=not args.no_spot_check,
            )
            print(format_verify_report(report))
            print(f"\nMerged shards written to: {args.output_dir.resolve()}")
        except (FileNotFoundError, ValueError, FileExistsError) as exc:
            print(f"MERGE FAILED\n{exc}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "merge-faiss":
        merge_faiss_indexes(args.data_dir, args.output_dir)

    elif args.action == "repair-member-shards":
        run_repair_member_shards(args)

    elif args.action == "repair-missing-shards":
        run_repair_missing_shards(args)


if __name__ == "__main__":
    main()
