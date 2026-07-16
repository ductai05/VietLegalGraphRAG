"""Build report-ready tables and figures from retrieval and LLM evaluations."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output"
REPORT_DIR = OUTPUT / "report_artifacts"

MODELS = (
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "groq/qwen/qwen3-32b",
    "groq/qwen/qwen3.6-27b",
)
COMPLETE_RESPONSES = OUTPUT / "llm_evaluation" / "responses.jsonl"

RETRIEVAL_RUNS = {
    "Dense": OUTPUT / "elasticsearch_dense_eval.json",
    "Sparse (BM25)": OUTPUT / "elasticsearch_sparse_eval.json",
    "Hybrid (RRF)": OUTPUT / "elasticsearch_hybrid_rerank_eval.json",
    "Hybrid + Rerank": OUTPUT / "elasticsearch_hybrid_rerank_eval.json",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def successful_unique(
    path: Path,
    *,
    model: str,
    setup: str,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        if (
            row.get("status") == "ok"
            and row.get("model") == model
            and row.get("setup") == setup
        ):
            rows[row["question_id"]] = row
    return [rows[key] for key in sorted(rows)]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_llm() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary: dict[str, Any] = {}
    flat: list[dict[str, Any]] = []
    for model in MODELS:
        setups = {
            setup: successful_unique(
                COMPLETE_RESPONSES,
                model=model,
                setup=setup,
            )
            for setup in ("no_rag", "hybrid_rerank", "hybrid_graph")
        }
        model_result: dict[str, Any] = {}
        for setup, rows in setups.items():
            item = {
                "questions": len(rows),
                "accuracy": mean([float(row["correct"]) for row in rows]),
                "valid_json_rate": mean([float(row["valid_json"]) for row in rows]),
                "mean_latency_seconds": mean(
                    [float(row["latency_seconds"]) for row in rows]
                ),
            }
            if setup in ("hybrid_rerank", "hybrid_graph"):
                item.update(
                    {
                        "citation_validity": mean(
                            [float(row["citation_valid"]) for row in rows]
                        ),
                        "gold_citation_rate": mean(
                            [float(row["cites_gold"]) for row in rows]
                        ),
                        "retrieval_hit_rate": mean(
                            [float(row["retrieval_hit"]) for row in rows]
                        ),
                        "accuracy_when_retrieval_hit": mean(
                            [
                                float(row["correct"])
                                for row in rows
                                if row["retrieval_hit"]
                            ]
                        ),
                        "accuracy_when_retrieval_miss": mean(
                            [
                                float(row["correct"])
                                for row in rows
                                if not row["retrieval_hit"]
                            ]
                        ),
                        "refusal_rate": mean(
                            [
                                1.0 if row.get("predicted_answer") == "E" else 0.0
                                for row in rows
                            ]
                        ),
                        "refusal_when_retrieval_miss": mean(
                            [
                                1.0 if row.get("predicted_answer") == "E" else 0.0
                                for row in rows
                                if not row["retrieval_hit"]
                            ]
                        ),
                        "hallucination_when_retrieval_miss": mean(
                            [
                                1.0 if row.get("predicted_answer") in {"A", "B", "C", "D"} and not row["correct"] else 0.0
                                for row in rows
                                if not row["retrieval_hit"]
                            ]
                        ),
                    }
                )
            by_type = {}
            for kind in sorted({row["question_type"] for row in rows}):
                subset = [row for row in rows if row["question_type"] == kind]
                by_type[kind] = {
                    "questions": len(subset),
                    "accuracy": mean([float(row["correct"]) for row in subset]),
                }
            item["by_question_type"] = by_type
            model_result[setup] = item
            flat.append({"model": model, "setup": setup, **item})

        no_rag = {row["question_id"]: row for row in setups["no_rag"]}
        rag = {row["question_id"]: row for row in setups["hybrid_rerank"]}
        paired_ids = sorted(set(no_rag) & set(rag))
        rag_only = sum(not no_rag[q]["correct"] and rag[q]["correct"] for q in paired_ids)
        no_rag_only = sum(no_rag[q]["correct"] and not rag[q]["correct"] for q in paired_ids)
        discordant = rag_only + no_rag_only
        model_result["paired"] = {
            "questions": len(paired_ids),
            "rag_only_correct": rag_only,
            "no_rag_only_correct": no_rag_only,
            "mcnemar_exact_p": (
                binomtest(rag_only, discordant, 0.5).pvalue if discordant else 1.0
            ),
        }
        summary[model] = model_result
    return summary, flat


def summarize_retrieval() -> list[dict[str, Any]]:
    rows = []
    for name, path in RETRIEVAL_RUNS.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if name == "Hybrid (RRF)":
            metrics = payload["rrf_metrics"]
            recall = metrics["rrf_recall@10"]
            mrr = metrics["rrf_mrr@10"]
            ndcg = metrics["rrf_ndcg@10"]
        else:
            metrics = payload
            recall = metrics["recall@10"]
            mrr = metrics["mrr@10"]
            ndcg = metrics["ndcg@10"]
        rows.append(
            {
                "setup": name,
                "questions": payload["queries"],
                "recall@10": recall,
                "mrr@10": mrr,
                "ndcg@10": ndcg,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot_retrieval(rows: list[dict[str, Any]]) -> None:
    labels = [row["setup"] for row in rows]
    x = range(len(labels))
    width = 0.24
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for offset, metric, label in [
        (-width, "recall@10", "Recall@10"),
        (0, "mrr@10", "MRR@10"),
        (width, "ndcg@10", "nDCG@10"),
    ]:
        values = [row[metric] for row in rows]
        bars = ax.bar([value + offset for value in x], values, width, label=label)
        ax.bar_label(bars, fmt="%.2f", fontsize=8)
    ax.set_xticks(list(x), labels, rotation=12, ha="right")
    ax.set_ylim(0, 0.9)
    ax.set_ylabel("Score")
    ax.set_title("Retrieval performance on 200 synthetic questions")
    ax.legend()
    fig.savefig(REPORT_DIR / "retrieval_at10.png", dpi=180, bbox_inches='tight')
    plt.close(fig)


def plot_llm(summary: dict[str, Any]) -> None:
    models = list(summary)
    short = ["Llama 3.3 70B", "Llama 3.1 8B", "Qwen3 32B", "Qwen3.6 27B"]
    x = range(len(models))
    width = 0.22
    no_rag = [summary[model]["no_rag"]["accuracy"] for model in models]
    rag = [summary[model]["hybrid_rerank"]["accuracy"] for model in models]
    graph = [summary.get(model, {}).get("hybrid_graph", {}).get("accuracy", 0.0) for model in models]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    first = ax.bar([value - width for value in x], no_rag, width, label="No-RAG")
    second = ax.bar(
        list(x),
        rag,
        width,
        label="Hybrid + Rerank",
    )
    third = ax.bar(
        [value + width for value in x],
        graph,
        width,
        label="Hybrid + KG",
    )
    ax.bar_label(first, fmt="%.2f", fontsize=7)
    ax.bar_label(second, fmt="%.2f", fontsize=7)
    ax.bar_label(third, fmt="%.2f", fontsize=7)
    ax.set_xticks(list(x), short)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("MCQ accuracy")
    ax.set_title("LLM answer accuracy")
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize='small')
    fig.savefig(REPORT_DIR / "llm_accuracy.png", dpi=180, bbox_inches='tight')
    plt.close(fig)


def plot_llm_refusal(summary: dict[str, Any]) -> None:
    models = list(summary)
    short = ["Llama 3.3 70B", "Llama 3.1 8B", "Qwen3 32B", "Qwen3.6 27B"]
    x = range(len(models))
    width = 0.5
    
    # We only plot for hybrid_rerank for now
    refusal_miss = [summary.get(model, {}).get("hybrid_rerank", {}).get("refusal_when_retrieval_miss", 0.0) for model in models]
    lucky_miss = [summary.get(model, {}).get("hybrid_rerank", {}).get("accuracy_when_retrieval_miss", 0.0) for model in models]
    hallucination_miss = [summary.get(model, {}).get("hybrid_rerank", {}).get("hallucination_when_retrieval_miss", 0.0) for model in models]
    
    fig, ax = plt.subplots(figsize=(8, 4.6))
    p1 = ax.bar(list(x), refusal_miss, width, label="Refusal on Miss (Good)", color="mediumseagreen")
    p2 = ax.bar(list(x), lucky_miss, width, bottom=refusal_miss, label="Lucky Guess on Miss (Neutral)", color="gold")
    bottom_p3 = [r + l for r, l in zip(refusal_miss, lucky_miss)]
    p3 = ax.bar(list(x), hallucination_miss, width, bottom=bottom_p3, label="Hallucination on Miss (Bad)", color="crimson")
    
    ax.bar_label(p1, labels=[f"{v:.2f}" if v >= 0.05 else "" for v in refusal_miss], label_type='center', fontsize=8, color='black')
    ax.bar_label(p2, labels=[f"{v:.2f}" if v >= 0.05 else "" for v in lucky_miss], label_type='center', fontsize=8, color='black')
    ax.bar_label(p3, labels=[f"{v:.2f}" if v >= 0.05 else "" for v in hallucination_miss], label_type='center', fontsize=8, color='black')
    
    ax.set_xticks(list(x), short)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Proportion of Retrieval Misses")
    ax.set_title("LLM Behavior when Retrieval Fails (Hybrid Rerank)")
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize='small')
    fig.savefig(REPORT_DIR / "llm_refusal.png", dpi=180, bbox_inches='tight')
    plt.close(fig)


def plot_llm_valid_json(summary: dict[str, Any]) -> None:
    models = list(summary)
    short = ["Llama 3.3 70B", "Llama 3.1 8B", "Qwen3 32B", "Qwen3.6 27B"]
    x = range(len(models))
    width = 0.22
    no_rag = [summary[model].get("no_rag", {}).get("valid_json_rate", 0.0) for model in models]
    rag = [summary[model].get("hybrid_rerank", {}).get("valid_json_rate", 0.0) for model in models]
    graph = [summary[model].get("hybrid_graph", {}).get("valid_json_rate", 0.0) for model in models]
    
    fig, ax = plt.subplots(figsize=(8, 4.6))
    first = ax.bar([value - width for value in x], no_rag, width, label="No-RAG")
    second = ax.bar(list(x), rag, width, label="Hybrid + Rerank")
    third = ax.bar([value + width for value in x], graph, width, label="Hybrid + KG")
    
    ax.bar_label(first, fmt="%.2f", fontsize=7)
    ax.bar_label(second, fmt="%.2f", fontsize=7)
    ax.bar_label(third, fmt="%.2f", fontsize=7)
    ax.set_xticks(list(x), short)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Valid JSON Rate")
    ax.set_title("LLM Valid JSON Formatting Rate")
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize='small')
    fig.savefig(REPORT_DIR / "llm_valid_json.png", dpi=180, bbox_inches='tight')
    plt.close(fig)

def plot_llm_latency(summary: dict[str, Any]) -> None:
    models = list(summary)
    short = ["Llama 3.3 70B", "Llama 3.1 8B", "Qwen3 32B", "Qwen3.6 27B"]
    x = range(len(models))
    width = 0.25
    no_rag = [summary[model].get("no_rag", {}).get("mean_latency_seconds", 0.0) for model in models]
    rag = [summary[model].get("hybrid_rerank", {}).get("mean_latency_seconds", 0.0) for model in models]
    graph = [summary[model].get("hybrid_graph", {}).get("mean_latency_seconds", 0.0) for model in models]
    
    fig, ax = plt.subplots(figsize=(8, 4.6))
    first = ax.bar([value - width for value in x], no_rag, width, label="No-RAG")
    second = ax.bar(list(x), rag, width, label="Hybrid + Rerank")
    third = ax.bar([value + width for value in x], graph, width, label="Hybrid + KG")
    
    ax.bar_label(first, fmt="%.2f", fontsize=8)
    ax.bar_label(second, fmt="%.2f", fontsize=8)
    ax.bar_label(third, fmt="%.2f", fontsize=8)
    ax.set_xticks(list(x), short)
    max_y = max(max(no_rag), max(rag), max(graph)) if any(no_rag + rag + graph) else 1.0
    ax.set_ylim(0, max_y * 1.3)
    ax.set_ylabel("Latency (seconds)")
    ax.set_title("LLM Mean Latency per Question")
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize='small')
    fig.savefig(REPORT_DIR / "llm_latency.png", dpi=180, bbox_inches='tight')
    plt.close(fig)

def plot_llm_citation(summary: dict[str, Any]) -> None:
    models = list(summary)
    short = ["Llama 3.3 70B", "Llama 3.1 8B", "Qwen3 32B", "Qwen3.6 27B"]
    x = range(len(models))
    width = 0.35
    citation_validity = [summary.get(model, {}).get("hybrid_rerank", {}).get("citation_validity", 0.0) for model in models]
    gold_citation = [summary.get(model, {}).get("hybrid_rerank", {}).get("gold_citation_rate", 0.0) for model in models]
    
    fig, ax = plt.subplots(figsize=(8, 4.6))
    first = ax.bar([value - width/2 for value in x], citation_validity, width, label="Citation Validity (Valid chunk IDs)")
    second = ax.bar([value + width/2 for value in x], gold_citation, width, label="Gold Citation Rate (Actually cited Gold)")
    
    ax.bar_label(first, fmt="%.2f", fontsize=8)
    ax.bar_label(second, fmt="%.2f", fontsize=8)
    ax.set_xticks(list(x), short)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Rate")
    ax.set_title("LLM Citation Quality (Hybrid Rerank)")
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize='small')
    fig.savefig(REPORT_DIR / "llm_citation.png", dpi=180, bbox_inches='tight')
    plt.close(fig)

def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    llm_summary, llm_rows = summarize_llm()
    retrieval_rows = summarize_retrieval()
    payload = {
        "retrieval": retrieval_rows,
        "llm": llm_summary,
        "notes": {
            "questions": 200,
            "rag_context": "top-10 hybrid + rerank, 4,000-character weighted budget",
            "llm_results_complete": all(
                setups["no_rag"]["questions"] == 200
                and setups["hybrid_rerank"]["questions"] == 200
                and setups.get("hybrid_graph", {}).get("questions", 0) == 200
                for setups in llm_summary.values()
            ),
        },
    }
    (REPORT_DIR / "evaluation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        REPORT_DIR / "retrieval_metrics.csv",
        retrieval_rows,
        ["setup", "questions", "recall@10", "mrr@10", "ndcg@10"],
    )
    write_csv(
        REPORT_DIR / "llm_metrics.csv",
        llm_rows,
        [
            "model",
            "setup",
            "questions",
            "accuracy",
            "valid_json_rate",
            "mean_latency_seconds",
            "citation_validity",
            "gold_citation_rate",
            "retrieval_hit_rate",
        ],
    )
    plot_retrieval(retrieval_rows)
    plot_llm(llm_summary)
    plot_llm_refusal(llm_summary)
    plot_llm_valid_json(llm_summary)
    plot_llm_latency(llm_summary)
    plot_llm_citation(llm_summary)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
