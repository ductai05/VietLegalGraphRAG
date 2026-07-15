import os
import sys
import json
import math
import argparse
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = Path(__file__).resolve().parents[1]
BACKEND_SRC = BASE_DIR / "src" / "backend"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
if str(BACKEND_SRC / "services") not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC / "services"))

from graph_retriever import GraphRetriever

def load_env_file(path: Path) -> None:
    if not path or not path.exists():
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

def clean_doc_id(val: Any) -> str:
    s = str(val or "").strip()
    if s.startswith("doc:"):
        return s[4:]
    return s

def load_gold_data(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
        return [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in content.splitlines() if line.strip()]

def batch_get_doc_ids_from_chunks(driver, database: str, chunk_ids: set[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    query = """
    UNWIND $chunk_ids AS cid
    MATCH (c) WHERE c.chunk_id = cid
    OPTIONAL MATCH (c)<-[:HAS_CHUNK]-(d:Document)
    RETURN c.chunk_id AS chunk_id, COALESCE(c.doc_id, d.doc_id, d.id) AS doc_id
    """
    mapping = {}
    with driver.session(database=database) as session:
        records = session.run(query, chunk_ids=list(chunk_ids))
        for record in records:
            if record["doc_id"]:
                mapping[record["chunk_id"]] = clean_doc_id(record["doc_id"])
    return mapping

def ensure_indexes(driver, database: str) -> None:
    queries = [
        "CREATE INDEX chunk_id_index IF NOT EXISTS FOR (c:Article) ON (c.chunk_id)",
        "CREATE INDEX chunk_id_generic_index IF NOT EXISTS FOR (c:Chunk) ON (c.chunk_id)",
        "CREATE INDEX document_doc_id_index IF NOT EXISTS FOR (d:Document) ON (d.doc_id)",
        "CREATE INDEX document_id_index IF NOT EXISTS FOR (d:Document) ON (d.id)"
    ]
    with driver.session(database=database) as session:
        for q in queries:
            try:
                session.run(q)
            except Exception as e:
                print(f"Warning creating index ({q}): {e}")

def wait_for_indexes(driver, database: str, timeout: int = 60) -> None:
    import time
    start = time.time()
    with driver.session(database=database) as session:
        while time.time() - start < timeout:
            try:
                recs = list(session.run("SHOW INDEXES"))
                pending = 0
                for r in recs:
                    state = r.get("state")
                    if state and state != "ONLINE":
                        pending += 1
                if pending == 0:
                    return
            except Exception as e:
                # If SHOW INDEXES is not supported or errors, just exit early
                print(f"Warning checking index state: {e}")
                return
            time.sleep(2)
    print("Warning: Some indexes not yet ONLINE after timeout")

def parse_args():
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env")
    pre_args, _ = pre_parser.parse_known_args()
    load_env_file(pre_args.env_file)

    parser = argparse.ArgumentParser(description="Evaluate Knowledge Graph retrieval expansion.")
    parser.add_argument("--search-results", type=Path, required=True,
                        help="Path to the initial hybrid search results JSON.")
    parser.add_argument("--gold", type=Path, required=True,
                        help="Path to eval_questions_gold.jsonl or json.")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
                        help="Neo4j connection URI.")
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"),
                        help="Neo4j username.")
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"),
                        help="Neo4j password.")
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"),
                        help="Neo4j database name.")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Number of initial top chunks to consider for graph expansion.")
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5, 10],
                        help="k values to evaluate hit rate and recall.")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "graph_eval_results.json",
                        help="Path to save evaluation results.")
    parser.add_argument("--env-file", type=Path, default=pre_args.env_file,
                        help="Path to .env file.")
    return parser.parse_args()

def main():
    args = parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j python package not installed. Please install it.")
        sys.exit(1)

    print(f"Connecting to Neo4j at {args.neo4j_uri}...")
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    print("Ensuring Neo4j indexes exist...")
    ensure_indexes(driver, args.neo4j_database)
    wait_for_indexes(driver, args.neo4j_database)
    retriever = GraphRetriever(driver, database=args.neo4j_database)
    
    print(f"Loading gold file: {args.gold}")
    gold_data = load_gold_data(args.gold)
    gold_dict = {}
    for row in gold_data:
        q_key = (row.get("query") or row.get("question") or "").strip()
        if q_key:
            gold_dict[q_key] = row
    
    print(f"Loading search results: {args.search_results}")
    with args.search_results.open("r", encoding="utf-8") as f:
        search_data = json.load(f)
    
    details = search_data.get("details", search_data) if isinstance(search_data, dict) else search_data
    if not isinstance(details, list):
        details = []

    results = []
    
    print(f"Evaluating {len(details)} queries...")
    try:
        from tqdm import tqdm
        iterator = tqdm(details, desc="Evaluating Graph Queries")
    except ImportError:
        iterator = details

    print("Pre-fetching doc_ids for chunks...")
    all_chunk_ids = set()
    for row in details:
        query_text = (row.get("query") or row.get("question") or "").strip()
        gold_row = gold_dict.get(query_text)
        if gold_row and not gold_row.get("relevant_doc_ids"):
            all_chunk_ids.update(gold_row.get("relevant_chunk_ids", []))
        for k in args.k_values:
            top_chunk_ids = (row.get("top_chunk_ids") or [])[:k]
            if not top_chunk_ids and "final_ordered_results" in row:
                top_chunk_ids = [res["chunk_id"] for res in row["final_ordered_results"]][:k]
            all_chunk_ids.update(top_chunk_ids)

    chunk_to_doc_cache = batch_get_doc_ids_from_chunks(driver, args.neo4j_database, all_chunk_ids)
    doc_neighbors_cache = {}

    def get_cached_doc_id(chunk_id: str) -> str:
        return chunk_to_doc_cache.get(chunk_id, clean_doc_id(chunk_id))

    print("Pre-warming graph neighbor cache...")
    all_seed_docs = set()
    max_k = max(args.k_values)
    for row in details:
        top_chunk_ids = (row.get("top_chunk_ids") or [])[:max_k]
        if not top_chunk_ids and "final_ordered_results" in row:
            top_chunk_ids = [res["chunk_id"] for res in row["final_ordered_results"]][:max_k]
        for c in top_chunk_ids:
            d = get_cached_doc_id(c)
            if d:
                all_seed_docs.add(d)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _warm_one(doc_id: str) -> tuple[str, list[str]]:
        try:
            context = retriever.get_document_neighbors(doc_id, depth=1)
            docs = []
            if context and hasattr(context, "nodes") and context.nodes:
                for node in context.nodes:
                    node_doc_id = None
                    if hasattr(node, "properties") and node.properties:
                        node_doc_id = node.properties.get("doc_id")
                    if not node_doc_id and hasattr(node, "id") and node.id:
                        node_doc_id = clean_doc_id(node.id)
                    if node_doc_id:
                        cleaned = clean_doc_id(node_doc_id)
                        if cleaned not in docs:
                            docs.append(cleaned)
            return doc_id, docs
        except Exception as e:
            print(f"Error fetching neighbors for {doc_id}: {e}")
            return doc_id, []

    if all_seed_docs:
        try:
            from tqdm import tqdm
            has_tqdm = True
        except ImportError:
            has_tqdm = False

        # Use 8 workers to fetch in parallel
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_warm_one, d): d for d in all_seed_docs}
            iterator_warm = as_completed(futures)
            if has_tqdm:
                iterator_warm = tqdm(iterator_warm, total=len(futures), desc="Pre-warming neighbor cache")
            for fut in iterator_warm:
                doc_id, docs = fut.result()
                doc_neighbors_cache[(doc_id, 1)] = docs

    def explore_graph(depth: int, seed_docs: list[str]) -> list[str]:
        expanded_docs = []
        seen_exp = set()
        for doc_id in seed_docs:
            cache_key = (doc_id, depth)
            if cache_key not in doc_neighbors_cache:
                try:
                    context = retriever.get_document_neighbors(doc_id, depth=depth)
                    docs = []
                    if context and hasattr(context, "nodes") and context.nodes:
                        for node in context.nodes:
                            node_doc_id = None
                            if hasattr(node, "properties") and node.properties:
                                node_doc_id = node.properties.get("doc_id")
                            if not node_doc_id and hasattr(node, "id") and node.id:
                                node_doc_id = clean_doc_id(node.id)
                            if node_doc_id:
                                cleaned = clean_doc_id(node_doc_id)
                                if cleaned not in docs:
                                    docs.append(cleaned)
                    doc_neighbors_cache[cache_key] = docs
                except Exception:
                    doc_neighbors_cache[cache_key] = []
            for neighbor in doc_neighbors_cache[cache_key]:
                if neighbor not in seen_exp:
                    seen_exp.add(neighbor)
                    expanded_docs.append(neighbor)
        return expanded_docs

    for idx, row in enumerate(iterator):
        query = (row.get("query") or row.get("question") or "").strip()
        gold_row = gold_dict.get(query)
        if not gold_row:
            continue
            
        relevant_doc_ids = {clean_doc_id(d) for d in gold_row.get("relevant_doc_ids", []) if d}
        if not relevant_doc_ids:
            relevant_chunk_ids = set(gold_row.get("relevant_chunk_ids", []))
            relevant_doc_ids = {clean_doc_id(get_cached_doc_id(c)) for c in relevant_chunk_ids if c}
            
        if not relevant_doc_ids:
            continue
            
        query_result = {"query": query}
        
        for k in args.k_values:
            top_chunk_ids = (row.get("top_chunk_ids") or [])[:k]
            if not top_chunk_ids and "final_ordered_results" in row:
                top_chunk_ids = [res["chunk_id"] for res in row["final_ordered_results"]][:k]
                
            base_doc_list = []
            for c in top_chunk_ids:
                d = get_cached_doc_id(c)
                if d and d not in base_doc_list:
                    base_doc_list.append(d)

            base_rel = [int(d in relevant_doc_ids) for d in base_doc_list]
            base_hit = any(base_rel)
            base_recall = len(set(base_doc_list) & relevant_doc_ids) / len(relevant_doc_ids)
            
            # Remove base MRR/NDCG calculation as it is not needed here
                
            hop1_docs = explore_graph(1, base_doc_list)
            hop1_new = [d for d in hop1_docs if d not in set(base_doc_list)]
            combined_hop1_list = base_doc_list + hop1_new
            
            hop1_rel = [int(d in relevant_doc_ids) for d in combined_hop1_list]
            hop1_hit = any(hop1_rel)
            hop1_recall = len(set(combined_hop1_list) & relevant_doc_ids) / len(relevant_doc_ids)
            hop1_rescue = int(not base_hit and hop1_hit)
            hop1_noise = len(set(hop1_new) - relevant_doc_ids) / len(hop1_new) if hop1_new else 0.0

            recall_lift = hop1_recall - base_recall
            hop1_relevant_count = sum(1 for d in hop1_new if d in relevant_doc_ids)
            kg_precision = hop1_relevant_count / len(hop1_new) if hop1_new else 0.0
            
            query_result.update({
                f"base_hit@{k}": int(base_hit),
                f"base_recall@{k}": base_recall,
                f"hop1_hit@{k}": int(hop1_hit),
                f"hop1_recall@{k}": hop1_recall,
                f"hop1_rescue@{k}": hop1_rescue,
                f"hop1_noise@{k}": hop1_noise,
                f"recall_lift@{k}": recall_lift,
                f"kg_precision@{k}": kg_precision,
            })
            
        results.append(query_result)
    
    if not results:
        print("No valid evaluation records found.")
        driver.close()
        return
        
    num_queries = len(results)
    summary = {"queries": num_queries}
    for k in args.k_values:
        summary.update({
            f"base_hit_rate@{k}": sum(r[f"base_hit@{k}"] for r in results) / num_queries,
            f"base_recall@{k}": sum(r[f"base_recall@{k}"] for r in results) / num_queries,
            f"hop1_hit_rate@{k}": sum(r[f"hop1_hit@{k}"] for r in results) / num_queries,
            f"hop1_recall@{k}": sum(r[f"hop1_recall@{k}"] for r in results) / num_queries,
            f"hop1_rescue_rate@{k}": sum(r[f"hop1_rescue@{k}"] for r in results) / num_queries,
            f"hop1_noise_avg@{k}": sum(r[f"hop1_noise@{k}"] for r in results) / num_queries,
            f"recall_lift_avg@{k}": sum(r[f"recall_lift@{k}"] for r in results) / num_queries,
            f"kg_precision_avg@{k}": sum(r[f"kg_precision@{k}"] for r in results) / num_queries,
        })
    
    tk = args.top_k if args.top_k in args.k_values else args.k_values[-1]
    
    print(f"\n--- Ablation Table (Base vs Hybrid + KG) at K={tk} ---")
    print(f"{'Metric':<20} | {'Base':<10} | {'Hybrid + KG':<10} | {'Δ (Lift)':<10}")
    print("-" * 60)
    print(f"{'Hit Rate':<20} | {summary[f'base_hit_rate@{tk}']:<10.4f} | {summary[f'hop1_hit_rate@{tk}']:<10.4f} | {summary[f'hop1_hit_rate@{tk}'] - summary[f'base_hit_rate@{tk}']:<10.4f}")
    print(f"{'Recall':<20} | {summary[f'base_recall@{tk}']:<10.4f} | {summary[f'hop1_recall@{tk}']:<10.4f} | {summary[f'recall_lift_avg@{tk}']:<10.4f}")
    print(f"{'Rescue Rate':<20} | {'-':<10} | {summary[f'hop1_rescue_rate@{tk}']:<10.4f} | {'-':<10}")
    print(f"{'Noise Avg':<20} | {'-':<10} | {summary[f'hop1_noise_avg@{tk}']:<10.4f} | {'-':<10}")
    print(f"{'KG Precision':<20} | {'-':<10} | {summary[f'kg_precision_avg@{tk}']:<10.4f} | {'-':<10}")
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump({"summary": summary, "details": results}, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")
        
    driver.close()

if __name__ == "__main__":
    main()

