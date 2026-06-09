"""Discover, verify, and merge embedding shards from parallel Kaggle member runs."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from embedding_common import VECTOR_SIZE, atomic_write_json, read_json

SHARD_SIZE = 10_000
NUM_MEMBERS = 5
# Legacy payload_fingerprint values include path and mtime, so they cannot be
# compared across independently generated Kaggle member outputs.
CONFIG_KEYS = (
    "embedding_model",
    "model_revision",
    "max_length",
    "normalize",
    "vector_dtype",
    "vector_size",
    "shard_size",
)


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
    dirs = [member_root / "gpu0", member_root / "gpu1"]
    missing = [str(path) for path in dirs if not path.is_dir()]
    if missing:
        raise FileNotFoundError(f"Missing GPU output dir(s) under {member_root}: {missing}")
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


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {dst}")
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


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
