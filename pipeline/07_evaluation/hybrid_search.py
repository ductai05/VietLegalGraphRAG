"""Hybrid search using Dense + Sparse retrieval, RRF combination, and BGE reranking."""

from __future__ import annotations

import os
import sys
import json
import math
import argparse
import logging
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# Ensure proxy environment variables are clean
for _key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_key, None)

# Add pipeline/04_embedding and pipeline/05_sparse_retrieval to path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR / "pipeline" / "04_embedding"))
sys.path.append(str(BASE_DIR / "pipeline" / "05_sparse_retrieval"))

from dense_retrieval import format_citation
from embedding_common import encode_texts, load_encoder, COLLECTION_NAME, MODEL_NAME, setup_logging
from elasticsearch_common import build_elasticsearch_filter, resolve_num_candidates
from src.elastic_client import build_elasticsearch_client
from src.tokenizer import tokenize_vi
from rerank import DEFAULT_RERANKER_MODEL, BaseReranker, PassageLoader, create_reranker


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


def mean(key: str, subset: list[dict[str, Any]]) -> float:
    return sum(item[key] for item in subset) / len(subset) if subset else 0.0


def summarize(details: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
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


class HybridRetriever:
    def __init__(
        self,
        url: str,
        dense_index: str = COLLECTION_NAME,
        sparse_index: str = "vietlegal_chunks_sparse_current",
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        model_name: str = MODEL_NAME,
        device: str | None = None,
        cache_dir: str | None = None,
        query_max_length: int = 512,
        elastic_num_candidates: int | None = None,
    ) -> None:
        self.client = build_elasticsearch_client(
            url,
            api_key=api_key,
            username=username,
            password=password,
        )
        self.dense_index = dense_index
        self.sparse_index = sparse_index
        self.elastic_num_candidates = elastic_num_candidates
        self.query_max_length = query_max_length

        # Load dense query encoder model on CPU to conserve GPU memory for the reranker
        self.tokenizer, self.model, self.device, _ = load_encoder(
            model_name, "cpu", cache_dir
        )
        logging.info("Initialized HybridRetriever with dense index: %s, sparse index: %s", dense_index, sparse_index)

    def close(self) -> None:
        self.client.close()

    def hybrid_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        candidate_k: int = 100,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        # 1. Dense Search
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

        knn: dict[str, Any] = {
            "field": "vector",
            "query_vector": np.asarray(vector, dtype=np.float32).tolist(),
            "k": candidate_k,
            "num_candidates": resolve_num_candidates(
                candidate_k,
                self.elastic_num_candidates,
            ),
        }
        dense_filters = build_elasticsearch_filter(filters)
        if dense_filters:
            knn["filter"] = dense_filters

        dense_response = self.client.search(
            index=self.dense_index,
            size=candidate_k,
            knn=knn,
            source_excludes=["vector"],
        )

        dense_hits = []
        for idx, hit in enumerate(dense_response["hits"]["hits"]):
            payload = dict(hit.get("_source") or {})
            payload.pop("vector", None)
            chunk_id = payload.get("chunk_id")
            if chunk_id:
                dense_hits.append({
                    "chunk_id": str(chunk_id),
                    "score": float(hit.get("_score") or 0.0),
                    "rank": idx,
                    "payload": payload
                })

        # 2. Sparse Search
        tokenized_query = tokenize_vi(query)
        sparse_body: dict[str, Any] = {
            "size": candidate_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": tokenized_query,
                                "fields": [
                                    "chunk_text_vi^3.0",
                                    "contextual_text_vi^1.5",
                                    "title_vi^2.0",
                                    "section_path_vi^1.0",
                                    "procedure_name_vi^1.5"
                                ],
                                "analyzer": "vi_whitespace"
                            }
                        }
                    ]
                }
            }
        }
        if filters:
            filter_clauses = []
            for key, val in filters.items():
                if key == "ranges":
                    for r_key, r_val in val.items():
                        filter_clauses.append({"range": {r_key: r_val}})
                else:
                    if isinstance(val, list):
                        filter_clauses.append({"terms": {key: val}})
                    else:
                        filter_clauses.append({"term": {key: val}})
            sparse_body["query"]["bool"]["filter"] = filter_clauses

        sparse_response = self.client.search(
            index=self.sparse_index,
            body=sparse_body
        )

        sparse_hits = []
        for idx, hit in enumerate(sparse_response["hits"]["hits"]):
            payload = hit.get("_source") or {}
            chunk_id = payload.get("chunk_id")
            if chunk_id:
                sparse_hits.append({
                    "chunk_id": str(chunk_id),
                    "score": float(hit.get("_score") or 0.0),
                    "rank": idx,
                    "payload": payload
                })

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: dict[str, float] = {}
        merged_payloads: dict[str, dict[str, Any]] = {}
        dense_scores_dict: dict[str, float] = {}
        sparse_scores_dict: dict[str, float] = {}

        for hit in dense_hits:
            chunk_id = hit["chunk_id"]
            dense_scores_dict[chunk_id] = hit["score"]
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + hit["rank"])
            merged_payloads[chunk_id] = hit["payload"]

        for hit in sparse_hits:
            chunk_id = hit["chunk_id"]
            sparse_scores_dict[chunk_id] = hit["score"]
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + hit["rank"])
            if chunk_id not in merged_payloads:
                merged_payloads[chunk_id] = hit["payload"]
            else:
                merged_payloads[chunk_id].update(hit["payload"])

        # Sort all candidates by RRF score descending
        sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        # Hydrate missing metadata/chunk_text using mget from the sparse index
        missing_ids = [cid for cid in sorted_chunk_ids[:candidate_k] if not merged_payloads[cid].get("chunk_text")]
        if missing_ids:
            try:
                mget_res = self.client.mget(
                    index=self.sparse_index,
                    ids=missing_ids,
                    source=["chunk_text", "legal_type", "document_number", "title", "issuing_authority", "effect_status", "effect_date", "legal_sectors", "linh_vuc"]
                )
                for doc in mget_res.get("docs", []):
                    if doc.get("found"):
                        cid = doc["_id"]
                        merged_payloads[cid].update(doc["_source"])
            except Exception as e:
                logging.warning("Failed to hydrate missing chunk metadata via mget: %s", e)

        candidates = []
        for chunk_id in sorted_chunk_ids[:candidate_k]:
            candidates.append({
                "chunk_id": chunk_id,
                "score": rrf_scores[chunk_id],  # Primary score
                "dense_score": dense_scores_dict.get(chunk_id, 0.0),
                "sparse_score": sparse_scores_dict.get(chunk_id, 0.0),
                "payload": merged_payloads[chunk_id],
                "citation": format_citation(merged_payloads[chunk_id]),
                "optional_expanded_context": None,
            })

        return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Elasticsearch URL")
    parser.add_argument("--api-key", default=None, help="Elasticsearch API key")
    parser.add_argument("--username", default=None, help="Elasticsearch username")
    parser.add_argument("--password", default=None, help="Elasticsearch password")
    parser.add_argument("--dense-index", default=COLLECTION_NAME, help="Dense vector index name")
    parser.add_argument("--sparse-index", default="vietlegal_chunks_sparse_current", help="Sparse index name")
    
    # Modes
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Single query string to test search")
    group.add_argument("--gold", type=Path, help="Path to gold evaluation json file")
    
    # Reranking & Chunks
    parser.add_argument("--chunks", type=Path, default=None, help="Path to chunks.parquet to hydrate full metadata")
    parser.add_argument("--candidate-k", type=int, default=100, help="RRF candidate pool size")
    parser.add_argument("--top-k", type=int, default=10, help="Final return top_k")
    parser.add_argument("--rerank", action="store_true", help="Enable cross-encoder reranking")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL, help="Hugging Face reranker model name")
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--device", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--output", type=Path, help="Path to save evaluation output results JSON")
    
    return parser.parse_args()


def main() -> None:
    # Handle Windows console UTF-8 issues
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args()
    setup_logging()

    # Setup reranker first (on GPU) to avoid CUDA state conflicts with CPU query encoder initialization
    reranker = None
    passage_loader = None
    if args.rerank:
        print(f"Loading reranker model: {args.reranker_model}...")
        passage_loader = PassageLoader(args.chunks)
        reranker = create_reranker(args.reranker_model, device=args.device, cache_dir=args.cache_dir)

    # Initialize retriever
    retriever = HybridRetriever(
        url=args.url,
        dense_index=args.dense_index,
        sparse_index=args.sparse_index,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        device=args.device,
        cache_dir=args.cache_dir,
    )

    try:
        # 1. Single Query Mode
        if args.query:
            print(f"\nQuerying: {args.query}")
            candidates = retriever.hybrid_search(
                args.query,
                candidate_k=args.candidate_k
            )
            print(f"Retrieved {len(candidates)} candidates via RRF.")
            
            final_hits = candidates
            if args.rerank and reranker is not None:
                passages = passage_loader.build_passages(candidates)
                print("Scoring candidate pairs...")
                rerank_scores = reranker.score_pairs(
                    [(args.query, passage) for passage in passages],
                    batch_size=args.rerank_batch_size,
                )
                scored = sorted(
                    zip(candidates, rerank_scores, strict=True),
                    key=lambda item: item[1],
                    reverse=True
                )
                final_hits = []
                for hit, score in scored[:args.top_k]:
                    hit["rerank_score"] = score
                    final_hits.append(hit)
            else:
                final_hits = candidates[:args.top_k]

            print(f"\nTop {args.top_k} results:")
            for idx, hit in enumerate(final_hits):
                score_str = f"Rerank Score: {hit['rerank_score']:.4f}" if "rerank_score" in hit else f"RRF Score: {hit['score']:.4f}"
                print(f"[{idx+1}] {score_str} | Chunk ID: {hit['chunk_id']}")
                print(f"Citation: {hit['citation']}")
                print(f"Text Preview: {hit['payload'].get('chunk_text', '')[:200]}...\n" + "-"*50)

        # 2. Evaluation Mode
        elif args.gold:
            print(f"\nRunning evaluation on gold file: {args.gold}")
            rows = load_jsonl(args.gold) if args.gold.suffix == ".jsonl" else json.loads(args.gold.read_text(encoding="utf-8"))
            if isinstance(rows, dict) and "questions" in rows:
                rows = rows["questions"]
            
            details = []
            for i, row in enumerate(rows):
                candidates = retriever.hybrid_search(
                    row["query"],
                    filters=row.get("filters"),
                    candidate_k=args.candidate_k
                )

                rrf_hits = candidates[:args.top_k]
                final_hits = rrf_hits
                rerank_scores = None

                if args.rerank and reranker is not None:
                    try:
                        passages = passage_loader.build_passages(candidates)
                        rerank_scores = reranker.score_pairs(
                            [(row["query"], passage) for passage in passages],
                            batch_size=args.rerank_batch_size,
                        )
                        scored = sorted(
                            zip(candidates, rerank_scores, strict=True),
                            key=lambda item: item[1],
                            reverse=True
                        )
                        final_hits = []
                        for hit, score in scored[:args.top_k]:
                            h = dict(hit)
                            h["rerank_score"] = score
                            final_hits.append(h)
                    except Exception:
                        logging.warning("Reranking failed for query %r, falling back to RRF order.", row["query"], exc_info=True)
                        final_hits = rrf_hits

                rrf_metrics = metrics_for_hits(rrf_hits, row, args.top_k)
                final_metrics = metrics_for_hits(final_hits, row, args.top_k)

                details.append({
                    "query": row["query"],
                    "group": row.get("group", "unknown"),
                    "recall": final_metrics["recall"],
                    "mrr": final_metrics["mrr"],
                    "ndcg": final_metrics["ndcg"],
                    "rrf_recall": rrf_metrics["recall"],
                    "rrf_mrr": rrf_metrics["mrr"],
                    "rrf_ndcg": rrf_metrics["ndcg"],
                    "top_chunk_ids": [hit["chunk_id"] for hit in final_hits],
                    "final_ordered_results": [
                        {
                            "chunk_id": hit["chunk_id"],
                            "score": hit["score"],
                            "rerank_score": hit.get("rerank_score")
                        } for hit in final_hits
                    ]
                })

                if (i + 1) % 50 == 0:
                    print(f"Processed {i + 1}/{len(rows)} queries...")

            # Summarize results
            report = {
                "queries": len(details),
                "recall@10": mean("recall", details),
                "mrr@10": mean("mrr", details),
                "ndcg@10": mean("ndcg", details),
                "rrf_metrics": {
                    "recall@10": mean("rrf_recall", details),
                    "mrr@10": mean("rrf_mrr", details),
                    "ndcg@10": mean("rrf_ndcg", details),
                },
                "by_group": {
                    group: {
                        "queries": len(subset := [item for item in details if item["group"] == group]),
                        "recall@10": mean("recall", subset),
                        "mrr@10": mean("mrr", subset),
                        "ndcg@10": mean("ndcg", subset),
                    } for group in sorted({item["group"] for item in details})
                },
                "details": details
            }

            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Results saved to: {args.output}")

            print("\nEvaluation Completed!")
            print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2))

    finally:
        retriever.close()


if __name__ == "__main__":
    main()
