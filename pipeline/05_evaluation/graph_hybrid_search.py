"""Hybrid search with Knowledge Graph expansion followed by Cross-Encoder Reranking."""

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

from hybrid_search import load_env_file, load_jsonl, metrics_for_hits, summarize, fuse_ranked_hits, HybridRetriever, DEFAULT_HYBRID_QUERY, DEFAULT_RRF_K

class GraphHybridRetriever(HybridRetriever):
    def __init__(
        self,
        *args,
        neo4j_driver=None,
        neo4j_database: str = "neo4j",
        **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.neo4j_driver = neo4j_driver
        self.neo4j_database = neo4j_database

    def batch_get_doc_ids_from_chunks(self, chunk_ids: set[str]) -> dict[str, str]:
        if not chunk_ids or not self.neo4j_driver:
            return {}
        query = """
        UNWIND $chunk_ids AS cid
        MATCH (c) WHERE c.chunk_id = cid
        OPTIONAL MATCH (c)<-[:HAS_CHUNK]-(d:Document)
        RETURN c.chunk_id AS chunk_id, COALESCE(c.doc_id, d.doc_id, d.id) AS doc_id
        """
        mapping = {}
        with self.neo4j_driver.session(database=self.neo4j_database) as session:
            records = session.run(query, chunk_ids=list(chunk_ids))
            for record in records:
                if record["doc_id"]:
                    doc_id = str(record["doc_id"]).strip()
                    if doc_id.startswith("doc:"):
                        doc_id = doc_id[4:]
                    mapping[record["chunk_id"]] = doc_id
        return mapping

    def get_document_neighbors(self, doc_ids: list[str]) -> list[str]:
        if not doc_ids or not self.neo4j_driver:
            return []
        query = """
        UNWIND $doc_ids AS did
        MATCH (d:Document) WHERE toString(d.doc_id) = toString(did) OR d.id = did OR d.id = "doc:" + did
        MATCH (d)-[:AMENDS|GUIDELINES]-(neighbor:Document)
        RETURN DISTINCT COALESCE(neighbor.doc_id, neighbor.id) AS neighbor_id
        """
        neighbors = []
        with self.neo4j_driver.session(database=self.neo4j_database) as session:
            records = session.run(query, doc_ids=doc_ids)
            for r in records:
                nid = str(r["neighbor_id"] or "").strip()
                if nid.startswith("doc:"):
                    nid = nid[4:]
                if nid and nid not in doc_ids:
                    neighbors.append(nid)
        return neighbors

    def get_kg_chunks(self, query_vector: list[float], kg_doc_ids: list[str], limit: int) -> list[dict[str, Any]]:
        if not kg_doc_ids:
            return []
        
        formatted_ids = []
        for d in kg_doc_ids:
            formatted_ids.append(d)
            formatted_ids.append(f"doc:{d}")
            
        knn_filter = {
            "terms": {
                "doc_id": formatted_ids
            }
        }
        
        knn: dict[str, Any] = {
            "field": "vector",
            "query_vector": np.asarray(query_vector, dtype=np.float32).tolist(),
            "k": limit,
            "num_candidates": max(limit * 2, 50),
            "filter": knn_filter
        }
        
        response = self.client.search(
            index=self.dense_index,
            size=limit,
            knn=knn,
            source_excludes=["vector"]
        )
        
        hits = []
        for idx, hit in enumerate(response["hits"]["hits"]):
            payload = dict(hit.get("_source") or {})
            payload.pop("vector", None)
            chunk_id = payload.get("chunk_id")
            if chunk_id:
                hits.append({
                    "chunk_id": str(chunk_id),
                    "score": float(hit.get("_score") or 0.0),
                    "rank": idx + 1,
                    "payload": payload,
                    "source": "kg"
                })
        return hits

    def graph_hybrid_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        candidate_k: int = 100,
        rrf_k: int = 60,
        kg_chunk_limit: int = 20,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # 1. Encode query
        query_vector = encode_texts(
            [query],
            self.tokenizer,
            self.model,
            self.device,
            batch_size=1,
            max_length=self.query_max_length,
            is_query=True,
            show_progress=False,
        )[0]
        
        # 2. Dense search
        knn: dict[str, Any] = {
            "field": "vector",
            "query_vector": np.asarray(query_vector, dtype=np.float32).tolist(),
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

        # 3. Sparse search
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

        # 4. RRF Fusion
        hybrid_candidates = fuse_ranked_hits(
            dense_hits,
            sparse_hits,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
        )
        
        missing_ids = [
            hit["chunk_id"]
            for hit in hybrid_candidates
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
                        for hit in hybrid_candidates:
                            if hit["chunk_id"] == cid:
                                hit["payload"].update(doc["_source"])
                                hit["citation"] = format_citation(hit["payload"])
                                break
            except Exception as e:
                logging.warning("Failed to hydrate missing chunk metadata: %s", e)

        for hit in hybrid_candidates:
            hit["source"] = "hybrid"

        # 5. KG Expansion
        chunk_ids = {hit["chunk_id"] for hit in hybrid_candidates}
        chunk_to_doc = self.batch_get_doc_ids_from_chunks(chunk_ids)
        
        seed_doc_ids = set()
        for hit in hybrid_candidates:
            cid = hit["chunk_id"]
            doc_id = chunk_to_doc.get(cid) or hit["payload"].get("doc_id")
            if doc_id:
                doc_id = str(doc_id).strip()
                if doc_id.startswith("doc:"):
                    doc_id = doc_id[4:]
                seed_doc_ids.add(doc_id)
                hit["payload"]["doc_id"] = doc_id

        kg_doc_ids = self.get_document_neighbors(list(seed_doc_ids))
        
        kg_candidates = []
        if kg_doc_ids:
            kg_candidates = self.get_kg_chunks(query_vector, kg_doc_ids, kg_chunk_limit)
            
            missing_kg_ids = [
                hit["chunk_id"]
                for hit in kg_candidates
                if not hit["payload"].get("chunk_text")
            ]
            if missing_kg_ids:
                try:
                    mget_res = self.client.mget(
                        index=self.sparse_index,
                        ids=missing_kg_ids,
                        source=["chunk_text", "legal_type", "document_number", "title", "issuing_authority", "effect_status", "effect_date", "legal_sectors", "linh_vuc"]
                    )
                    for doc in mget_res.get("docs", []):
                        if doc.get("found"):
                            cid = doc["_id"]
                            for hit in kg_candidates:
                                if hit["chunk_id"] == cid:
                                    hit["payload"].update(doc["_source"])
                                    hit["citation"] = format_citation(hit["payload"])
                                    break
                except Exception as e:
                    logging.warning("Failed to hydrate missing KG chunk metadata: %s", e)

        return hybrid_candidates, kg_candidates

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
    parser.add_argument("--index", default=None, help="Single hybrid index/alias")
    parser.add_argument("--dense-index", default=None)
    parser.add_argument("--sparse-index", default=None)
    
    # Neo4j args
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    
    # KG config
    parser.add_argument("--kg-chunk-limit", type=int, default=20, help="Max chunks to retrieve from KG neighbors")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="Single query string")
    group.add_argument("--gold", type=Path, help="Path to gold eval file")
    
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    parser.add_argument("--elastic-num-candidates", type=int, default=None)
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--max-workers", type=int, default=10)
    parser.add_argument("--device", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "graph_hybrid_eval_results.json")
    
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

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args()
    setup_logging()

    # Setup reranker
    reranker = None
    passage_loader = None
    if args.rerank:
        print(f"Loading reranker model: {args.reranker_model}...")
        passage_loader = PassageLoader(args.chunks)
        reranker = create_reranker(args.reranker_model, device=args.device, cache_dir=args.cache_dir)

    # Setup Neo4j
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j python package not installed.")
        sys.exit(1)
        
    print(f"Connecting to Neo4j at {args.neo4j_uri}...")
    neo4j_driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))

    retriever = GraphHybridRetriever(
        url=args.url,
        dense_index=args.dense_index,
        sparse_index=args.sparse_index,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        device=args.device,
        cache_dir=args.cache_dir,
        elastic_num_candidates=args.elastic_num_candidates,
        neo4j_driver=neo4j_driver,
        neo4j_database=args.neo4j_database
    )

    try:
        if args.query:
            print(f"\nQuerying: {args.query}")
            hybrid, kg = retriever.graph_hybrid_search(
                args.query,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
                kg_chunk_limit=args.kg_chunk_limit
            )
            print(f"Retrieved {len(hybrid)} hybrid candidates and {len(kg)} KG expansion candidates.")
            
            combined = hybrid + kg
            
            final_hits = combined
            if args.rerank and reranker is not None:
                passages = passage_loader.build_passages(combined)
                print("Scoring candidate pairs...")
                rerank_scores = reranker.score_pairs(
                    [(args.query, passage) for passage in passages],
                    batch_size=args.rerank_batch_size,
                )
                scored = sorted(
                    zip(combined, rerank_scores, strict=True),
                    key=lambda item: item[1],
                    reverse=True
                )
                final_hits = []
                for hit, score in scored[:args.top_k]:
                    hit["rerank_score"] = score
                    final_hits.append(hit)
            else:
                final_hits = combined[:args.top_k]

            print(f"\nTop {args.top_k} results:")
            for idx, hit in enumerate(final_hits):
                score_str = f"Rerank Score: {hit['rerank_score']:.4f}" if "rerank_score" in hit else f"RRF/KNN Score: {hit['score']:.4f}"
                source_str = hit.get("source", "unknown")
                print(f"[{idx+1}] {score_str} | Source: {source_str} | Chunk ID: {hit['chunk_id']}")
                print(f"Citation: {hit['citation']}")
                print(f"Text Preview: {hit['payload'].get('chunk_text', '')[:200]}...\n" + "-"*50)

        elif args.gold:
            print(f"\nRunning evaluation on gold file: {args.gold}")
            rows = load_jsonl(args.gold)
            
            details = []
            def process_retrieval(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
                return retriever.graph_hybrid_search(
                    row["query"],
                    filters=row.get("filters"),
                    candidate_k=args.candidate_k,
                    rrf_k=args.rrf_k,
                    kg_chunk_limit=args.kg_chunk_limit
                )

            try:
                from tqdm import tqdm
            except ImportError:
                tqdm = lambda x, **kwargs: x

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                results_raw = list(tqdm(executor.map(process_retrieval, rows), total=len(rows), desc="Retrieving Candidates"))

            # Reranking logic
            if args.rerank and reranker is not None:
                assert passage_loader is not None
                all_pairs = []
                pair_indices = []
                for q_idx, (row, (hybrid, kg)) in enumerate(zip(rows, results_raw)):
                    combined = hybrid + kg
                    try:
                        passages = passage_loader.build_passages(combined)
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
                            # Combined indices map directly to combined list
                            hybrid_len = len(results_raw[q_idx][0])
                            if c_idx < hybrid_len:
                                results_raw[q_idx][0][c_idx]["rerank_score"] = score
                            else:
                                results_raw[q_idx][1][c_idx - hybrid_len]["rerank_score"] = score
                    except Exception:
                        logging.warning("Global reranking failed", exc_info=True)

            for row, (hybrid, kg) in zip(rows, results_raw):
                combined = hybrid + kg
                
                # Default baseline is hybrid sorted by RRF
                rrf_hits = hybrid[:max(args.k_values)]
                
                # Hybrid + KG + Rerank final hits
                final_hits = combined
                if args.rerank and reranker is not None:
                    # Sort combine list by rerank_score
                    valid_candidates = [c.copy() for c in combined if "rerank_score" in c]
                    if valid_candidates:
                        valid_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
                        final_hits = valid_candidates[:max(args.k_values)]
                else:
                    final_hits = combined[:max(args.k_values)]

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
                            "rerank_score": hit.get("rerank_score"),
                            "source": hit.get("source", "hybrid")
                        } for hit in final_hits
                    ]
                })

            report = {
                **summarize(details, args.k_values),
                "rrf_metrics": summarize(details, args.k_values, prefix="rrf_"),
                "rerank_enabled": args.rerank,
                "reranker_model": args.reranker_model if args.rerank else None,
                "kg_config": {
                    "kg_chunk_limit": args.kg_chunk_limit,
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
        neo4j_driver.close()

if __name__ == "__main__":
    main()
