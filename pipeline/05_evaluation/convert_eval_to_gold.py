import json
import polars as pl
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVAL_FILE = BASE_DIR / "output" / "eval_questions.json"
GOLD_FILE = BASE_DIR / "output" / "eval_questions_gold.jsonl"
CHUNKS_FILE = BASE_DIR / "data" / "preprocessed" / "chunking" / "chunks.parquet"

def main():
    if not EVAL_FILE.exists():
        print(f"Error: {EVAL_FILE} does not exist.")
        return
    if not CHUNKS_FILE.exists():
        print(f"Error: {CHUNKS_FILE} does not exist. Cannot resolve duplicate chunk texts.")
        return

    with open(EVAL_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            f.seek(0)
            rows = [json.loads(line) for line in f if line.strip()]
            data = {"questions": rows}

    questions = data.get("questions", [])
    print(f"Loaded {len(questions)} questions from {EVAL_FILE}")

    # Collect all unique evidence chunk IDs to look up
    all_orig_ids = set()
    for q in questions:
        all_orig_ids.update(q["evidence"]["chunk_ids"])

    print("Resolving text-equivalent chunk IDs from chunks.parquet...")
    lazy_chunks = pl.scan_parquet(CHUNKS_FILE, glob=False)
    
    # Get texts of evidence chunks
    evidence_chunks = (
        lazy_chunks
        .filter(pl.col("chunk_id").is_in(list(all_orig_ids)))
        .select("chunk_id", "chunk_text")
        .collect()
    )
    
    id_to_text = {row["chunk_id"]: row["chunk_text"] for row in evidence_chunks.iter_rows(named=True) if row["chunk_text"]}
    unique_texts = list(set(id_to_text.values()))
    
    # Get all chunk IDs sharing those exact texts
    matching_chunks = (
        lazy_chunks
        .filter(pl.col("chunk_text").is_in(unique_texts))
        .select("chunk_id", "chunk_text")
        .collect()
    )
    
    text_to_ids = {}
    for row in matching_chunks.iter_rows(named=True):
        txt = row["chunk_text"]
        if txt not in text_to_ids:
            text_to_ids[txt] = []
        text_to_ids[txt].append(row["chunk_id"])

    print(f"Mapped {len(unique_texts)} unique evidence texts to equivalent chunk IDs.")

    with open(GOLD_FILE, "w", encoding="utf-8") as f:
        for q in questions:
            orig_ids = q["evidence"]["chunk_ids"]
            
            # Map each original ID to its equivalence group of IDs
            groups = []
            for cid in orig_ids:
                txt = id_to_text.get(cid)
                if txt and txt in text_to_ids:
                    groups.append(text_to_ids[txt])
                else:
                    groups.append([cid]) # Fallback to original ID if text not found
            
            # Flatten all equivalent IDs for simple lookup
            flat_relevant_ids = list(set(item for g in groups for item in g))

            # Extract doc IDs (fallback to single doc_id if doc_ids missing for compatibility)
            relevant_doc_ids = q.get("evidence", {}).get("doc_ids", [])
            if not relevant_doc_ids and "doc_id" in q.get("evidence", {}):
                relevant_doc_ids = [q["evidence"]["doc_id"]]

            gold_row = {
                "query": q["question"],
                "relevant_chunk_ids": flat_relevant_ids,
                "relevant_chunk_groups": groups,
                "relevant_doc_ids": [str(d) for d in relevant_doc_ids], # Cast to string for matching in evaluate_graph
                "group": q.get("question_type", "unknown")
            }
            f.write(json.dumps(gold_row, ensure_ascii=False) + "\n")

    print(f"Successfully converted and saved to {GOLD_FILE}")

if __name__ == "__main__":
    main()
