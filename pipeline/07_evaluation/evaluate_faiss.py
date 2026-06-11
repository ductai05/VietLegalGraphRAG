import json
import subprocess
import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVAL_FILE = BASE_DIR / "pipeline" / "07_evaluation" / "eval_questions.json"
DEFAULT_FAISS_DIR = BASE_DIR / "data" / "legal_embedding" / "faiss_huy"
DEFAULT_CHUNKS_PATH = BASE_DIR / "data" / "legal_chunking_dataset" / "chunks.parquet"
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "legal_embedding" / "dense_faiss_eval_results_huy.json"

def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate FAISS index offline using eval_questions.json")
    parser.add_argument("--eval-questions", type=Path, default=DEFAULT_EVAL_FILE,
                        help="Path to eval_questions.json")
    parser.add_argument("--faiss-dir", type=Path, default=DEFAULT_FAISS_DIR,
                        help="Path to FAISS index directory")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH,
                        help="Path to chunks.parquet")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help="Path to save evaluation results JSON")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Recall/MRR/nDCG top-k threshold")
    parser.add_argument("--device", type=str, default=None,
                        help="Device to run query encoder on (e.g. cuda:0, cpu)")
    return parser.parse_args()

def convert_to_gold_jsonl(eval_file: Path) -> Path:
    gold_file = eval_file.parent / "eval_questions_gold.jsonl"
    print(f"Converting {eval_file} to JSONL gold format at {gold_file}...")
    
    with open(eval_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    questions = data.get("questions", [])
    
    with open(gold_file, "w", encoding="utf-8") as f:
        for q in questions:
            gold_row = {
                "query": q["question"],
                "relevant_chunk_ids": q["evidence"]["chunk_ids"],
                "relevant_doc_ids": [q["evidence"]["doc_id"]],
                "group": q.get("question_type", "unknown")
            }
            f.write(json.dumps(gold_row, ensure_ascii=False) + "\n")
            
    print(f"Successfully converted {len(questions)} questions.")
    return gold_file

def main():
    args = parse_args()
    
    # 1. Check dependencies
    if not args.eval_questions.exists():
        print(f"Error: Evaluation file {args.eval_questions} not found.")
        sys.exit(1)
        
    if not args.faiss_dir.exists():
        print(f"Error: FAISS directory {args.faiss_dir} not found.")
        sys.exit(1)
        
    if not args.chunks.exists():
        print(f"Error: Chunks file {args.chunks} not found.")
        sys.exit(1)

    # 2. Convert eval_questions.json to gold jsonl format
    gold_file = convert_to_gold_jsonl(args.eval_questions)

    # 3. Run evaluation script
    eval_script = BASE_DIR / "pipeline" / "04_embedding" / "evaluate_dense.py"
    cmd = [
        sys.executable,
        str(eval_script),
        "--gold", str(gold_file),
        "--faiss-dir", str(args.faiss_dir),
        "--chunks", str(args.chunks),
        "--output", str(args.output),
        "--top-k", str(args.top_k)
    ]
    if args.device:
        cmd.extend(["--device", args.device])
        
    print(f"Running evaluation command:\n{' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\nEvaluation completed successfully!")
        print(f"Results saved to: {args.output}")
        
        # Clean up temporary gold file
        gold_file.unlink(missing_ok=True)
    else:
        print(f"\nEvaluation failed with exit code: {result.returncode}")
        sys.exit(result.returncode)

if __name__ == "__main__":
    main()
