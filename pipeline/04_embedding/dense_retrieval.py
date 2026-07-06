"""Query Elasticsearch or sharded FAISS and optionally expand chunks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
try:
    import polars as pl
except ModuleNotFoundError as exc:
    if exc.name != "polars":
        raise
    pl = None
try:
    import pyarrow as pa
    import pyarrow.ipc as ipc
except ModuleNotFoundError as exc:
    if exc.name not in {"pyarrow", "pyarrow.ipc"}:
        raise
    pa = None
    ipc = None
try:
    from elasticsearch import Elasticsearch
except ModuleNotFoundError as exc:
    if exc.name != "elasticsearch":
        raise
    Elasticsearch = None
from pipeline.embedding.embedding_common import (
    COLLECTION_NAME,
    MODEL_NAME,
    encode_texts,
    load_encoder,
    load_faiss_module,
    read_json,
)
from pipeline.embedding.elasticsearch_common import (
    build_elasticsearch_filter,
    normalize_search_hits,
    resolve_credentials,
    resolve_num_candidates,
)

EXPAND_SCORE_THRESHOLD = 0.75
EXPAND_MIN_CHARS = 300


def format_citation(payload: dict[str, Any]) -> str:
    parts = [
        payload.get("document_number"),
        payload.get("title"),
        " > ".join(payload.get("section_path") or []),
    ]
    if payload.get("procedure_name"):
        parts.append(f"[TTHC: {payload['procedure_name']}]")
    parts.append(f"chunk_id: {payload.get('chunk_id', '')}")
    return " | ".join(str(part) for part in parts if part)


def payload_matches(payload: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        if key == "ranges":
            continue
        actual = payload.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    for key, bounds in filters.get("ranges", {}).items():
        actual = payload.get(key)
        if actual is None:
            return False
        if "gte" in bounds and actual < bounds["gte"]:
            return False
        if "gt" in bounds and actual <= bounds["gt"]:
            return False
        if "lte" in bounds and actual > bounds["lte"]:
            return False
        if "lt" in bounds and actual >= bounds["lt"]:
            return False
    return True


class DenseRetriever:
    def __init__(
        self,
        storage_dir: Path | None = None,
        *,
        url: str | None = None,
        faiss_dir: Path | None = None,
        api_key: str | None = None,
        collection: str = COLLECTION_NAME,
        model_name: str = MODEL_NAME,
        chunks_path: Path | None = None,
        device: str | None = None,
        cache_dir: str | None = None,
        query_max_length: int = 512,
        faiss_nprobe: int = 32,
        faiss_oversample: int = 20,
        elastic_cloud_id: str | None = None,
        elastic_api_key: str | None = None,
        elastic_index: str = COLLECTION_NAME,
        elastic_num_candidates: int | None = None,
    ) -> None:
        if storage_dir is not None or url is not None:
            raise ValueError(
                "Qdrant targets are no longer supported in the MVP dense "
                "retriever. Use --elastic-cloud-id for Elasticsearch."
            )
        if api_key is not None:
            raise ValueError(
                "Qdrant api_key is no longer supported. Use elastic_api_key "
                "with Elasticsearch."
            )
        targets = (faiss_dir, elastic_cloud_id)
        if sum(value is not None for value in targets) != 1:
            raise ValueError(
                "Provide exactly one of faiss_dir or elastic_cloud_id"
            )
        self.client = None
        self.elasticsearch_client: Any | None = None
        self.faiss_indexes: list[tuple[str, Any, pa.Table]] = []
        self.faiss_handles: list[pa.MemoryMappedFile] = []
        self.faiss_oversample = faiss_oversample
        self.collection = collection
        self.elastic_index = elastic_index
        self.elastic_num_candidates = elastic_num_candidates
        if faiss_dir is not None:
            self._load_faiss(faiss_dir, faiss_nprobe)
        elif elastic_cloud_id is not None:
            if Elasticsearch is None:
                raise ModuleNotFoundError(
                    "Elasticsearch retrieval requires the elasticsearch client. "
                    "Install it with `python -m pip install elasticsearch`."
                )
            resolved_cloud_id, resolved_api_key = resolve_credentials(
                elastic_cloud_id,
                elastic_api_key,
            )
            self.elasticsearch_client = Elasticsearch(
                cloud_id=resolved_cloud_id,
                api_key=resolved_api_key,
                request_timeout=60,
            )
            if not self.elasticsearch_client.indices.exists(index=elastic_index):
                self.elasticsearch_client.close()
                raise RuntimeError(
                    f"Elasticsearch index {elastic_index!r} does not exist. "
                    "Run build_elasticsearch.py successfully before retrieval."
                )
        self.tokenizer, self.model, self.device, _ = load_encoder(
            model_name, device, cache_dir
        )
        self.chunks_path = chunks_path
        self.query_max_length = query_max_length

    def _load_faiss(self, faiss_dir: Path, nprobe: int) -> None:
        if pa is None or ipc is None:
            raise ModuleNotFoundError(
                "FAISS payload retrieval requires pyarrow. Install project "
                "requirements with `python -m pip install -r requirements.txt`."
            )
        faiss = load_faiss_module()

        manifest = read_json(faiss_dir / "manifest.json")
        if not manifest.get("indexes"):
            raise FileNotFoundError(f"Missing FAISS member manifest: {faiss_dir}")
        for name, info in sorted(manifest["indexes"].items()):
            if info.get("status") != "done":
                continue
            index = faiss.read_index(str(faiss_dir / info["index"]))
            if hasattr(index, "nprobe"):
                index.nprobe = nprobe
            handle = pa.memory_map(str(faiss_dir / info["payload"]), "r")
            payload = ipc.open_file(handle).read_all()
            if index.ntotal != payload.num_rows:
                handle.close()
                raise ValueError(f"FAISS/payload row mismatch for {name}")
            if index.ntotal == 0:
                handle.close()
                continue
            self.faiss_handles.append(handle)
            self.faiss_indexes.append((name, index, payload))

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.elasticsearch_client is not None:
            self.elasticsearch_client.close()
        for handle in self.faiss_handles:
            handle.close()

    def _lookup_chunks(self, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not self.chunks_path or not chunk_ids:
            return {}
        if pl is None:
            raise ModuleNotFoundError(
                "Chunk expansion requires polars. Install project requirements "
                "with `python -m pip install -r requirements.txt`."
            )
        rows = (
            pl.scan_parquet(self.chunks_path, glob=False)
            .filter(pl.col("chunk_id").is_in(chunk_ids))
            .select("chunk_id", "chunk_text", "chunk_type", "parent_id", "raw_table_id")
            .collect()
        )
        return {row["chunk_id"]: row for row in rows.iter_rows(named=True)}

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = 20,
        expand: bool = True,
    ) -> list[dict[str, Any]]:
        vector = encode_texts(
            [query],
            self.tokenizer,
            self.model,
            self.device,
            batch_size=1,
            max_length=self.query_max_length,
            is_query=True,
            show_progress=False,
        )[0]
        if self.faiss_indexes:
            points = self._search_faiss(vector, filters, top_k)
        elif self.elasticsearch_client is not None:
            points = self._search_elasticsearch(vector, filters, top_k)
        else:
            raise RuntimeError("DenseRetriever has no active search backend.")
        hits = []
        expansion_ids: list[str] = []
        for score, payload in points:
            parent_id = payload.get("parent_id") or ""
            raw_table_id = payload.get("raw_table_id") or ""
            if expand and payload.get("chunk_type") == "table_summary" and raw_table_id:
                expansion_ids.append(raw_table_id)
            elif expand and payload.get("chunk_type") == "procedure_record":
                expansion_ids.extend(value for value in [parent_id, raw_table_id] if value)
            elif (
                expand
                and payload.get("chunk_type") == "clause_group"
                and parent_id
            ):
                expansion_ids.append(parent_id)
            hits.append(
                {
                    "chunk_id": payload.get("chunk_id"),
                    "dense_score": score,
                    "payload": payload,
                    "citation": format_citation(payload),
                    "optional_expanded_context": None,
                }
            )

        original_ids = [hit["chunk_id"] for hit in hits if hit["chunk_id"]]
        lookup = (
            self._lookup_chunks(list(dict.fromkeys(original_ids + expansion_ids)))
            if expand
            else {}
        )
        for hit in hits:
            payload = hit["payload"]
            own = lookup.get(hit["chunk_id"], {})
            if "chunk_text" not in payload and own.get("chunk_text"):
                payload["chunk_text"] = own["chunk_text"]
            target_id = None
            if payload.get("chunk_type") == "table_summary":
                target_id = payload.get("raw_table_id")
            elif payload.get("chunk_type") == "procedure_record":
                target_id = payload.get("parent_id") or payload.get("raw_table_id")
            elif (
                payload.get("chunk_type") == "clause_group"
                and (
                    hit["dense_score"] < EXPAND_SCORE_THRESHOLD
                    or len(own.get("chunk_text", "")) < EXPAND_MIN_CHARS
                )
            ):
                target_id = payload.get("parent_id")
            if target_id in lookup:
                hit["optional_expanded_context"] = lookup[target_id]["chunk_text"]
        return hits

    def _search_elasticsearch(
        self, vector: np.ndarray, filters: dict[str, Any] | None, top_k: int
    ) -> list[tuple[float, dict[str, Any]]]:
        assert self.elasticsearch_client is not None
        knn: dict[str, Any] = {
            "field": "vector",
            "query_vector": np.asarray(vector, dtype=np.float32).tolist(),
            "k": top_k,
            "num_candidates": resolve_num_candidates(
                top_k,
                self.elastic_num_candidates,
            ),
        }
        filter_clauses = build_elasticsearch_filter(filters)
        if filter_clauses:
            knn["filter"] = filter_clauses
        response = self.elasticsearch_client.search(
            index=self.elastic_index,
            size=top_k,
            knn=knn,
            source_excludes=["vector"],
        )
        return normalize_search_hits(
            response["hits"]["hits"],
            cosine_score=True,
        )

    def _search_faiss(
        self, vector: np.ndarray, filters: dict[str, Any] | None, top_k: int
    ) -> list[tuple[float, dict[str, Any]]]:
        local_k = max(top_k, top_k * self.faiss_oversample if filters else top_k)
        candidates: list[tuple[float, dict[str, Any]]] = []
        query = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        for _, index, payload_table in self.faiss_indexes:
            scores, indices = index.search(query, min(local_k, index.ntotal))
            valid = [(float(score), int(row_id)) for score, row_id in zip(scores[0], indices[0]) if row_id >= 0]
            if not valid:
                continue
            rows = payload_table.take(pa.array([row_id for _, row_id in valid])).to_pylist()
            candidates.extend(
                (score, payload)
                for (score, _), payload in zip(valid, rows, strict=True)
                if payload_matches(payload, filters)
            )
        candidates.sort(key=lambda item: item[0], reverse=True)
        unique: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()
        for score, payload in candidates:
            chunk_id = payload.get("chunk_id")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            unique.append((score, payload))
            if len(unique) == top_k:
                break
        return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--faiss-dir", type=Path)
    target.add_argument("--elastic-cloud-id")
    parser.add_argument("--elastic-api-key", default=None)
    parser.add_argument("--elastic-index", default=COLLECTION_NAME)
    parser.add_argument("--elastic-num-candidates", type=int, default=None)
    parser.add_argument("--query", required=True)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--faiss-nprobe", type=int, default=32)
    parser.add_argument("--faiss-oversample", type=int, default=20)
    parser.add_argument("--filters", default=None, help="JSON object with exact/range filters.")
    parser.add_argument("--no-expand", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    retriever = DenseRetriever(
        faiss_dir=args.faiss_dir,
        model_name=args.model,
        chunks_path=args.chunks,
        device=args.device,
        cache_dir=args.cache_dir,
        faiss_nprobe=args.faiss_nprobe,
        faiss_oversample=args.faiss_oversample,
        elastic_cloud_id=args.elastic_cloud_id,
        elastic_api_key=args.elastic_api_key,
        elastic_index=args.elastic_index,
        elastic_num_candidates=args.elastic_num_candidates,
    )
    try:
        hits = retriever.search(
            args.query,
            filters=json.loads(args.filters) if args.filters else None,
            top_k=args.top_k,
            expand=not args.no_expand,
        )
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
