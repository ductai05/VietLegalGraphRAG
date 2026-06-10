"""Generate synthetic queries using AI Studio for sparse retrieval evaluation."""

import argparse
import json
import os
import time
from pathlib import Path

import google.generativeai as genai
import polars as pl
from tqdm import tqdm


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=Path("/kaggle/input/legal-chunking-dataset/chunks.parquet"))
    parser.add_argument("--output", type=Path, default=Path("/kaggle/working/synthetic_queries.jsonl"))
    parser.add_argument("--num-samples", type=int, default=100)
    parser.add_argument("--model", type=str, default="gemma-4-31b-it")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sleep", type=int, default=2, help="Thời gian chờ giữa các lần gọi API (giây).")
    return parser.parse_args()


def generate_query(model: genai.GenerativeModel, chunk_text: str) -> str:
    prompt = f"""Bạn là một người dùng đang tìm kiếm thông tin về pháp luật Việt Nam. 
Hãy đọc đoạn văn bản pháp luật dưới đây và tạo ra MỘT câu hỏi tìm kiếm (query) bằng tiếng Việt tự nhiên mà bạn sẽ dùng để tìm ra đoạn văn bản này. 
Câu hỏi nên ngắn gọn, giống như người bình thường gõ trên Google. Không cần giải thích thêm, CHỈ in ra câu hỏi.

Đoạn văn bản:
{chunk_text}

Câu hỏi:"""
    try:
        response = model.generate_content(prompt)
        if response.parts:
            text = response.text.strip()
            if "\n" in text:
                text = text.split("\n")[0]
            text = text.replace("Câu hỏi:", "").strip()
            text = text.replace('"', '').strip()
            return text
        return ""
    except Exception as e:
        print(f"Lỗi khi gọi API: {e}")
        return ""


def main():
    args = parse_args()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Biến môi trường GEMINI_API_KEY chưa được thiết lập.")
    
    genai.configure(api_key=api_key)
    
    print(f"Loading chunks from {args.chunks}")
    df = pl.read_parquet(args.chunks)
    
    if "chunk_text" in df.columns:
        df = df.filter(pl.col("chunk_text").is_not_null())
        df = df.filter(pl.col("chunk_text").str.len_chars() > 50)
    else:
        raise ValueError("Không tìm thấy cột 'chunk_text' trong file parquet.")
        
    if "chunk_type" in df.columns:
        df = df.filter(pl.col("chunk_type").is_in(["prose", "article", "clause"]))
        
    print(f"Total valid chunks: {len(df)}")
    
    sampled_df = df.sample(n=min(args.num_samples, len(df)), seed=args.seed)
    
    model = genai.GenerativeModel(args.model)
    
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating queries with model: {args.model}")
    with open(args.output, "w", encoding="utf-8") as f:
        for row in tqdm(sampled_df.iter_rows(named=True), total=len(sampled_df)):
            chunk_id = row.get("chunk_id")
            doc_id = row.get("doc_id")
            chunk_text = row.get("chunk_text")
            
            query = generate_query(model, chunk_text)
            
            if query:
                item = {
                    "query": query,
                    "expected_chunk_ids": [str(chunk_id)],
                    "expected_doc_ids": [doc_id] if doc_id is not None else [],
                    "group": "synthetic"
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()
                results.append(item)
            
            time.sleep(args.sleep)
            
    print(f"Đã tạo và lưu {len(results)} câu hỏi tại {args.output}")


if __name__ == "__main__":
    main()
