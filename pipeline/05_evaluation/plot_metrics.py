"""
Plot retrieval metrics (Recall, MRR, NDCG) across multiple configurations.
Usage: 
python pipeline/05_evaluation/plot_metrics.py \
    --dense data/legal_embedding/dense_eval_results.json \
    --sparse data/legal_embedding/sparse_eval_results.json \
    --hybrid data/legal_embedding/hybrid_eval_results.json \
    --hybrid-rerank data/legal_embedding/hybrid_rerank_eval_results.json \
    --output output/retrieval_metrics_comparison.png
"""

import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dense", type=Path, help="Path to dense eval results JSON")
    parser.add_argument("--sparse", type=Path, help="Path to sparse eval results JSON")
    parser.add_argument("--hybrid", type=Path, help="Path to hybrid eval results JSON")
    parser.add_argument("--rerank-k20", type=Path, help="Path to rerank K=20 eval results JSON")
    parser.add_argument("--rerank-k30", type=Path, help="Path to rerank K=30 eval results JSON")
    parser.add_argument("--rerank-k40", type=Path, help="Path to rerank K=40 eval results JSON")
    parser.add_argument("--rerank-k50", type=Path, help="Path to rerank K=50 eval results JSON")
    parser.add_argument("--graph", type=Path, help="Path to graph eval results JSON")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output", help="Directory to save the output charts")
    return parser.parse_args()

def extract_metrics(report: dict, prefix: str = "", is_hybrid_file: bool = False, use_rrf: bool = False):
    """
    Extract recall, mrr, ndcg for various ks from a report dict.
    Returns: recall_dict, mrr_dict, ndcg_dict mapping k to float value.
    """
    recall, mrr, ndcg = {}, {}, {}
    target_dict = report
    if "summary" in report:
        target_dict = report["summary"]
        
    if use_rrf and "rrf_metrics" in report:
        target_dict = report["rrf_metrics"]
        prefix = "rrf_"
    elif is_hybrid_file and not use_rrf:
        prefix = ""

    for key, value in target_dict.items():
        if key.startswith(f"{prefix}recall@"):
            k = int(key.split("@")[1])
            recall[k] = value
        elif key.startswith(f"{prefix}mrr@"):
            k = int(key.split("@")[1])
            mrr[k] = value
        elif key.startswith(f"{prefix}ndcg@"):
            k = int(key.split("@")[1])
            ndcg[k] = value
            
    return recall, mrr, ndcg

def plot_metric_chart(title, k_values, data_dict, labels, output_path):
    fig, ax = plt.subplots(figsize=(8, 6))
    
    markers = ['o', 's', '^', 'D', 'v', '<', '>']
    
    for i, label in enumerate(labels):
        values = data_dict[label]
        if not values:
            continue
        y_vals = [values.get(k, 0) for k in k_values]
        marker = markers[i % len(markers)]
        ax.plot(k_values, y_vals, marker=marker, linewidth=2, label=label)
            
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
    ax.set_xticks(k_values)
    ax.set_xticklabels([f"k={k}" for k in k_values])
    ax.set_ylim(0, 1.1)
    ax.legend(loc="upper left")
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved {title} plot to {output_path}")

def plot_reranker_k_tuning(rerank_configs, output_path):
    target_ks = [20, 30, 40, 50]
    available_ks = [k for k in target_ks if k in rerank_configs]
    if not available_ks:
        available_ks = sorted(list(rerank_configs.keys()))
        
    if not available_ks:
        print("No reranker configs available for plotting Chart 4.")
        return
        
    fig, ax = plt.subplots(figsize=(8, 6))
    
    y_recall, y_mrr, y_ndcg = [], [], []
    
    for k_val in available_ks:
        r, m, n = rerank_configs[k_val]
        target_eval_k = 10
        if target_eval_k not in r:
            target_eval_k = max(r.keys()) if r.keys() else None
            
        if target_eval_k is not None:
            y_recall.append(r.get(target_eval_k, 0))
            y_mrr.append(m.get(target_eval_k, 0))
            y_ndcg.append(n.get(target_eval_k, 0))
        else:
            y_recall.append(0)
            y_mrr.append(0)
            y_ndcg.append(0)
            
    ax.plot(available_ks, y_recall, marker='o', color="#1f77b4", linewidth=2, label="Recall@10")
    ax.plot(available_ks, y_mrr, marker='s', color="#ff7f0e", linewidth=2, label="MRR@10")
    ax.plot(available_ks, y_ndcg, marker='^', color="#2ca02c", linewidth=2, label="NDCG@10")
    # No text annotations to avoid overlapping on line charts
            
    ax.set_title("Reranker Performance by Candidate Pool Size (K)", fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel("Candidate Pool Size (K)", fontsize=12)
    ax.set_ylabel("Metric Score", fontsize=12)
    ax.set_xticks(available_ks)
    ax.set_xticklabels([f"K={k}" for k in available_ks])
    ax.set_ylim(0, 1.1)
    ax.legend(loc="upper left")
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved Reranker K-tuning plot to {output_path}")

def main():
    args = parse_args()
    configs = []

    if args.dense and args.dense.exists():
        with open(args.dense, "r", encoding="utf-8") as f:
            data = json.load(f)
            r, m, n = extract_metrics(data)
            if r:
                configs.append(("Dense", r, m, n))

    if args.sparse and args.sparse.exists():
        with open(args.sparse, "r", encoding="utf-8") as f:
            data = json.load(f)
            r, m, n = extract_metrics(data)
            if r:
                configs.append(("Sparse", r, m, n))

    if args.hybrid and args.hybrid.exists():
        with open(args.hybrid, "r", encoding="utf-8") as f:
            data = json.load(f)
            r, m, n = extract_metrics(data, use_rrf=True)
            if r:
                configs.append(("Hybrid (RRF)", r, m, n))

    rerank_configs = {}
    for k_val in [20, 30, 40, 50]:
        arg_name = f"rerank_k{k_val}"
        path = getattr(args, arg_name, None)
        if path and path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                r, m, n = extract_metrics(data)
                if r:
                    rerank_configs[k_val] = (r, m, n)
                    if k_val == 50:
                        configs.append(("Hybrid + Rerank", r, m, n))

    if args.graph and args.graph.exists():
        with open(args.graph, "r", encoding="utf-8") as f:
            data = json.load(f)
            r, m, n = extract_metrics(data)
            if r:
                configs.append(("Hybrid + KG + Rerank", r, m, n))

    if not configs:
        print("No valid evaluation data found.")
        return

    first_r = configs[0][1]
    k_values = sorted(list(first_r.keys()))
    labels = [c[0] for c in configs]
    
    recall_data = {l: c[1] for l, c in zip(labels, configs)}
    mrr_data = {l: c[2] for l, c in zip(labels, configs)}
    ndcg_data = {l: c[3] for l, c in zip(labels, configs)}

    args.output_dir.mkdir(parents=True, exist_ok=True)

    plot_metric_chart("Recall@k", k_values, recall_data, labels, args.output_dir / "recall_comparison.png")
    plot_metric_chart("MRR@k", k_values, mrr_data, labels, args.output_dir / "mrr_comparison.png")
    plot_metric_chart("NDCG@k", k_values, ndcg_data, labels, args.output_dir / "ndcg_comparison.png")

    plot_reranker_k_tuning(rerank_configs, args.output_dir / "reranker_k_tuning.png")

if __name__ == "__main__":
    main()
