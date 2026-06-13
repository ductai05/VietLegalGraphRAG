import os
import sys
for _key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_key, None)

import argparse
import json
import math
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Import common evaluation utilities from dense retrieval
sys.path.append(str(BASE_DIR / "pipeline" / "04_embedding"))
from evaluate_dense import evaluate_hits_relevance, load_jsonl

# Import Elasticsearch client and tokenizer from sparse retrieval
sys.path.append(str(BASE_DIR / "pipeline" / "05_sparse_retrieval"))
from src.elastic_client import build_elasticsearch_client
from src.tokenizer import tokenize_vi

DEFAULT_EVAL_FILE = BASE_DIR / "pipeline" / "07_evaluation" / "eval_questions.json"
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "legal_embedding" / "sparse_eval_results.json"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate sparse retrieval using eval_questions.json")
    parser.add_argument("--eval-questions", type=Path, default=DEFAULT_EVAL_FILE,
                        help="Path to eval_questions.json")
    parser.add_argument("--url", default=os.environ.get("ELASTIC_URL", "http://127.0.0.1:9200"),
                        help="Elasticsearch URL")
    parser.add_argument("--api-key", default=os.environ.get("ELASTIC_API_KEY"),
                        help="Elasticsearch API key")
    parser.add_argument("--username", default=os.environ.get("ELASTIC_USERNAME"),
                        help="Elasticsearch username")
    parser.add_argument("--password", default=os.environ.get("ELASTIC_PASSWORD"),
                        help="Elasticsearch password")
    parser.add_argument("--index", default=os.environ.get("ELASTIC_ALIAS", os.environ.get("ELASTIC_INDEX", "vietlegal_chunks_sparse_current")),
                        help="Elasticsearch index or alias name")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help="Path to save evaluation results JSON")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Recall/MRR/nDCG top-k threshold")
    parser.add_argument("--chunks", type=Path, default=os.environ.get("CHUNKS_PATH"),
                        help="Path to chunks.parquet or sparse_base.parquet to resolve duplicate chunk texts")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / "pipeline" / "05_sparse_retrieval" / "config.env",
                        help="Path to environment file")
    return parser.parse_args()


def convert_to_gold_jsonl(eval_file: Path, chunks_file: Path | None = None) -> Path:
    sys.path.append(str(Path(__file__).resolve().parent))
    import convert_eval_to_gold
    convert_eval_to_gold.EVAL_FILE = eval_file
    convert_eval_to_gold.GOLD_FILE = eval_file.parent / "eval_questions_gold_sparse.jsonl"
    if chunks_file:
        convert_eval_to_gold.CHUNKS_FILE = chunks_file
    convert_eval_to_gold.main()
    return convert_eval_to_gold.GOLD_FILE


class SparseRetriever:
    def __init__(
        self,
        url: str,
        index: str,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.client = build_elasticsearch_client(
            url,
            api_key=api_key,
            username=username,
            password=password,
        )
        self.index = index

    def search(self, query: str, filters: dict[str, Any] | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        tokenized_query = tokenize_vi(query)
        body = {
            "size": top_k,
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
            body["query"]["bool"]["filter"] = filter_clauses

        response = self.client.search(index=self.index, body=body)
        
        hits = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            hits.append({
                "chunk_id": source.get("chunk_id"),
                "score": hit["_score"],
                "payload": source
            })
        return hits

    def close(self) -> None:
        self.client.close()


def main() -> None:
    # Pre-parse env-file configuration
    temp_parser = argparse.ArgumentParser(add_help=False)
    temp_parser.add_argument("--env-file", type=Path, default=BASE_DIR / "pipeline" / "05_sparse_retrieval" / "config.env")
    temp_args, _ = temp_parser.parse_known_args()
    
    load_env_file(temp_args.env_file)
    if not temp_args.env_file.exists():
        load_env_file(BASE_DIR / "pipeline" / "05_sparse_retrieval" / ".env")
        load_env_file(BASE_DIR / ".env")

    args = parse_args()
    
    if not args.eval_questions.exists():
        print(f"Error: Evaluation file {args.eval_questions} not found.")
        sys.exit(1)

    print(f"Connecting to Elasticsearch at {args.url}")
    retriever = SparseRetriever(
        url=args.url,
        index=args.index,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
    )
    
    print("Converting evaluation file to gold standard...")
    gold_file = convert_to_gold_jsonl(args.eval_questions, chunks_file=args.chunks)
    
    print(f"Loading gold file: {gold_file}")
    rows = load_jsonl(gold_file)
    details = []
    
    print(f"Evaluating {len(rows)} queries on index '{args.index}' (top_k={args.top_k})...")
    
    try:
        for idx, row in enumerate(rows):
            hits = retriever.search(
                row["query"],
                filters=row.get("filters"),
                top_k=args.top_k
            )
            rel = evaluate_hits_relevance(hits, row)
            first = next((index + 1 for index, value in enumerate(rel) if value), None)
            relevant_total = max(
                len(row.get("relevant_chunk_groups") or row.get("relevant_chunk_ids") or []),
                1,
            )
            recall = min(sum(rel) / relevant_total, 1.0)
            mrr = 1.0 / first if first else 0.0
            dcg = sum(value / math.log2(index + 2) for index, value in enumerate(rel))
            ideal_hits = min(relevant_total, args.top_k)
            idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
            details.append(
                {
                    "query": row["query"],
                    "group": row.get("group", "unknown"),
                    "recall": recall,
                    "mrr": mrr,
                    "ndcg": dcg / idcg if idcg else 0.0,
                    "top_chunk_ids": [hit["chunk_id"] for hit in hits],
                }
            )
            
            if (idx + 1) % 50 == 0:
                print(f"Processed {idx + 1}/{len(rows)} queries...")
    finally:
        retriever.close()
        gold_file.unlink(missing_ok=True)

    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        return sum(item[key] for item in subset) / len(subset) if subset else 0.0

    groups = sorted({item["group"] for item in details})
    report = {
        "queries": len(details),
        f"recall@{args.top_k}": mean("recall", details),
        f"mrr@{args.top_k}": mean("mrr", details),
        f"ndcg@{args.top_k}": mean("ndcg", details),
        "by_group": {
            group: {
                "queries": len(subset := [item for item in details if item["group"] == group]),
                f"recall@{args.top_k}": mean("recall", subset),
                f"mrr@{args.top_k}": mean("mrr", subset),
                f"ndcg@{args.top_k}": mean("ndcg", subset),
            }
            for group in groups
        },
        "details": details,
    }
    
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except OSError:
        fallback_output = Path.cwd() / args.output.name
        print(f"Warning: Output directory not writable. Saving results to: {fallback_output}")
        with fallback_output.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        args.output = fallback_output
    
    print("\nEvaluation completed successfully!")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
