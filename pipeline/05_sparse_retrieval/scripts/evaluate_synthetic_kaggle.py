"""Kaggle wrapper script for sparse retrieval evaluation on synthetic data."""

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold", 
        type=Path, 
        default=Path("/kaggle/working/synthetic_queries.jsonl"),
        help="Path to synthetic queries JSONL file."
    )
    parser.add_argument(
        "--url", 
        type=str, 
        default="http://localhost:9200",
        help="Elasticsearch URL."
    )
    parser.add_argument(
        "--output", 
        type=Path, 
        default=Path("/kaggle/working/synthetic_evaluation_report.json"),
        help="Path to output report JSON."
    )
    parser.add_argument(
        "--index-alias", 
        type=str, 
        default="vietlegal_chunks_sparse_current",
        help="Elasticsearch index alias."
    )
    parser.add_argument(
        "--top-k", 
        type=int, 
        default=10,
        help="Top K for evaluation."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Path to the actual evaluate_sparse.py script
    script_dir = Path(__file__).parent
    eval_script = script_dir / "evaluate_sparse.py"
    
    if not eval_script.exists():
        print(f"Lỗi: Không tìm thấy file {eval_script}")
        sys.exit(1)
        
    if not args.gold.exists():
        print(f"Cảnh báo: Không tìm thấy file dữ liệu đầu vào {args.gold}")
        print("Hãy đảm bảo bạn đã chạy scripts/generate_synthetic_queries.py trước.")
        sys.exit(1)

    cmd = [
        sys.executable,
        str(eval_script),
        "--gold", str(args.gold),
        "--url", args.url,
        "--index-alias", args.index_alias,
        "--output", str(args.output),
        "--top-k", str(args.top_k)
    ]
    
    print(f"Running evaluation: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        print(f"Đánh giá hoàn tất. Kết quả được lưu tại: {args.output}")
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi chạy script đánh giá: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
