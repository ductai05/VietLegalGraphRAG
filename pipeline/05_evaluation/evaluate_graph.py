import os
import sys
import json
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = Path(__file__).resolve().parents[1]
BACKEND_SRC = BASE_DIR / "src" / "backend"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
if str(BACKEND_SRC / "services") not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC / "services"))

from graph_retriever import GraphRetriever

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

def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def get_doc_id_from_chunk(driver, database: str, chunk_id: str) -> str:
    """Extract doc_id from chunk_id by querying Neo4j."""
    query = "MATCH (c:Chunk {chunk_id: $cid}) RETURN c.doc_id AS doc_id"
    with driver.session(database=database) as session:
        record = session.run(query, cid=chunk_id).single()
        if record and record["doc_id"]:
            return str(record["doc_id"])
    return chunk_id

def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate Knowledge Graph retrieval expansion.")
    parser.add_argument("--search-results", type=Path, required=True,
                        help="Path to the initial hybrid search results JSON.")
    parser.add_argument("--gold", type=Path, required=True,
                        help="Path to eval_questions_gold.jsonl.")
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
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "graph_eval_results.json",
                        help="Path to save evaluation results.")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env",
                        help="Path to .env file.")
    return parser.parse_args()

def main():
    load_env_file(BASE_DIR / ".env")
    args = parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j python package not installed. Please install it.")
        sys.exit(1)

    print(f"Connecting to Neo4j at {args.neo4j_uri}...")
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    retriever = GraphRetriever(driver, database=args.neo4j_database)
    
    print(f"Loading gold file: {args.gold}")
    gold_data = load_jsonl(args.gold)
    gold_dict = {row["query"]: row for row in gold_data}
    
    print(f"Loading search results: {args.search_results}")
    with args.search_results.open("r", encoding="utf-8") as f:
        search_data = json.load(f)
    
    details = search_data.get("details", [])
    results = []
    
    print(f"Evaluating {len(details)} queries...")
    for idx, row in enumerate(details):
        query = row["query"]
        gold_row = gold_dict.get(query)
        if not gold_row:
            continue
            
        # Extract relevant doc_ids
        relevant_doc_ids = set(gold_row.get("relevant_doc_ids", []))
        if not relevant_doc_ids:
            relevant_chunk_ids = set(gold_row.get("relevant_chunk_ids", []))
            relevant_doc_ids = {get_doc_id_from_chunk(driver, args.neo4j_database, c) for c in relevant_chunk_ids}
            
        if not relevant_doc_ids:
            continue
            
        top_chunk_ids = row.get("top_chunk_ids", [])[:args.top_k]
        if not top_chunk_ids and "final_ordered_results" in row:
            top_chunk_ids = [res["chunk_id"] for res in row["final_ordered_results"]][:args.top_k]
            
        base_doc_ids = {get_doc_id_from_chunk(driver, args.neo4j_database, c) for c in top_chunk_ids}
        
        base_hit = any(doc_id in relevant_doc_ids for doc_id in base_doc_ids)
        base_recall = len(base_doc_ids.intersection(relevant_doc_ids)) / len(relevant_doc_ids)
        
        def explore_graph(depth: int) -> set:
            expanded_docs = set()
            for doc_id in base_doc_ids:
                context = retriever.get_document_neighbors(doc_id, depth=depth)
                if context and hasattr(context, "nodes") and context.nodes:
                    for node in context.nodes:
                        node_doc_id = node.properties.get("doc_id") if hasattr(node, "properties") else None
                        if not node_doc_id and hasattr(node, "id") and node.id and str(node.id).startswith("doc:"):
                            node_doc_id = str(node.id).split(":", 1)[1]
                        if node_doc_id:
                            expanded_docs.add(node_doc_id)
            return expanded_docs
            
        hop1_docs = explore_graph(1)
        hop2_docs = explore_graph(2)
        
        combined_hop1 = base_doc_ids.union(hop1_docs)
        combined_hop2 = base_doc_ids.union(hop2_docs)
        
        hop1_hit = any(doc_id in relevant_doc_ids for doc_id in combined_hop1)
        hop2_hit = any(doc_id in relevant_doc_ids for doc_id in combined_hop2)
        
        hop1_recall = len(combined_hop1.intersection(relevant_doc_ids)) / len(relevant_doc_ids)
        hop2_recall = len(combined_hop2.intersection(relevant_doc_ids)) / len(relevant_doc_ids)
        
        hop1_rescue = int(not base_hit and hop1_hit)
        hop2_rescue = int(not base_hit and hop2_hit)
        
        hop1_new = hop1_docs - base_doc_ids
        hop2_new = hop2_docs - base_doc_ids
        hop1_noise = len(hop1_new - relevant_doc_ids) / max(1, len(base_doc_ids))
        hop2_noise = len(hop2_new - relevant_doc_ids) / max(1, len(base_doc_ids))
        
        results.append({
            "query": query,
            "base_hit": int(base_hit),
            "base_recall": base_recall,
            "hop1_hit": int(hop1_hit),
            "hop1_recall": hop1_recall,
            "hop1_rescue": hop1_rescue,
            "hop1_noise": hop1_noise,
            "hop2_hit": int(hop2_hit),
            "hop2_recall": hop2_recall,
            "hop2_rescue": hop2_rescue,
            "hop2_noise": hop2_noise,
        })
        
        if (idx + 1) % 10 == 0:
            print(f"Processed {idx + 1}/{len(details)} queries...")
    
    if not results:
        print("No valid evaluation records found.")
        driver.close()
        return
        
    num_queries = len(results)
    summary = {
        "queries": num_queries,
        "base_hit_rate": sum(r["base_hit"] for r in results) / num_queries,
        "base_recall": sum(r["base_recall"] for r in results) / num_queries,
        "hop1_hit_rate": sum(r["hop1_hit"] for r in results) / num_queries,
        "hop1_recall": sum(r["hop1_recall"] for r in results) / num_queries,
        "hop1_rescue_rate": sum(r["hop1_rescue"] for r in results) / num_queries,
        "hop1_noise_avg": sum(r["hop1_noise"] for r in results) / num_queries,
        "hop2_hit_rate": sum(r["hop2_hit"] for r in results) / num_queries,
        "hop2_recall": sum(r["hop2_recall"] for r in results) / num_queries,
        "hop2_rescue_rate": sum(r["hop2_rescue"] for r in results) / num_queries,
        "hop2_noise_avg": sum(r["hop2_noise"] for r in results) / num_queries,
    }
    
    print("\n--- Ablation Table (Base vs 1-Hop vs 2-Hop) ---")
    print(f"{'Metric':<20} | {'Base':<10} | {'1-Hop':<10} | {'2-Hop':<10}")
    print("-" * 57)
    print(f"{'Hit Rate':<20} | {summary['base_hit_rate']:<10.4f} | {summary['hop1_hit_rate']:<10.4f} | {summary['hop2_hit_rate']:<10.4f}")
    print(f"{'Recall':<20} | {summary['base_recall']:<10.4f} | {summary['hop1_recall']:<10.4f} | {summary['hop2_recall']:<10.4f}")
    print(f"{'Rescue Rate':<20} | {'-':<10} | {summary['hop1_rescue_rate']:<10.4f} | {summary['hop2_rescue_rate']:<10.4f}")
    print(f"{'Noise Avg':<20} | {'-':<10} | {summary['hop1_noise_avg']:<10.4f} | {summary['hop2_noise_avg']:<10.4f}")
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump({"summary": summary, "details": results}, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")
        
    driver.close()

if __name__ == "__main__":
    main()
