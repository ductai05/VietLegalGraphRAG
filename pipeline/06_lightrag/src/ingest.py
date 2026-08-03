"""
Ingestion script for LightRAG Integration Pipeline.
Reads Vietnamese legal document corpus, extracts entities/relations using LightRAG, and builds graph index.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any, List, Dict

# Ensure local imports work when executed directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    LightRAGConfig,
    load_config,
    setup_logger,
    make_llm_func,
    make_embedding_func,
    load_corpus,
)

from legal_ontology import (
    ENTITY_TYPES,
    RELATION_TYPES,
    LEGAL_ENTITY_EXTRACTION_SYSTEM_PROMPT,
)


async def run_ingestion(
    config: LightRAGConfig,
    corpus_input: str,
    max_docs: int = 0,
    working_dir: str = "",
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    logger = setup_logger("lightrag_ingest")

    if working_dir:
        config.working_dir = working_dir
    os.makedirs(config.working_dir, exist_ok=True)

    logger.info(f"Target Working Directory: {os.path.abspath(config.working_dir)}")
    logger.info(f"LLM Base URL: {config.llm_base_url} (Model: {config.llm_model})")
    logger.info(f"Embedding Provider: {config.embedding_provider} (Model: {config.embedding_model})")

    # Load corpus
    if not corpus_input:
        real_parquet = os.path.abspath("data/processed/cleaned/content.parquet")
        if os.path.exists(real_parquet):
            corpus_input = real_parquet
            logger.info(f"Auto-selected real corpus data file: {corpus_input}")

    logger.info("Loading document corpus...")
    docs = load_corpus(
        corpus_dir_or_config=corpus_input if corpus_input else config,
        glob_pattern=config.corpus_glob,
        max_docs=max_docs if max_docs > 0 else config.max_docs,
        text_field=config.corpus_text_field,
    )

    if not docs:
        logger.error("No documents found to index! Exiting.")
        return {"status": "error", "message": "No documents found."}

    texts = [d["text"] for d in docs if d.get("text")]
    logger.info(f"Prepared {len(texts)} document texts for indexing.")

    # Initialize LightRAG
    try:
        from lightrag import LightRAG
    except ImportError:
        logger.error("lightrag-hku package is not installed. Please run `pip install -r requirements.txt`.")
        return {"status": "error", "message": "lightrag-hku not installed."}

    llm_func = make_llm_func(config, role="index")
    embedding_func = make_embedding_func(config)

    logger.info("Initializing LightRAG instance...")

    # Configure entity types and custom prompt if supported
    rag = LightRAG(
        working_dir=config.working_dir,
        llm_model_func=llm_func,
        embedding_func=embedding_func,
        addon_params={
            "entity_types": ENTITY_TYPES,
            "relation_types": RELATION_TYPES,
            "language": "Vietnamese",
        },
    )

    # Initialize storage tables if required by LightRAG
    if hasattr(rag, "initialize_storages"):
        logger.info("Initializing LightRAG storages...")
        await rag.initialize_storages()

    start_time = time.time()
    logger.info("Starting document insertion into LightRAG...")

    try:
        # Use ainsert if available (AsyncLightRAG or LightRAG.ainsert)
        if hasattr(rag, "ainsert"):
            await rag.ainsert(texts)
        elif hasattr(rag, "insert"):
            rag.insert(texts)
        else:
            logger.error("LightRAG instance has neither ainsert nor insert method.")
            return {"status": "error", "message": "Invalid LightRAG interface."}

        elapsed = time.time() - start_time
        logger.info(f"Indexing completed successfully in {elapsed:.2f} seconds.")

        # Collect summary stats
        graph_file = os.path.join(config.working_dir, "graph_chunk_entity_relation.graphml")
        has_graph = os.path.exists(graph_file)

        return {
            "status": "success",
            "docs_indexed": len(texts),
            "elapsed_seconds": round(elapsed, 2),
            "working_dir": config.working_dir,
            "graph_file": graph_file if has_graph else None,
        }

    except Exception as exc:
        logger.error(f"Error during LightRAG insertion: {exc}", exc_info=True)
        return {"status": "error", "message": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Vietnamese legal corpus into LightRAG")
    parser.add_argument("--config", type=str, default="", help="Path to .env.lightrag config file")
    parser.add_argument("--input", type=str, default="", help="Path to corpus directory or file")
    parser.add_argument("--working-dir", type=str, default="", help="Directory to save LightRAG index")
    parser.add_argument("--max-docs", type=int, default=0, help="Maximum number of documents to index")
    parser.add_argument("--force", action="store_true", help="Force rebuild index from scratch")

    args = parser.parse_args()

    config = load_config(args.config)
    result = asyncio.run(
        run_ingestion(
            config=config,
            corpus_input=args.input,
            max_docs=args.max_docs,
            working_dir=args.working_dir,
            force_rebuild=args.force,
        )
    )

    print(f"\n[Ingest Result]: {result}")


if __name__ == "__main__":
    main()
