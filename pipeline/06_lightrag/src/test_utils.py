"""
Unit tests for pipeline/06_lightrag/src/utils.py
"""

import asyncio
import os
import sys
import tempfile
import pytest

# Add pipeline/06_lightrag/src to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    LightRAGConfig,
    load_config,
    setup_logger,
    make_llm_func,
    make_embedding_func,
    load_corpus,
)


def test_load_config():
    config = load_config()
    assert isinstance(config, LightRAGConfig)
    assert config.chunk_token_size == 1200
    assert config.embedding_dim == 1024


def test_setup_logger():
    logger = setup_logger("test_logger")
    assert logger.name == "test_logger"


@pytest.mark.asyncio
async def test_make_llm_func():
    config = LightRAGConfig(llm_api_key="mock", llm_base_url="http://mock-url")
    llm_func = make_llm_func(config, role="index")
    assert callable(llm_func)


@pytest.mark.asyncio
async def test_make_embedding_func_mock():
    config = LightRAGConfig(embedding_provider="mock", embedding_dim=128)
    emb_func = make_embedding_func(config)
    assert emb_func is not None

    if hasattr(emb_func, "embedding_func"):
        vecs = await emb_func.embedding_func(["xóa bỏ", "thành lập công ty"])
    else:
        vecs = await emb_func(["xóa bỏ", "thành lập công ty"])

    assert vecs.shape[0] == 2
    assert vecs.shape[1] == 128


def test_load_corpus():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = os.path.join(tmpdir, "doc1.json")
        with open(json_file, "w", encoding="utf-8") as f:
            f.write('[{"id": "doc1", "text": "Văn bản pháp luật thử nghiệm."}]')

        docs = load_corpus(tmpdir, glob_pattern="*.json")
        assert len(docs) == 1
        assert docs[0]["id"] == "doc1"
        assert docs[0]["text"] == "Văn bản pháp luật thử nghiệm."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
