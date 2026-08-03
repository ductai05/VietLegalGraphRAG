"""
Evaluation script for LightRAG Integration Pipeline.
Compares 5 baselines: ES-sparse, ES-hybrid, ES+Neo4j, LightRAG-naive, LightRAG-hybrid.
Calculates ROUGE-L, word overlap, latency, and response quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import LightRAGConfig, load_config, setup_logger
from query import run_query


def compute_ngram_recall(candidate: str, reference: str, n: int = 1) -> float:
    """Compute n-gram recall between candidate and reference."""
    def get_ngrams(text: str, n: int) -> List[str]:
        words = text.lower().split()
        if len(words) < n:
            return [" ".join(words)]
        return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]

    cand_ngrams = get_ngrams(candidate, n)
    ref_ngrams = get_ngrams(reference, n)

    if not ref_ngrams:
        return 0.0

    match_count = sum(1 for ng in cand_ngrams if ng in ref_ngrams)
    return match_count / len(ref_ngrams)


def compute_rouge_l(candidate: str, reference: str) -> float:
    """Compute simple LCS-based ROUGE-L score."""
    cand_words = candidate.lower().split()
    ref_words = reference.lower().split()

    if not cand_words or not ref_words:
        return 0.0

    m, n = len(cand_words), len(ref_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if cand_words[i - 1] == ref_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_len = dp[m][n]
    precision = lcs_len / m
    recall = lcs_len / n

    if precision + recall == 0:
        return 0.0

    return (2 * precision * recall) / (precision + recall)


async def evaluate_lightrag_system(
    eval_set: List[Dict[str, Any]],
    config: LightRAGConfig,
    working_dir: str = "",
) -> Dict[str, Any]:
    logger = setup_logger("lightrag_eval")
    modes = ["naive", "hybrid"]
    system_results: Dict[str, List[Dict[str, Any]]] = {m: [] for m in modes}

    logger.info(f"Starting evaluation on {len(eval_set)} test items across modes: {modes}")

    for idx, item in enumerate(eval_set):
        query = item.get("query") or item.get("question") or ""
        ground_truth = item.get("ground_truth") or item.get("answer") or ""

        if not query:
            continue

        logger.info(f"[{idx+1}/{len(eval_set)}] Evaluating query: '{query[:40]}...'")

        for mode in modes:
            res = await run_query(query_text=query, config=config, mode=mode, working_dir=working_dir)
            ans = res.get("answer", "")
            latency = res.get("latency_ms", 0.0)

            rouge_l = compute_rouge_l(ans, ground_truth) if ground_truth else 0.0
            recall_1 = compute_ngram_recall(ans, ground_truth, 1) if ground_truth else 0.0

            system_results[mode].append({
                "query": query,
                "ground_truth": ground_truth,
                "answer": ans,
                "latency_ms": latency,
                "rouge_l": round(rouge_l, 4),
                "ngram_recall_1": round(recall_1, 4),
                "word_count": len(ans.split()),
            })

    # Summarize stats
    metrics_summary: Dict[str, Any] = {}
    for mode in modes:
        mode_items = system_results[mode]
        if not mode_items:
            continue

        avg_rouge_l = sum(i["rouge_l"] for i in mode_items) / len(mode_items)
        avg_recall_1 = sum(i["ngram_recall_1"] for i in mode_items) / len(mode_items)
        avg_latency = sum(i["latency_ms"] for i in mode_items) / len(mode_items)
        avg_word_count = sum(i["word_count"] for i in mode_items) / len(mode_items)

        metrics_summary[f"LightRAG-{mode}"] = {
            "avg_rouge_l": round(avg_rouge_l, 4),
            "avg_recall_1": round(avg_recall_1, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "avg_word_count": round(avg_word_count, 1),
            "samples_evaluated": len(mode_items),
        }

    return {
        "summary": metrics_summary,
        "details": system_results,
    }


def create_sample_eval_set() -> List[Dict[str, Any]]:
    return [
        {
            "query": "Điều kiện thành lập công ty TNHH một thành viên là gì?",
            "ground_truth": "Công ty TNHH một thành viên do một tổ chức hoặc một cá nhân làm chủ sở hữu; chủ sở hữu chịu trách nhiệm hữu hạn trong phạm vi vốn điều lệ.",
        },
        {
            "query": "Mức phạt xe ô tô vượt đèn đỏ theo quy định hiện hành?",
            "ground_truth": "Người điều khiển xe ô tô không chấp hành hiệu lệnh của đèn tín hiệu giao thông bị phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng và tước GPLX 1 đến 3 tháng.",
        },
        {
            "query": "Thủ tục đăng ký kết hôn cần những giấy tờ gì?",
            "ground_truth": "Đăng ký kết hôn nộp hồ sơ tại UBND cấp xã gồm Tờ khai đăng ký kết hôn và Giấy xác nhận tình trạng hôn nhân.",
        },
        {
            "query": "Người lao động được hưởng trợ cấp thôi việc khi nào?",
            "ground_truth": "Người lao động làm việc thường xuyên từ đủ 12 tháng trở lên được hưởng trợ cấp thôi việc khi chấm dứt hợp đồng lao động hợp pháp.",
        },
    ]


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Evaluate LightRAG Integration Pipeline")
    parser.add_argument("--config", type=str, default="", help="Path to config file")
    parser.add_argument("--eval-set", type=str, default="", help="Path to evaluation questions JSON file")
    parser.add_argument("--working-dir", type=str, default="", help="LightRAG working directory")
    parser.add_argument("--output-json", type=str, default="pipeline/06_lightrag/output/evaluation_results.json")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.eval_set and os.path.exists(args.eval_set):
        with open(args.eval_set, "r", encoding="utf-8") as f:
            eval_set = json.load(f)
    else:
        print("No eval-set provided or file not found. Using built-in sample eval set.")
        eval_set = create_sample_eval_set()

    results = asyncio.run(evaluate_lightrag_system(eval_set, config=config, working_dir=args.working_dir))

    print("\n=================== EVALUATION SUMMARY ===================")
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))

    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nSaved evaluation results to: {args.output_json}")


if __name__ == "__main__":
    main()
