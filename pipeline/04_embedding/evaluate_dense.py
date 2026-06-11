"""Evaluate dense retrieval, optionally reranking a larger candidate pool.

Example:
python pipeline/04_embedding/evaluate_dense.py --gold pipeline/07_evaluation/eval_questions_gold.jsonl --url http://129.212.184.109:8333/ --chunks data/legal_chunking_dataset/chunks.parquet --candidate-k 100 --top-k 10 --rerank --reranker-model BAAI/bge-reranker-v2-m3 --output data/legal_embedding/dense_rerank_eval_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any

from dense_retrieval import DenseRetriever
from embedding_common import COLLECTION_NAME, MODEL_NAME, setup_logging
from rerank import DEFAULT_RERANKER_MODEL, BaseReranker, PassageLoader, create_reranker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--storage-dir", type=Path)
    target.add_argument("--url")
    target.add_argument("--faiss-dir", type=Path)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--faiss-nprobe", type=int, default=32)
    parser.add_argument("--faiss-oversample", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--cache-dir", default=None)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def evaluate_hits_relevance(hits: list[dict[str, Any]], row: dict[str, Any]) -> list[int]:
    groups = row.get("relevant_chunk_groups")
    if not groups:
        chunk_ids = set(row.get("relevant_chunk_ids") or [])
        doc_ids = set(row.get("relevant_doc_ids") or [])
        return [
            int(
                hit.get("chunk_id") in chunk_ids
                or hit.get("payload", {}).get("doc_id") in doc_ids
            )
            for hit in hits
        ]

    rel: list[int] = []
    matched_groups: set[int] = set()
    for hit in hits:
        hit_id = hit.get("chunk_id")
        matched = False
        for g_idx, group in enumerate(groups):
            if hit_id in group:
                if g_idx not in matched_groups:
                    matched_groups.add(g_idx)
                    rel.append(1)
                    matched = True
                    break
        if not matched:
            rel.append(0)
    return rel


def deduplicate_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = []
    seen: set[str] = set()
    for hit in hits:
        chunk_id = hit.get("chunk_id")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        unique.append(hit)
    return unique


def metrics_for_hits(
    hits: list[dict[str, Any]], row: dict[str, Any], top_k: int
) -> dict[str, float]:
    rel = evaluate_hits_relevance(hits[:top_k], row)
    first = next((index + 1 for index, value in enumerate(rel) if value), None)
    relevant_total = max(
        len(
            row.get("relevant_chunk_groups")
            or row.get("relevant_chunk_ids")
            or row.get("relevant_doc_ids")
            or []
        ),
        1,
    )
    dcg = sum(value / math.log2(index + 2) for index, value in enumerate(rel))
    ideal_hits = min(relevant_total, top_k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return {
        "recall": min(sum(rel) / relevant_total, 1.0),
        "mrr": 1.0 / first if first else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
    }


def summarize(details: list[dict[str, Any]], top_k: int, prefix: str = "") -> dict[str, Any]:
    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        metric_key = f"{prefix}{key}"
        return sum(item[metric_key] for item in subset) / len(subset) if subset else 0.0

    groups = sorted({item["group"] for item in details})
    return {
        "queries": len(details),
        f"recall@{top_k}": mean("recall", details),
        f"mrr@{top_k}": mean("mrr", details),
        f"ndcg@{top_k}": mean("ndcg", details),
        "by_group": {
            group: {
                "queries": len(subset := [item for item in details if item["group"] == group]),
                f"recall@{top_k}": mean("recall", subset),
                f"mrr@{top_k}": mean("mrr", subset),
                f"ndcg@{top_k}": mean("ndcg", subset),
            }
            for group in groups
        },
    }


def main() -> None:
    args = parse_args()
    setup_logging()
    if args.candidate_k <= 0 or args.top_k <= 0:
        raise ValueError("--candidate-k and --top-k must be positive")
    if args.rerank and args.candidate_k <= args.top_k:
        raise ValueError("--candidate-k must be greater than --top-k when --rerank is enabled")
    if args.rerank_batch_size <= 0:
        raise ValueError("--rerank-batch-size must be positive")
    rows = load_jsonl(args.gold)
    retriever = DenseRetriever(
        args.storage_dir,
        url=args.url,
        faiss_dir=args.faiss_dir,
        api_key=args.api_key,
        collection=args.collection,
        model_name=args.model,
        chunks_path=args.chunks,
        device=args.device,
        cache_dir=args.cache_dir,
        faiss_nprobe=args.faiss_nprobe,
        faiss_oversample=args.faiss_oversample,
    )
    reranker: BaseReranker | None = None
    passage_loader: PassageLoader | None = None
    if args.rerank:
        if args.chunks is None:
            logging.warning(
                "--chunks was not provided; reranking passages will rely only on "
                "Qdrant/FAISS payload fields and may have empty chunk text"
            )
        try:
            passage_loader = PassageLoader(args.chunks)
            reranker = create_reranker(
                args.reranker_model, device=args.device, cache_dir=args.cache_dir
            )
        except Exception:
            reranker = None
            passage_loader = None
            logging.warning(
                "Failed to initialize reranker %s; using dense order for all queries",
                args.reranker_model,
                exc_info=True,
            )

    details: list[dict[str, Any]] = []
    try:
        for row in rows:
            candidates = deduplicate_hits(
                retriever.search(
                    row["query"],
                    filters=row.get("filters"),
                    top_k=args.candidate_k if args.rerank else args.top_k,
                    expand=False,
                )
            )
            dense_hits = candidates[: args.top_k]
            final_hits = dense_hits
            rerank_scores: list[float] | None = None
            if args.rerank and reranker is not None:
                try:
                    assert passage_loader is not None
                    passages = passage_loader.build_passages(candidates)
                    rerank_scores = reranker.score_pairs(
                        [(row["query"], passage) for passage in passages],
                        batch_size=args.rerank_batch_size,
                    )
                    scored = list(zip(candidates, rerank_scores, strict=True))
                    scored.sort(key=lambda item: item[1], reverse=True)
                    final_hits = [
                        {**hit, "rerank_score": score}
                        for hit, score in scored[: args.top_k]
                    ]
                except Exception:
                    logging.warning(
                        "Reranking failed for query %r; using dense order",
                        row["query"],
                        exc_info=True,
                    )
                    rerank_scores = None

            dense_metrics = metrics_for_hits(dense_hits, row, args.top_k)
            final_metrics = metrics_for_hits(final_hits, row, args.top_k)
            details.append(
                {
                    "query": row["query"],
                    "group": row.get("group", "unknown"),
                    **final_metrics,
                    **{f"dense_{key}": value for key, value in dense_metrics.items()},
                    "top_chunk_ids": [hit["chunk_id"] for hit in final_hits],
                    "baseline_dense_scores": [
                        {"chunk_id": hit["chunk_id"], "score": hit["dense_score"]}
                        for hit in candidates
                    ],
                    "rerank_scores": (
                        [
                            {"chunk_id": hit["chunk_id"], "score": score}
                            for hit, score in zip(candidates, rerank_scores, strict=True)
                        ]
                        if rerank_scores is not None
                        else None
                    ),
                    "final_ordered_results": [
                        {
                            "chunk_id": hit["chunk_id"],
                            "dense_score": hit["dense_score"],
                            "rerank_score": hit.get("rerank_score"),
                        }
                        for hit in final_hits
                    ],
                }
            )
    finally:
        retriever.close()

    report = {
        **summarize(details, args.top_k),
        "candidate_k": args.candidate_k,
        "rerank_enabled": args.rerank,
        "reranker_loaded": reranker is not None,
        "reranker_model": args.reranker_model if args.rerank else None,
        "dense_baseline_metrics": summarize(details, args.top_k, prefix="dense_"),
        "details": details,
    }
    if args.rerank:
        report["rerank_metrics"] = summarize(details, args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "details"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
