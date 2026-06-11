import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVAL_FILE = BASE_DIR / "pipeline" / "07_evaluation" / "eval_questions.json"
GOLD_FILE = BASE_DIR / "pipeline" / "07_evaluation" / "eval_questions_gold.jsonl"

def main():
    if not EVAL_FILE.exists():
        print(f"Error: {EVAL_FILE} does not exist.")
        return

    with open(EVAL_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", [])
    print(f"Loaded {len(questions)} questions from {EVAL_FILE}")

    with open(GOLD_FILE, "w", encoding="utf-8") as f:
        for q in questions:
            gold_row = {
                "query": q["question"],
                "relevant_chunk_ids": q["evidence"]["chunk_ids"],
                "relevant_doc_ids": [q["evidence"]["doc_id"]],
                "group": q.get("question_type", "unknown")
            }
            f.write(json.dumps(gold_row, ensure_ascii=False) + "\n")

    print(f"Successfully converted and saved to {GOLD_FILE}")

if __name__ == "__main__":
    main()
