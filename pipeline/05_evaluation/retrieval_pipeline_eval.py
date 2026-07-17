"""Run the entire retrieval evaluation pipeline and plot separate metrics charts."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
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


def decode_cloud_id(cloud_id: str) -> str:
    import base64
    if ":" in cloud_id:
        _, encoded = cloud_id.split(":", 1)
    else:
        encoded = cloud_id
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    decoded = base64.b64decode(padded).decode("utf-8")
    parts = decoded.split("$")
    if len(parts) >= 2:
        host, es_uuid = parts[0], parts[1]
        if ":" in host:
            return f"https://{es_uuid}.{host}"
        else:
            return f"https://{es_uuid}.{host}:443"
    raise ValueError("Invalid Elastic Cloud ID format")


def parse_args(argv=None):
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)
    load_env_file(pre_args.env_file)

    parser = argparse.ArgumentParser(description="Automate retrieval evaluation pipeline")
    parser.add_argument("--env-file", type=Path, default=pre_args.env_file,
                        help="Environment file with Elasticsearch credentials")
    parser.add_argument("--gold", type=Path, default=BASE_DIR / "output" / "eval_questions_gold.jsonl",
                        help="Path to gold standard evaluation file")
    parser.add_argument("--url", default=os.environ.get("ELASTICSEARCH_URL") or os.environ.get("ELASTIC_URL") or "http://127.0.0.1:9200",
                        help="Elasticsearch connection URL")
    parser.add_argument("--elastic-cloud-id", default=os.environ.get("ELASTIC_CLOUD_ID"),
                        help="Elasticsearch Cloud ID")
    parser.add_argument("--api-key", default=os.environ.get("ELASTICSEARCH_API_KEY") or os.environ.get("ELASTIC_API_KEY"),
                        help="Elasticsearch API key")
    parser.add_argument("--username", default=os.environ.get("ELASTICSEARCH_USERNAME") or os.environ.get("ELASTIC_USERNAME"),
                        help="Elasticsearch username")
    parser.add_argument("--password", default=os.environ.get("ELASTICSEARCH_PASSWORD") or os.environ.get("ELASTIC_PASSWORD"),
                        help="Elasticsearch password")
    parser.add_argument("--index", default=os.environ.get("ELASTICSEARCH_ALIAS") or os.environ.get("ELASTICSEARCH_INDEX"),
                        help="Hybrid Elasticsearch index or alias for dense and sparse search")
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K, 
                        help="RRF rank constant used by hybrid_search.py")
    parser.add_argument("--elastic-num-candidates", type=int, default=None,
                        help="Elasticsearch kNN num_candidates override for hybrid dense search")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL,
                        help="Hugging Face reranker model name")
    parser.add_argument("--rerank-batch-size", type=int, default=32,
                        help="Reranker batch size")
    parser.add_argument("--max-workers", type=int, default=4,
                        help="Number of concurrent threads for Elasticsearch retrieval")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI"),
                        help="Neo4j connection URI")
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER"),
                        help="Neo4j username")
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                        help="Neo4j password")
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE"),
                        help="Neo4j database name")
    parser.add_argument("--chunks", type=Path, default=None,
                        help="Path to chunks parquet dataset for metadata hydration")
    parser.add_argument("--device", default=None,
                        help="Compute device for encoder models (cpu or cuda)")
    parser.add_argument("--num-samples", type=int, default=None,
                        help="Limit the number of evaluation samples")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output",
                        help="Directory to save evaluation reports and plots")
    return parser.parse_args(argv)


def run_command(cmd, desc):
    print(f"\n>>> Running: {desc}...")
    print(f"Command: {' '.join(str(x) for x in cmd)}")
    res = subprocess.run(cmd, check=True)
    if res.returncode != 0:
        raise RuntimeError(f"Step failed: {desc}")


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.elastic_cloud_id and (not args.url or args.url == "http://127.0.0.1:9200"):
        try:
            args.url = decode_cloud_id(args.elastic_cloud_id)
            print(f"Decoded Elastic Cloud ID to URL: {args.url}")
        except Exception as e:
            print(f"Error decoding Elastic Cloud ID: {e}")

    eval_gold_path = args.gold
    temp_gold_file = None

    # Implement subset sample limiting if requested
    if args.num_samples is not None and args.gold.exists():
        try:
            with open(args.gold, "r", encoding="utf-8") as f:
                content = f.read().strip()

            lines = [line for line in content.splitlines() if line.strip()]
            is_jsonl = False
            if lines:
                try:
                    json.loads(lines[0])
                    if len(lines) > 1:
                        is_jsonl = True
                    else:
                        json.loads(content)
                except json.JSONDecodeError:
                    pass

            if is_jsonl:
                subset_lines = lines[:args.num_samples]
                temp_gold_file = args.output_dir / "temp_eval_gold_subset.jsonl"
                with open(temp_gold_file, "w", encoding="utf-8") as f:
                    for line in subset_lines:
                        f.write(line + "\n")
            else:
                data = json.loads(content)
                if isinstance(data, dict) and "questions" in data:
                    data_copy = dict(data)
                    data_copy["questions"] = data["questions"][:args.num_samples]
                    temp_gold_file = args.output_dir / "temp_eval_gold_subset.json"
                    with open(temp_gold_file, "w", encoding="utf-8") as f:
                        json.dump(data_copy, f, ensure_ascii=False, indent=2)
                else:
                    data_subset = data[:args.num_samples] if isinstance(data, list) else data
                    temp_gold_file = args.output_dir / "temp_eval_gold_subset.json"
                    with open(temp_gold_file, "w", encoding="utf-8") as f:
                        json.dump(data_subset, f, ensure_ascii=False, indent=2)
            eval_gold_path = temp_gold_file
            print(f"Created temporary subset with {args.num_samples} queries: {eval_gold_path}")
        except Exception as e:
            print(f"Warning: Failed to create subset ({e}). Falling back to full file.")
            eval_gold_path = args.gold

    try:
        # 1. Run Dense Evaluation
        dense_output = args.output_dir / "elasticsearch_dense_eval.json"
        dense_cmd = [
            sys.executable, str(EVAL_DIR / "evaluate_dense.py"),
            "--gold", str(eval_gold_path),
            "--output", str(dense_output),
            "--max-workers", str(args.max_workers)
        ]
        if args.elastic_cloud_id:
            dense_cmd.extend(["--elastic-cloud-id", args.elastic_cloud_id])
            if args.api_key:
                dense_cmd.extend(["--elastic-api-key", args.api_key])
        else:
            dense_cmd.extend(["--url", args.url])
            if args.api_key:
                dense_cmd.extend(["--api-key", args.api_key])
                
        if args.chunks:
            dense_cmd.extend(["--chunks", str(args.chunks)])
        if args.device:
            dense_cmd.extend(["--device", args.device])
        if args.index:
            dense_cmd.extend(["--elastic-index", args.index])
        if args.elastic_num_candidates:
            dense_cmd.extend(["--elastic-num-candidates", str(args.elastic_num_candidates)])
        run_command(dense_cmd, "Dense Retrieval Evaluation")

        # 2. Run Sparse Evaluation
        sparse_output = args.output_dir / "elasticsearch_sparse_eval.json"
        sparse_cmd = [
            sys.executable, str(EVAL_DIR / "evaluate_sparse.py"),
            "--eval-questions", str(eval_gold_path),
            "--url", args.url,
            "--output", str(sparse_output),
            "--max-workers", str(args.max_workers)
        ]
        if args.env_file:
            sparse_cmd.extend(["--env-file", str(args.env_file)])
        if args.api_key:
            sparse_cmd.extend(["--api-key", args.api_key])
        if args.username:
            sparse_cmd.extend(["--username", args.username])
        if args.password:
            sparse_cmd.extend(["--password", args.password])
        if args.chunks:
            sparse_cmd.extend(["--chunks", str(args.chunks)])
        if args.index:
            sparse_cmd.extend(["--index", args.index])
        run_command(sparse_cmd, "Sparse Retrieval Evaluation")

        # 3. Run Hybrid + Reranker Evaluations for K = 20, 30, 40, 50
        rerank_outputs = {}
        for k_val in [20, 30, 40, 50]:
            out_file = args.output_dir / f"elasticsearch_hybrid_rerank_eval_k{k_val}.json"
            rerank_outputs[k_val] = out_file
            hybrid_cmd = [
                sys.executable, str(EVAL_DIR / "hybrid_search.py"),
                "--gold", str(eval_gold_path),
                "--url", args.url,
                "--candidate-k", str(k_val),
                "--rrf-k", str(args.rrf_k),
                "--reranker-model", args.reranker_model,
                "--rerank-batch-size", str(args.rerank_batch_size),
                "--rerank",
                "--output", str(out_file),
                "--max-workers", str(args.max_workers)
            ]
            if args.env_file:
                hybrid_cmd.extend(["--env-file", str(args.env_file)])
            if args.index:
                hybrid_cmd.extend(["--index", args.index])
            if args.elastic_num_candidates:
                hybrid_cmd.extend(["--elastic-num-candidates", str(args.elastic_num_candidates)])
            if args.api_key:
                hybrid_cmd.extend(["--api-key", args.api_key])
            if args.username:
                hybrid_cmd.extend(["--username", args.username])
            if args.password:
                hybrid_cmd.extend(["--password", args.password])
            if args.chunks:
                hybrid_cmd.extend(["--chunks", str(args.chunks)])
            if args.device:
                hybrid_cmd.extend(["--device", args.device])
            run_command(hybrid_cmd, f"Hybrid + Reranker Evaluation (K={k_val})")

        # 3.5 Run Knowledge Graph + Reranker Evaluation (Hybrid + KG + Reranker)
        graph_output = args.output_dir / "elasticsearch_hybrid_graph_eval.json"
        graph_cmd = [
            sys.executable, str(EVAL_DIR / "graph_hybrid_search.py"),
            "--gold", str(eval_gold_path),
            "--url", args.url,
            "--candidate-k", "50",
            "--rrf-k", str(args.rrf_k),
            "--reranker-model", args.reranker_model,
            "--rerank-batch-size", str(args.rerank_batch_size),
            "--rerank",
            "--output", str(graph_output),
            "--max-workers", str(args.max_workers)
        ]
        if args.env_file:
            graph_cmd.extend(["--env-file", str(args.env_file)])
        if args.index:
            graph_cmd.extend(["--index", args.index])
        if args.elastic_num_candidates:
            graph_cmd.extend(["--elastic-num-candidates", str(args.elastic_num_candidates)])
        if args.api_key:
            graph_cmd.extend(["--api-key", args.api_key])
        if args.username:
            graph_cmd.extend(["--username", args.username])
        if args.password:
            graph_cmd.extend(["--password", args.password])
        if args.chunks:
            graph_cmd.extend(["--chunks", str(args.chunks)])
        if args.device:
            graph_cmd.extend(["--device", args.device])
            
        if args.neo4j_uri:
            graph_cmd.extend(["--neo4j-uri", args.neo4j_uri])
        if args.neo4j_user:
            graph_cmd.extend(["--neo4j-user", args.neo4j_user])
        if args.neo4j_password:
            graph_cmd.extend(["--neo4j-password", args.neo4j_password])
        if args.neo4j_database:
            graph_cmd.extend(["--neo4j-database", args.neo4j_database])
            
        run_command(graph_cmd, "Hybrid + KG + Reranker Retrieval Evaluation")

        # 4. Run Plotting Metrics
        plot_cmd = [
            sys.executable, str(EVAL_DIR / "plot_metrics.py"),
            "--dense", str(dense_output),
            "--sparse", str(sparse_output),
            "--hybrid", str(rerank_outputs[50]),  # Pass one rerank output to extract baseline hybrid RRF metrics
            "--graph", str(graph_output),
            "--output-dir", str(args.output_dir)
        ]
        for k_val, out_file in rerank_outputs.items():
            plot_cmd.extend([f"--rerank-k{k_val}", str(out_file)])
        run_command(plot_cmd, "Generate Comparison Metrics Plots")

        print("\n>>> Pipeline evaluation completed successfully!")
        print(f"All reports and plots saved to: {args.output_dir}")

    finally:
        # Clean up temporary gold file if created
        if temp_gold_file and temp_gold_file.exists():
            temp_gold_file.unlink(missing_ok=True)
            print(f"Cleaned up temporary subset file: {temp_gold_file}")


if __name__ == "__main__":
    main()
