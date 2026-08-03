"""
Query script for LightRAG Integration Pipeline.
Supports 5 query modes: naive, local, global, hybrid, mix.
Returns formatted answers with legal reasoning and citations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure local imports work when executed directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    LightRAGConfig,
    load_config,
    setup_logger,
    make_llm_func,
    make_embedding_func,
)


async def run_query(
    query_text: str,
    config: LightRAGConfig,
    mode: str = "hybrid",
    top_k: int = 10,
    working_dir: str = "",
) -> Dict[str, Any]:
    logger = setup_logger("lightrag_query")

    if working_dir:
        config.working_dir = working_dir
    os.makedirs(config.working_dir, exist_ok=True)

    try:
        from lightrag import LightRAG, QueryParam
    except ImportError:
        logger.error("lightrag-hku package is not installed.")
        return {"error": "lightrag-hku not installed"}

    llm_func = make_llm_func(config, role="query")
    embedding_func = make_embedding_func(config)

    logger.info(f"Initializing LightRAG query engine on: {config.working_dir}")
    rag = LightRAG(
        working_dir=config.working_dir,
        llm_model_func=llm_func,
        embedding_func=embedding_func,
    )

    if hasattr(rag, "initialize_storages"):
        await rag.initialize_storages()

    logger.info(f"Executing query (mode={mode}, top_k={top_k}): {query_text}")
    start_time = time.time()

    param = QueryParam(
        mode=mode,
        top_k=top_k if top_k > 0 else config.query_top_k,
        chunk_top_k=top_k if top_k > 0 else config.query_top_k,
    )

    try:
        if hasattr(rag, "aquery"):
            answer = await rag.aquery(query_text, param=param)
        elif hasattr(rag, "query"):
            answer = rag.query(query_text, param=param)
        else:
            answer = "Error: LightRAG query method not found."

        latency_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "query": query_text,
            "mode": mode,
            "answer": str(answer),
            "latency_ms": latency_ms,
            "working_dir": config.working_dir,
        }

    except Exception as exc:
        logger.error(f"Error during query execution: {exc}", exc_info=True)
        return {
            "query": query_text,
            "mode": mode,
            "error": str(exc),
            "latency_ms": round((time.time() - start_time) * 1000, 2),
        }


async def batch_queries(
    queries: List[str],
    config: LightRAGConfig,
    mode: str = "hybrid",
    working_dir: str = "",
) -> List[Dict[str, Any]]:
    results = []
    for q in queries:
        res = await run_query(q, config=config, mode=mode, working_dir=working_dir)
        results.append(res)
    return results


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Query LightRAG index for Vietnamese Legal Q&A")
    parser.add_argument("--config", type=str, default="", help="Path to .env.lightrag config file")
    parser.add_argument("--query", type=str, default="", help="Question text")
    parser.add_argument("--mode", type=str, default="hybrid", choices=["naive", "local", "global", "hybrid", "mix"])
    parser.add_argument("--working-dir", type=str, default="", help="Directory containing LightRAG index")
    parser.add_argument("--top-k", type=int, default=10, help="Top-K context chunks/entities")
    parser.add_argument("--output-json", type=str, default="", help="Save response to JSON file")
    parser.add_argument("--queries-file", type=str, default="", help="JSON file containing list of query strings")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.queries_file and os.path.exists(args.queries_file):
        with open(args.queries_file, "r", encoding="utf-8") as f:
            queries_data = json.load(f)
            if isinstance(queries_data, list):
                queries = [q if isinstance(q, str) else q.get("query", "") for q in queries_data]
            else:
                queries = [args.query]
        results = asyncio.run(batch_queries(queries, config=config, mode=args.mode, working_dir=args.working_dir))
        output_str = json.dumps(results, ensure_ascii=False, indent=2)
    else:
        query_text = args.query or "Điều kiện thành lập công ty TNHH một thành viên?"
        result = asyncio.run(run_query(query_text, config=config, mode=args.mode, top_k=args.top_k, working_dir=args.working_dir))
        results = [result]
        output_str = json.dumps(result, ensure_ascii=False, indent=2)

    print("\n=================== QUERY RESULT ===================")
    print(output_str)

    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"\nSaved result to: {args.output_json}")


if __name__ == "__main__":
    main()
