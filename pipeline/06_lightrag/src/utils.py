"""
Utility functions for LightRAG Integration Pipeline.
Includes configuration loader, logger setup, LLM factory, Embedding factory, and corpus loader.
"""

from __future__ import annotations

import os
import glob
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import dotenv
import numpy as np


@dataclass
class LightRAGConfig:
    # Indexing LLM (vLLM / H100)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "Qwen/Qwen3-8B"
    llm_max_tokens: int = 32768
    llm_temperature: float = 0.0
    llm_max_async: int = 4

    # Query LLM (External API)
    query_llm_base_url: str = "https://api.openai.com/v1"
    query_llm_api_key: str = "EMPTY"
    query_llm_model: str = "gpt-4o-mini"
    query_llm_temperature: float = 0.0

    # Embedding
    embedding_provider: str = "hf_local"  # hf_local | openai_compatible | mock
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_max_token_size: int = 8192
    embedding_batch_size: int = 32
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = None

    # Storage & Workspace
    working_dir: str = "./lightrag_index"
    graph_storage: str = "NetworkXStorage"
    kv_storage: str = "JsonKVStorage"
    vector_storage: str = "NanoVectorDBStorage"

    # Indexing Params
    chunk_token_size: int = 1200
    chunk_overlap_token_size: int = 100
    entity_extract_max_gleaning: int = 1
    enable_llm_cache: bool = True

    # Input Corpus
    corpus_dir: str = "../../data/processed/cleaned/content.parquet"
    corpus_glob: str = "*.parquet"
    max_docs: int = 500
    corpus_text_field: str = "content"

    # Query Params
    query_mode: str = "hybrid"
    query_top_k: int = 10
    query_max_token_for_text_unit: int = 4000
    query_max_token_for_global_context: int = 4000
    query_max_token_for_local_context: int = 4000

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> LightRAGConfig:
        """Load configuration from env file or environment variables."""
        if env_path and os.path.exists(env_path):
            dotenv.load_dotenv(env_path, override=True)
        elif os.path.exists(".env.lightrag"):
            dotenv.load_dotenv(".env.lightrag", override=True)

        return cls(
            llm_base_url=os.getenv("LIGHTRAG_LLM_BASE_URL", "http://localhost:8000/v1"),
            llm_api_key=os.getenv("LIGHTRAG_LLM_API_KEY", "EMPTY"),
            llm_model=os.getenv("LIGHTRAG_LLM_MODEL", "Qwen/Qwen3-8B"),
            llm_max_tokens=int(os.getenv("LIGHTRAG_LLM_MAX_TOKENS", "32768")),
            llm_temperature=float(os.getenv("LIGHTRAG_LLM_TEMPERATURE", "0.0")),
            llm_max_async=int(os.getenv("LIGHTRAG_LLM_MAX_ASYNC", "4")),
            query_llm_base_url=os.getenv("LIGHTRAG_QUERY_LLM_BASE_URL", "https://api.openai.com/v1"),
            query_llm_api_key=os.getenv("LIGHTRAG_QUERY_LLM_API_KEY", "EMPTY"),
            query_llm_model=os.getenv("LIGHTRAG_QUERY_LLM_MODEL", "gpt-4o-mini"),
            query_llm_temperature=float(os.getenv("LIGHTRAG_QUERY_LLM_TEMPERATURE", "0.0")),
            embedding_provider=os.getenv("LIGHTRAG_EMBEDDING_PROVIDER", "hf_local"),
            embedding_model=os.getenv("LIGHTRAG_EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dim=int(os.getenv("LIGHTRAG_EMBEDDING_DIM", "1024")),
            embedding_max_token_size=int(os.getenv("LIGHTRAG_EMBEDDING_MAX_TOKEN_SIZE", "8192")),
            embedding_batch_size=int(os.getenv("LIGHTRAG_EMBEDDING_BATCH_SIZE", "32")),
            embedding_base_url=os.getenv("LIGHTRAG_EMBEDDING_BASE_URL"),
            embedding_api_key=os.getenv("LIGHTRAG_EMBEDDING_API_KEY"),
            working_dir=os.getenv("LIGHTRAG_WORKING_DIR", "./lightrag_index"),
            graph_storage=os.getenv("LIGHTRAG_GRAPH_STORAGE", "NetworkXStorage"),
            kv_storage=os.getenv("LIGHTRAG_KV_STORAGE", "JsonKVStorage"),
            vector_storage=os.getenv("LIGHTRAG_VECTOR_STORAGE", "NanoVectorDBStorage"),
            chunk_token_size=int(os.getenv("LIGHTRAG_CHUNK_TOKEN_SIZE", "1200")),
            chunk_overlap_token_size=int(os.getenv("LIGHTRAG_CHUNK_OVERLAP_TOKEN_SIZE", "100")),
            entity_extract_max_gleaning=int(os.getenv("LIGHTRAG_ENTITY_EXTRACT_MAX_GLEANING", "1")),
            enable_llm_cache=os.getenv("LIGHTRAG_ENABLE_LLM_CACHE", "true").lower() in ("true", "1", "yes"),
            corpus_dir=os.getenv("LIGHTRAG_CORPUS_DIR", "../../data/processed/cleaned/content.parquet"),
            corpus_glob=os.getenv("LIGHTRAG_CORPUS_GLOB", "*.parquet"),
            max_docs=int(os.getenv("LIGHTRAG_MAX_DOCS", "500")),
            corpus_text_field=os.getenv("LIGHTRAG_CORPUS_TEXT_FIELD", "content"),
            query_mode=os.getenv("LIGHTRAG_QUERY_MODE", "hybrid"),
            query_top_k=int(os.getenv("LIGHTRAG_QUERY_TOP_K", "10")),
            query_max_token_for_text_unit=int(os.getenv("LIGHTRAG_QUERY_MAX_TOKEN_FOR_TEXT_UNIT", "4000")),
            query_max_token_for_global_context=int(os.getenv("LIGHTRAG_QUERY_MAX_TOKEN_FOR_GLOBAL_CONTEXT", "4000")),
            query_max_token_for_local_context=int(os.getenv("LIGHTRAG_QUERY_MAX_TOKEN_FOR_LOCAL_CONTEXT", "4000")),
        )


def load_config(env_path: Optional[str] = None) -> LightRAGConfig:
    """Load configuration helper function."""
    return LightRAGConfig.from_env(env_path)


def setup_logger(
    name: str = "lightrag_pipeline",
    log_file: Optional[str] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Setup structured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def make_llm_func(
    config: LightRAGConfig, role: str = "index"
) -> Callable[..., Coroutine[Any, Any, str]]:
    """
    Factory creating async LLM callback function for LightRAG.
    LightRAG expects signature:
    async def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str
    """
    base_url = config.llm_base_url if role == "index" else config.query_llm_base_url
    api_key = config.llm_api_key if role == "index" else config.query_llm_api_key
    model = config.llm_model if role == "index" else config.query_llm_model
    temperature = config.llm_temperature if role == "index" else config.query_llm_temperature
    max_tokens = config.llm_max_tokens if role == "index" else 4096

    logger = setup_logger("lightrag_llm")

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    except Exception:
        client = None

    async def llm_model_func(
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
    ) -> str:
        if client is None or api_key == "EMPTY" and "localhost" not in base_url and "127.0.0.1" not in base_url:
            logger.warning(f"No valid LLM client for {base_url}. Returning mock response.")
            if "keyword" in prompt.lower() or "keyword" in (system_prompt or "").lower() or kwargs.get("keyword_extraction"):
                return '{"high_level_keywords": ["pháp luật", "doanh nghiệp"], "low_level_keywords": ["thành lập", "điều kiện"]}'
            return f"[Mock Legal LLM Answer for prompt: {prompt[:60]}...]"

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history_messages:
            messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=kwargs.get("temperature", temperature),
                max_tokens=kwargs.get("max_tokens", max_tokens),
            )
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as exc:
            logger.warning(f"Calling LLM endpoint ({base_url}, model={model}) failed: {exc}. Falling back to mock response.")
            return f"[Mock Legal Response for: {prompt[:60]}...]"

    return llm_model_func


def make_embedding_func(config: LightRAGConfig) -> Any:
    """
    Factory creating LightRAG compatible EmbeddingFunc object or callback.
    """
    logger = setup_logger("lightrag_embedding")

    try:
        from lightrag.utils import EmbeddingFunc
    except ImportError:
        EmbeddingFunc = None

    provider = config.embedding_provider.lower()

    if provider == "mock":
        dim = config.embedding_dim

        async def mock_embedding(texts: List[str]) -> np.ndarray:
            vecs = []
            for t in texts:
                np.random.seed(abs(hash(t)) % (2**32))
                vecs.append(np.random.randn(dim))
            return np.array(vecs, dtype=np.float32)

        if EmbeddingFunc:
            return EmbeddingFunc(
                embedding_dim=dim,
                func=mock_embedding,
                max_token_size=config.embedding_max_token_size,
            )
        return mock_embedding

    elif provider == "hf_local":
        try:
            from sentence_transformers import SentenceTransformer
            model_name = config.embedding_model
            logger.info(f"Loading local SentenceTransformer model: {model_name}")
            st_model = SentenceTransformer(model_name)
            get_dim_fn = getattr(st_model, "get_embedding_dimension", getattr(st_model, "get_sentence_embedding_dimension", None))
            dim = (get_dim_fn() if get_dim_fn else None) or config.embedding_dim

            async def st_embedding(texts: List[str]) -> np.ndarray:
                embeddings = st_model.encode(texts, batch_size=config.embedding_batch_size, show_progress_bar=False)
                return np.array(embeddings, dtype=np.float32)

            if EmbeddingFunc:
                return EmbeddingFunc(
                    embedding_dim=dim,
                    func=st_embedding,
                    max_token_size=config.embedding_max_token_size,
                )
            return st_embedding
        except Exception as e:
            logger.warning(f"Failed to load sentence_transformers ({e}). Falling back to mock embeddings.")
            return make_embedding_func(LightRAGConfig(embedding_provider="mock"))

    elif provider == "openai_compatible":
        try:
            from openai import AsyncOpenAI
            base_url = config.embedding_base_url or config.llm_base_url
            api_key = config.embedding_api_key or config.llm_api_key
            client = AsyncOpenAI(base_url=base_url, api_key=api_key)

            async def openai_embedding(texts: List[str]) -> np.ndarray:
                resp = await client.embeddings.create(
                    model=config.embedding_model,
                    input=texts,
                )
                embeddings = [data.embedding for data in resp.data]
                return np.array(embeddings, dtype=np.float32)

            if EmbeddingFunc:
                return EmbeddingFunc(
                    embedding_dim=config.embedding_dim,
                    func=openai_embedding,
                    max_token_size=config.embedding_max_token_size,
                )
            return openai_embedding
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI embedding client ({e}). Falling back to mock embeddings.")
            return make_embedding_func(LightRAGConfig(embedding_provider="mock"))

    else:
        logger.warning(f"Unknown embedding provider '{provider}'. Falling back to mock embeddings.")
        return make_embedding_func(LightRAGConfig(embedding_provider="mock"))


def load_corpus(
    corpus_dir_or_config: Union[str, LightRAGConfig],
    glob_pattern: str = "*.json",
    max_docs: int = 0,
    text_field: str = "text",
) -> List[Dict[str, Any]]:
    """
    Scans directory or file path for corpus files (.json, .jsonl, .txt, .parquet) and returns structured documents.
    """
    logger = setup_logger("lightrag_corpus")

    if isinstance(corpus_dir_or_config, LightRAGConfig):
        cfg = corpus_dir_or_config
        corpus_dir = cfg.corpus_dir
        glob_pattern = cfg.corpus_glob
        max_docs = cfg.max_docs
        text_field = cfg.corpus_text_field
    else:
        corpus_dir = corpus_dir_or_config

    abs_corpus_path = os.path.abspath(corpus_dir)
    logger.info(f"Loading corpus from: {abs_corpus_path}")

    if not os.path.exists(abs_corpus_path):
        logger.warning(f"Corpus path {abs_corpus_path} does not exist. Returning empty corpus.")
        return []

    matched_files: List[str] = []
    if os.path.isfile(abs_corpus_path):
        matched_files = [abs_corpus_path]
    else:
        search_path = os.path.join(abs_corpus_path, glob_pattern)
        matched_files = glob.glob(search_path, recursive=True)
        if not matched_files:
            matched_files = glob.glob(os.path.join(abs_corpus_path, "*"), recursive=True)
        matched_files = [f for f in matched_files if os.path.isfile(f)]

    logger.info(f"Found {len(matched_files)} file(s) for corpus loading.")

    import json
    documents: List[Dict[str, Any]] = []

    for file_path in matched_files:
        if max_docs > 0 and len(documents) >= max_docs:
            break

        file_ext = os.path.splitext(file_path)[1].lower()

        try:
            if file_ext == ".json":
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if max_docs > 0 and len(documents) >= max_docs:
                                break
                            if isinstance(item, dict):
                                text = item.get(text_field) or item.get("content") or item.get("text_vietnamese") or str(item)
                                documents.append({
                                    "id": str(item.get("id") or item.get("doc_id") or len(documents)),
                                    "text": text,
                                    "source": file_path,
                                    "metadata": item,
                                })
                    elif isinstance(data, dict):
                        text = data.get(text_field) or data.get("content") or str(data)
                        documents.append({
                            "id": str(data.get("id") or len(documents)),
                            "text": text,
                            "source": file_path,
                            "metadata": data,
                        })

            elif file_ext in (".jsonl", ".ndjson"):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if max_docs > 0 and len(documents) >= max_docs:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        if isinstance(item, dict):
                            text = item.get(text_field) or item.get("content") or str(item)
                            documents.append({
                                "id": str(item.get("id") or len(documents)),
                                "text": text,
                                "source": file_path,
                                "metadata": item,
                            })

            elif file_ext in (".txt", ".md"):
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                    if text:
                        documents.append({
                            "id": f"{os.path.basename(file_path)}_{len(documents)}",
                            "text": text,
                            "source": file_path,
                            "metadata": {"filename": os.path.basename(file_path)},
                        })

            elif file_ext == ".parquet":
                try:
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(file_path)
                    limit = max_docs if max_docs > 0 else 500
                    batch_iter = pf.iter_batches(batch_size=min(limit, 1000))
                    
                    for batch in batch_iter:
                        if max_docs > 0 and len(documents) >= max_docs:
                            break
                        df_batch = batch.to_pandas()
                        for _, row in df_batch.iterrows():
                            if max_docs > 0 and len(documents) >= max_docs:
                                break
                            row_dict = row.to_dict()
                            text = (
                                str(row_dict.get("content") or "")
                                or str(row_dict.get(text_field) or "")
                                or str(row_dict.get("text_vietnamese") or "")
                            ).strip()
                            if text:
                                documents.append({
                                    "id": str(row_dict.get("id") or row_dict.get("doc_id") or len(documents)),
                                    "text": text,
                                    "source": str(row_dict.get("source") or file_path),
                                    "metadata": {k: v for k, v in row_dict.items() if k != "content"},
                                })
                except Exception as pe:
                    logger.warning(f"PyArrow parquet streaming failed ({pe}). Trying pandas head...")
                    try:
                        import pandas as pd
                        df = pd.read_parquet(file_path)
                        if max_docs > 0:
                            df = df.head(max_docs)
                        for _, row in df.iterrows():
                            row_dict = row.to_dict()
                            text = str(row_dict.get("content") or row_dict.get(text_field) or "").strip()
                            if text:
                                documents.append({
                                    "id": str(row_dict.get("id") or len(documents)),
                                    "text": text,
                                    "source": str(row_dict.get("source") or file_path),
                                    "metadata": {k: v for k, v in row_dict.items() if k != "content"},
                                })
                    except Exception as pde:
                        logger.warning(f"Could not read parquet file {file_path}: {pde}")

        except Exception as exc:
            logger.warning(f"Error reading file {file_path}: {exc}")

    logger.info(f"Successfully loaded {len(documents)} document items.")
    return documents
