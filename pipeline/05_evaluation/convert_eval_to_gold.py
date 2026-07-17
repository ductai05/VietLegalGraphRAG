import argparse
import json
import polars as pl
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVAL_FILE = BASE_DIR / "data" / "eval" / "eval_questions.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_CHUNKS_FILE = BASE_DIR / "data" / "preprocessed" / "chunking" / "chunks.parquet"


def parse_args():
    parser = argparse.ArgumentParser(description="Convert evaluation questions to gold standard format")
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE,
                        help="Path to input eval questions json file")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Directory to save gold standard jsonl file")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_FILE,
                        help="Path to chunks parquet dataset for resolving equivalent chunk IDs")
    return parser.parse_args()


def main():
    args = parse_args()
    eval_file = args.eval_file
    output_dir = args.output_dir
    chunks_file = args.chunks

    output_dir.mkdir(parents=True, exist_ok=True)
    gold_file = output_dir / "eval_questions_gold.jsonl"

    if not eval_file.exists():
        print(f"Error: {eval_file} does not exist.")
        return
    if not chunks_file.exists():
        print(f"Error: {chunks_file} does not exist. Cannot resolve duplicate chunk texts.")
        return

    with open(eval_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            f.seek(0)
            rows = [json.loads(line) for line in f if line.strip()]
            data = {"questions": rows}

    questions = data.get("questions", [])
    print(f"Loaded {len(questions)} questions from {eval_file}")

    all_orig_ids = set()
    for q in questions:
        all_orig_ids.update(q["evidence"]["chunk_ids"])

    print(f"Resolving text-equivalent chunk IDs from {chunks_file}...")
    lazy_chunks = pl.scan_parquet(chunks_file, glob=False)

    evidence_chunks = (
        lazy_chunks
        .filter(pl.col("chunk_id").is_in(list(all_orig_ids)))
        .select("chunk_id", "chunk_text")
        .collect()
    )

    id_to_text = {row["chunk_id"]: row["chunk_text"] for row in evidence_chunks.iter_rows(named=True) if row["chunk_text"]}
    unique_texts = list(set(id_to_text.values()))

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

    with open(gold_file, "w", encoding="utf-8") as f:
        for q in questions:
            orig_ids = q["evidence"]["chunk_ids"]

            groups = []
            for cid in orig_ids:
                txt = id_to_text.get(cid)
                if txt and txt in text_to_ids:
                    groups.append(text_to_ids[txt])
                else:
                    groups.append([cid])

            flat_relevant_ids = list(set(item for g in groups for item in g))

            relevant_doc_ids = q.get("evidence", {}).get("doc_ids", [])
            if not relevant_doc_ids and "doc_id" in q.get("evidence", {}):
                relevant_doc_ids = [q["evidence"]["doc_id"]]

            gold_row = {
                "query": q["question"],
                "relevant_chunk_ids": flat_relevant_ids,
                "relevant_chunk_groups": groups,
                "relevant_doc_ids": [str(d) for d in relevant_doc_ids],
                "group": q.get("question_type", "unknown")
            }
            f.write(json.dumps(gold_row, ensure_ascii=False) + "\n")

    print(f"Successfully converted and saved to {gold_file}")


if __name__ == "__main__":
    main()

