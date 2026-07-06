"""Evaluate dense retrieval, optionally reranking a larger candidate pool.

Example:
python pipeline/07_evaluation/evaluate_dense.py --gold pipeline/07_evaluation/eval_questions_gold.jsonl --elastic-cloud-id "$ELASTIC_CLOUD_ID" --chunks data/legal_chunking_dataset/chunks.parquet --candidate-k 100 --top-k 10 --rerank --reranker-model BAAI/bge-reranker-v2-m3 --output output/dense_rerank_eval_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent

from pipeline.embedding.dense_retrieval import DenseRetriever
from pipeline.embedding.embedding_common import COLLECTION_NAME, MODEL_NAME, setup_logging
from pipeline.embedding.rerank import DEFAULT_RERANKER_MODEL, BaseReranker, PassageLoader, create_reranker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--faiss-dir", type=Path)
    target.add_argument("--elastic-cloud-id")
    parser.add_argument("--elastic-api-key", default=None)
    parser.add_argument("--elastic-index", default=COLLECTION_NAME)
    parser.add_argument("--elastic-num-candidates", type=int, default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--faiss-nprobe", type=int, default=32)
    parser.add_argument("--faiss-oversample", type=int, default=20)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "dense_eval_results.json",
                        help="Path to save evaluation results JSON")
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
    hits: list[dict[str, Any]], row: dict[str, Any], k_values: list[int]
) -> dict[str, float]:
    metrics = {}
    for k in k_values:
        rel = evaluate_hits_relevance(hits[:k], row)
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
        ideal_hits = min(relevant_total, k)
        idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
        
        metrics[f"recall@{k}"] = min(sum(rel) / relevant_total, 1.0)
        metrics[f"mrr@{k}"] = 1.0 / first if first else 0.0
        metrics[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    return metrics


def summarize(details: list[dict[str, Any]], k_values: list[int], prefix: str = "") -> dict[str, Any]:
    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        metric_key = f"{prefix}{key}"
        return sum(item[metric_key] for item in subset) / len(subset) if subset else 0.0

    groups = sorted({item["group"] for item in details})
    summary: dict[str, Any] = {"queries": len(details)}
    
    for k in k_values:
        summary[f"recall@{k}"] = mean(f"recall@{k}", details)
        summary[f"mrr@{k}"] = mean(f"mrr@{k}", details)
        summary[f"ndcg@{k}"] = mean(f"ndcg@{k}", details)
        
    summary["by_group"] = {}
    for group in groups:
        subset = [item for item in details if item["group"] == group]
        group_summary: dict[str, Any] = {"queries": len(subset)}
        for k in k_values:
            group_summary[f"recall@{k}"] = mean(f"recall@{k}", subset)
            group_summary[f"mrr@{k}"] = mean(f"mrr@{k}", subset)
            group_summary[f"ndcg@{k}"] = mean(f"ndcg@{k}", subset)
        summary["by_group"][group] = group_summary

    return summary


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
    reranker: BaseReranker | None = None
    passage_loader: PassageLoader | None = None
    if args.rerank:
        if args.chunks is None:
            logging.warning(
                "--chunks was not provided; reranking passages will rely only on "
                "Elasticsearch/FAISS payload fields and may have empty chunk text"
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

            dense_metrics = metrics_for_hits(dense_hits, row, args.k_values)
            final_metrics = metrics_for_hits(final_hits, row, args.k_values)
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
        **summarize(details, args.k_values),
        "candidate_k": args.candidate_k,
        "rerank_enabled": args.rerank,
        "reranker_loaded": reranker is not None,
        "reranker_model": args.reranker_model if args.rerank else None,
        "dense_baseline_metrics": summarize(details, args.k_values, prefix="dense_"),
        "details": details,
    }
    if args.rerank:
        report["rerank_metrics"] = summarize(details, args.k_values)
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
