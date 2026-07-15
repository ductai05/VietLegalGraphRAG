"""Hybrid search using Dense + Sparse retrieval, RRF combination, and BGE reranking."""

from __future__ import annotations

import os
import sys
import json
import math
import argparse
import logging
import concurrent.futures
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# Ensure proxy environment variables are clean
for _key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_key, None)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = Path(__file__).resolve().parents[1]
DENSE_SRC = PIPELINE_DIR / "03_embeddings" / "dense" / "src"
SPARSE_SRC = PIPELINE_DIR / "03_embeddings" / "sparse" / "src"
for _path in [DENSE_SRC, SPARSE_SRC]:
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dense_retrieval import format_citation
from embedding_common import encode_texts, load_encoder, COLLECTION_NAME, MODEL_NAME, setup_logging
from elasticsearch_common import build_elasticsearch_filter, resolve_num_candidates
from elastic_client import build_elasticsearch_client
from tokenizer import tokenize_vi
from rerank import DEFAULT_RERANKER_MODEL, BaseReranker, PassageLoader, create_reranker

DEFAULT_HYBRID_QUERY = "thủ tục cấp giấy phép xây dựng"
DEFAULT_RRF_K = 60


def load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                os.environ[key] = value


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


def mean(key: str, subset: list[dict[str, Any]]) -> float:
    return sum(item[key] for item in subset) / len(subset) if subset else 0.0


def summarize(details: list[dict[str, Any]], k_values: list[int], prefix: str = "") -> dict[str, Any]:
    groups = sorted({item["group"] for item in details})
    summary: dict[str, Any] = {"queries": len(details)}
    
    for k in k_values:
        summary[f"{prefix}recall@{k}"] = mean(f"{prefix}recall@{k}", details)
        summary[f"{prefix}mrr@{k}"] = mean(f"{prefix}mrr@{k}", details)
        summary[f"{prefix}ndcg@{k}"] = mean(f"{prefix}ndcg@{k}", details)
        
    summary["by_group"] = {}
    for group in groups:
        subset = [item for item in details if item["group"] == group]
        group_summary: dict[str, Any] = {"queries": len(subset)}
        for k in k_values:
            group_summary[f"{prefix}recall@{k}"] = mean(f"{prefix}recall@{k}", subset)
            group_summary[f"{prefix}mrr@{k}"] = mean(f"{prefix}mrr@{k}", subset)
            group_summary[f"{prefix}ndcg@{k}"] = mean(f"{prefix}ndcg@{k}", subset)
        summary["by_group"][group] = group_summary

    return summary


def fuse_ranked_hits(
    dense_hits: Sequence[dict[str, Any]],
    sparse_hits: Sequence[dict[str, Any]],
    *,
    candidate_k: int,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    rrf_scores: dict[str, float] = {}
    merged_payloads: dict[str, dict[str, Any]] = {}
    dense_scores: dict[str, float] = {}
    sparse_scores: dict[str, float] = {}
    retrieval_sources: dict[str, set[str]] = {}

    def add_hit(hit: dict[str, Any], source: str) -> None:
        chunk_id = str(hit["chunk_id"])
        rank = int(hit["rank"])
        if rank <= 0:
            raise ValueError("RRF ranks must be 1-based positive integers")
        score = float(hit.get("score") or 0.0)
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        retrieval_sources.setdefault(chunk_id, set()).add(source)
        if source == "dense":
            dense_scores[chunk_id] = score
        else:
            sparse_scores[chunk_id] = score
        if chunk_id not in merged_payloads:
            merged_payloads[chunk_id] = dict(hit.get("payload") or {})
        else:
            merged_payloads[chunk_id].update(hit.get("payload") or {})

    for hit in dense_hits:
        add_hit(hit, "dense")
    for hit in sparse_hits:
        add_hit(hit, "sparse")

    sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda item: rrf_scores[item], reverse=True)
    candidates = []
    for chunk_id in sorted_chunk_ids[:candidate_k]:
        payload = merged_payloads[chunk_id]
        candidates.append(
            {
                "chunk_id": chunk_id,
                "score": rrf_scores[chunk_id],
                "dense_score": dense_scores.get(chunk_id, 0.0),
                "sparse_score": sparse_scores.get(chunk_id, 0.0),
                "retrieval_sources": sorted(retrieval_sources.get(chunk_id, set())),
                "payload": payload,
                "citation": format_citation(payload),
                "optional_expanded_context": None,
            }
        )
    return candidates


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
                    "rank": idx + 1,
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
                    "rank": idx + 1,
                    "payload": payload
                })

        # 3. Reciprocal Rank Fusion (RRF)
        candidates = fuse_ranked_hits(
            dense_hits,
            sparse_hits,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
        )

        # Hydrate missing metadata/chunk_text using mget from the sparse index
        missing_ids = [
            hit["chunk_id"]
            for hit in candidates
            if not hit["payload"].get("chunk_text")
        ]
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
                        for hit in candidates:
                            if hit["chunk_id"] == cid:
                                hit["payload"].update(doc["_source"])
                                hit["citation"] = format_citation(hit["payload"])
                                break
            except Exception as e:
                logging.warning("Failed to hydrate missing chunk metadata via mget: %s", e)

        return candidates


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)
    load_env_file(pre_args.env_file)

    default_index = (
        os.getenv("ELASTICSEARCH_ALIAS")
        or os.getenv("ELASTICSEARCH_INDEX")
        or COLLECTION_NAME
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=pre_args.env_file)
    parser.add_argument("--url", default=os.getenv("ELASTICSEARCH_URL") or os.getenv("ELASTIC_URL"), help="Elasticsearch URL")
    parser.add_argument("--api-key", default=os.getenv("ELASTICSEARCH_API_KEY") or os.getenv("ELASTIC_API_KEY"), help="Elasticsearch API key")
    parser.add_argument("--username", default=os.getenv("ELASTICSEARCH_USERNAME") or os.getenv("ELASTIC_USERNAME"), help="Elasticsearch username")
    parser.add_argument("--password", default=os.getenv("ELASTICSEARCH_PASSWORD") or os.getenv("ELASTIC_PASSWORD"), help="Elasticsearch password")
    parser.add_argument("--index", default=None, help="Single hybrid index/alias to use for both dense and sparse search")
    parser.add_argument("--dense-index", default=None, help="Dense vector index name")
    parser.add_argument("--sparse-index", default=None, help="Sparse text index name")
    
    # Modes
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="Single query string to test search")
    group.add_argument("--gold", type=Path, help="Path to gold evaluation json file")
    
    # Reranking & Chunks
    parser.add_argument("--chunks", type=Path, default=None, help="Path to chunks.parquet to hydrate full metadata")
    parser.add_argument("--candidate-k", type=int, default=100, help="RRF candidate pool size")
    parser.add_argument("--top-k", type=int, default=10, help="Final return top_k")
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K, help="RRF rank constant. Higher values soften rank differences.")
    parser.add_argument("--elastic-num-candidates", type=int, default=None, help="Elasticsearch kNN num_candidates override")
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5, 10], help="List of k values for evaluation metrics")
    parser.add_argument("--rerank", action="store_true", help="Enable cross-encoder reranking")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL, help="Hugging Face reranker model name")
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--max-workers", type=int, default=10, help="Number of concurrent threads for retrieval")
    parser.add_argument("--device", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "hybrid_eval_results.json", help="Path to save evaluation output results JSON")
    args = parser.parse_args(argv)
    if args.index:
        args.dense_index = args.index
        args.sparse_index = args.index
    else:
        args.dense_index = args.dense_index or default_index
        args.sparse_index = args.sparse_index or default_index
    if args.query is None and args.gold is None:
        args.query = DEFAULT_HYBRID_QUERY
    if not args.url:
        raise ValueError("Missing Elasticsearch URL. Set ELASTICSEARCH_URL or pass --url.")
    if not args.api_key and not (args.username and args.password):
        raise ValueError(
            "Missing Elasticsearch credentials. Set ELASTICSEARCH_API_KEY "
            "or ELASTICSEARCH_USERNAME/ELASTICSEARCH_PASSWORD."
        )
    if args.candidate_k <= 0:
        raise ValueError("--candidate-k must be positive")
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    if args.rrf_k <= 0:
        raise ValueError("--rrf-k must be positive")
    if args.elastic_num_candidates is not None and args.elastic_num_candidates <= 0:
        raise ValueError("--elastic-num-candidates must be positive")
    if args.rerank and args.candidate_k <= args.top_k:
        raise ValueError("--candidate-k must be greater than --top-k when --rerank is enabled")
    if args.rerank_batch_size <= 0:
        raise ValueError("--rerank-batch-size must be positive")
    return args


def convert_to_gold_jsonl(eval_file: Path, chunks_file: Path | None = None) -> Path:
    import convert_eval_to_gold
    convert_eval_to_gold.EVAL_FILE = eval_file
    convert_eval_to_gold.GOLD_FILE = eval_file.parent / "eval_questions_gold_hybrid.jsonl"
    if chunks_file:
        convert_eval_to_gold.CHUNKS_FILE = chunks_file
    convert_eval_to_gold.main()
    return convert_eval_to_gold.GOLD_FILE


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
        elastic_num_candidates=args.elastic_num_candidates,
    )

    try:
        # 1. Single Query Mode
        if args.query:
            print(f"\nQuerying: {args.query}")
            candidates = retriever.hybrid_search(
                args.query,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
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
            gold_file = args.gold
            is_temp_gold = False
            if args.gold.suffix != ".jsonl":
                print("\nConverting evaluation file to gold standard...")
                gold_file = convert_to_gold_jsonl(args.gold, chunks_file=args.chunks)
                is_temp_gold = True

            print(f"\nRunning evaluation on gold file: {gold_file}")
            rows = load_jsonl(gold_file)
            
            details = []
            def process_retrieval(row: dict[str, Any]) -> list[dict[str, Any]]:
                return retriever.hybrid_search(
                    row["query"],
                    filters=row.get("filters"),
                    candidate_k=args.candidate_k,
                    rrf_k=args.rrf_k,
                )

            try:
                from tqdm import tqdm
            except ImportError:
                tqdm = lambda x, **kwargs: x

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                all_candidates = list(tqdm(executor.map(process_retrieval, rows), total=len(rows), desc="Retrieving Hybrid Candidates"))

            if args.rerank and reranker is not None:
                assert passage_loader is not None
                all_pairs = []
                pair_indices = []
                for q_idx, (row, candidates) in enumerate(zip(rows, all_candidates)):
                    try:
                        passages = passage_loader.build_passages(candidates)
                        for c_idx, passage in enumerate(passages):
                            all_pairs.append((row["query"], passage))
                            pair_indices.append((q_idx, c_idx))
                    except Exception:
                        logging.warning("Failed to build passages for query %r", row["query"], exc_info=True)
                
                if all_pairs:
                    print(f"Reranking {len(all_pairs)} pairs globally...")
                    try:
                        global_scores = reranker.score_pairs(all_pairs, batch_size=args.rerank_batch_size)
                        for (q_idx, c_idx), score in zip(pair_indices, global_scores):
                            all_candidates[q_idx][c_idx]["rerank_score"] = score
                    except Exception:
                        logging.warning("Global reranking failed; falling back to RRF order", exc_info=True)

            for row, candidates in zip(rows, all_candidates):
                rrf_hits = candidates[:max(args.k_values)]
                final_hits = rrf_hits

                if args.rerank and reranker is not None:
                    valid_candidates = [c.copy() for c in candidates if "rerank_score" in c]
                    if valid_candidates:
                        valid_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
                        final_hits = valid_candidates[:max(args.k_values)]

                rrf_metrics = metrics_for_hits(rrf_hits, row, args.k_values)
                final_metrics = metrics_for_hits(final_hits, row, args.k_values)

                details.append({
                    "query": row["query"],
                    "group": row.get("group", "unknown"),
                    **final_metrics,
                    **{f"rrf_{key}": value for key, value in rrf_metrics.items()},
                    "top_chunk_ids": [hit["chunk_id"] for hit in final_hits],
                    "final_ordered_results": [
                        {
                            "chunk_id": hit["chunk_id"],
                            "score": hit["score"],
                            "rerank_score": hit.get("rerank_score")
                        } for hit in final_hits
                    ]
                })

            # Summarize results
            report = {
                **summarize(details, args.k_values),
                "rrf_metrics": summarize(details, args.k_values, prefix="rrf_"),
                "rerank_enabled": args.rerank,
                "reranker_model": args.reranker_model if args.rerank else None,
                "rrf_strategy": {
                    "dense_index": args.dense_index,
                    "sparse_index": args.sparse_index,
                    "candidate_k": args.candidate_k,
                    "rrf_k": args.rrf_k,
                    "elastic_num_candidates": args.elastic_num_candidates,
                    "fusion": "RRF score = sum(1 / (rrf_k + 1-based rank)) over dense and sparse result lists",
                    "rerank_input": "top candidate_k RRF candidates",
                },
                "details": details
            }

            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Results saved to: {args.output}")

            print("\nEvaluation Completed!")
            print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2))

            if is_temp_gold:
                gold_file.unlink(missing_ok=True)

    finally:
        retriever.close()


if __name__ == "__main__":
    main()
