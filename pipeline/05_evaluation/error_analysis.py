"""
Analyze retrieval errors and extract 10 incorrect queries.
Usage:
python pipeline/05_evaluation/error_analysis.py \
    --eval-results data/legal_embedding/hybrid_rerank_eval_results.json \
    --gold pipeline/05_evaluation/eval_questions_gold.jsonl \
    --chunks data/legal_chunking_dataset/chunks.parquet \
    --output output/error_analysis.md
"""

import argparse
import json
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-results", type=Path, required=True, help="Path to best eval results JSON (e.g. hybrid_rerank)")
    parser.add_argument("--gold", type=Path, required=True, help="Path to gold eval jsonl")
    parser.add_argument("--chunks", type=Path, default=None, help="Path to chunks.parquet to get chunk text")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "error_analysis.md")
    args = parser.parse_args()

    with open(args.eval_results, "r", encoding="utf-8") as f:
        results = json.load(f)
        
    gold_data = load_jsonl(args.gold)
    gold_dict = {row["query"]: row for row in gold_data}
    
    chunks_df = None
    if args.chunks and args.chunks.exists():
        chunks_df = pd.read_parquet(args.chunks, columns=["chunk_id", "chunk_text"])
        chunks_df.set_index("chunk_id", inplace=True)
        
    text_cache = {}
    q_path = args.gold.parent / "eval_questions.json"
    if not q_path.exists():
        q_path = args.gold.parent.parent / "output" / "eval_questions.json"
    if q_path.exists():
        try:
            with open(q_path, "r", encoding="utf-8") as f:
                q_data = json.load(f)
                for q in q_data.get("questions", []):
                    ev = q.get("evidence", {})
                    for cid, text in zip(ev.get("chunk_ids", []), ev.get("chunk_texts", [])):
                        if cid and text:
                            text_cache[cid] = text
        except Exception:
            pass

    def get_chunk_text(chunk_id):
        if chunk_id in text_cache:
            return text_cache[chunk_id]
        if chunks_df is not None and chunk_id in chunks_df.index:
            try:
                val = chunks_df.loc[chunk_id]
                if isinstance(val, pd.DataFrame):
                    return val.iloc[0].get("chunk_text", "No text found")
                return val.get("chunk_text", "No text found")
            except Exception:
                pass
        return f"[{chunk_id} text not available]"

    details = results.get("details", [])
    
    errors = []
    for item in details:
        val = item.get("recall@10")
        if val is None:
            recall_keys = [k for k in item.keys() if k.startswith("recall@")]
            if recall_keys:
                max_k_key = sorted(recall_keys, key=lambda x: int(x.split("@")[1]))[-1]
                val = item[max_k_key]
            elif "recall" in item:
                val = item["recall"]
            
        if val is not None and val == 0:
            errors.append(item)
            if len(errors) >= 10:
                break
                
    if not errors:
        print("No errors found in the evaluation results!")
        return

    out_lines = [
        "# Phân tích Lỗi Retrieval (K=10)",
        "Dưới đây là các ví dụ mà hệ thống truy xuất sai trong top 10 (Recall@10 = 0) trong kết quả retrieve.",
        ""
    ]
    
    for i, err in enumerate(errors, 1):
        query = err["query"]
        out_lines.append(f"## {i}. Câu hỏi: {query}")
        gold = gold_dict.get(query, {})
        
        # Extract ground truth chunks
        true_chunks = []
        if "relevant_chunk_groups" in gold and gold["relevant_chunk_groups"]:
            for g in gold["relevant_chunk_groups"]:
                true_chunks.extend(g)
        elif "relevant_chunk_ids" in gold and gold["relevant_chunk_ids"]:
            true_chunks.extend(gold["relevant_chunk_ids"])
            
        out_lines.append("### Ground-truth Chunk(s):")
        for tc in true_chunks[:5]: # limit to 5
            raw_text = get_chunk_text(tc)
            is_truncated = len(raw_text) > 5000
            text = raw_text[:5000].replace('\n', '\n  > ')
            out_lines.append(f"- **ID**: `{tc}`")
            out_lines.append(f"  > {text}" + ("..." if is_truncated else ""))
        if len(true_chunks) > 5:
            out_lines.append(f"- *(Và {len(true_chunks) - 5} chunk khác)*")
            
        out_lines.append("\n### Kết quả Retrieve Top 5:")
        top_chunks = err.get("top_chunk_ids", [])[:5]
        for rc in top_chunks:
            raw_text = get_chunk_text(rc)
            is_truncated = len(raw_text) > 5000
            text = raw_text[:5000].replace('\n', '\n  > ')
            out_lines.append(f"- **ID**: `{rc}`")
            out_lines.append(f"  > {text}" + ("..." if is_truncated else ""))
            
        out_lines.append("\n---\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))
        
    print(f"Exported error analysis to {args.output}")

if __name__ == "__main__":
    main()
