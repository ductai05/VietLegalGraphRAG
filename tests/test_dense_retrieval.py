from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contracts import RetrievalHit  # noqa: E402
from elasticsearch_retriever import (  # noqa: E402
    ElasticsearchGraphChunkFetcher,
    ElasticsearchDenseRetriever,
    ElasticsearchTextRetriever,
)
from retrieval_modes import RetrievalRequest  # noqa: E402
from retrieval_service import RetrievalService  # noqa: E402


def _es_response(*hit_ids: str) -> dict:
    return {
        "hits": {
            "hits": [
                {
                    "_id": hit_id,
                    "_score": 1.5,
                    "_source": {
                        "chunk_id": hit_id,
                        "doc_id": "doc-1",
                        "title": "Luat Dat Dai",
                        "document_number": "31/2024/QH15",
                        "chunk_text": "noi dung",
                        "section_path": ["Dieu 5"],
                    },
                }
                for hit_id in hit_ids
            ]
        }
    }


def _request(**overrides) -> RetrievalRequest:
    payload = {"query": "dat dai", "top_k": 5, "rerank": {"enabled": False}}
    payload.update(overrides)
    return RetrievalRequest(**payload)


def _hit(chunk_id: str, score_key: str = "bm25") -> RetrievalHit:
    return RetrievalHit(
        rank=1,
        chunk_id=chunk_id,
        doc_id="doc-1",
        title="t",
        document_number="n",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text="x",
        scores={score_key: 1.0},
        citation="c",
    )


# --- B3: ElasticsearchDenseRetriever ---


def test_dense_retriever_builds_knn_body() -> None:
    client = Mock()
    client.search.return_value = _es_response("chunk:1")
    embedder = Mock()
    embedder.embed_query.return_value = [0.1, 0.2]
    retriever = ElasticsearchDenseRetriever(client, index="vietlegal_chunks", embedder=embedder)

    hits = retriever.search(_request(), candidate_k=10)

    embedder.embed_query.assert_called_once_with("dat dai")
    kwargs = client.search.call_args.kwargs
    assert kwargs["index"] == "vietlegal_chunks"
    assert kwargs["size"] == 10
    assert kwargs["source_excludes"] == ["vector"]
    knn = kwargs["knn"]
    assert knn["field"] == "vector"
    assert knn["query_vector"] == [0.1, 0.2]
    assert knn["k"] == 10
    assert knn["num_candidates"] == 100  # max(10*4, 100)
    assert "filter" not in knn
    assert len(hits) == 1
    assert hits[0].scores == {"dense": 1.5}


def test_dense_retriever_shares_filter_clauses() -> None:
    client = Mock()
    client.search.return_value = _es_response()
    embedder = Mock()
    embedder.embed_query.return_value = [0.1]
    retriever = ElasticsearchDenseRetriever(client, index="idx", embedder=embedder)

    retriever.search(
        _request(filters={"legal_type": "Luat", "doc_id": ["doc-1"]}),
        candidate_k=50,
    )

    knn = client.search.call_args.kwargs["knn"]
    assert {"term": {"legal_type": "Luat"}} in knn["filter"]
    assert {"terms": {"doc_id": ["doc-1"]}} in knn["filter"]
    assert knn["num_candidates"] == 200  # 50*4 > floor


def test_dense_retriever_returns_empty_on_embed_failure() -> None:
    client = Mock()
    embedder = Mock()
    embedder.embed_query.side_effect = RuntimeError("provider down")
    retriever = ElasticsearchDenseRetriever(client, index="idx", embedder=embedder)

    assert retriever.search(_request(), candidate_k=10) == []
    client.search.assert_not_called()


def test_dense_retriever_returns_empty_on_search_failure() -> None:
    client = Mock()
    client.search.side_effect = ConnectionError("es down")
    embedder = Mock()
    embedder.embed_query.return_value = [0.1]
    retriever = ElasticsearchDenseRetriever(client, index="idx", embedder=embedder)

    assert retriever.search(_request(), candidate_k=10) == []


def test_dense_and_sparse_hit_shapes_match() -> None:
    client = Mock()
    client.search.return_value = _es_response("chunk:1")
    embedder = Mock()
    embedder.embed_query.return_value = [0.1]
    dense = ElasticsearchDenseRetriever(client, index="idx", embedder=embedder)
    sparse = ElasticsearchTextRetriever(client, index="idx")

    [dense_hit] = dense.search(_request(), candidate_k=5)
    [sparse_hit] = sparse.search(_request(), candidate_k=5)

    assert dense_hit.chunk_id == sparse_hit.chunk_id
    assert dense_hit.citation == sparse_hit.citation
    assert dense_hit.scores == {"dense": 1.5}
    assert sparse_hit.scores == {"bm25": 1.5}


def test_graph_chunk_fetcher_returns_graph_answer_contexts() -> None:
    client = Mock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "chunk-related",
                    "_score": 7.0,
                    "_source": {
                        "chunk_id": "chunk-related",
                        "doc_id": "doc-related",
                        "title": "Related Law",
                        "document_number": "99/2026/QH",
                        "chunk_text": "related legal text",
                        "section_path": ["Dieu 9"],
                    },
                }
            ]
        }
    }
    fetcher = ElasticsearchGraphChunkFetcher(client, index="vietlegal_chunks")

    contexts = fetcher(
        "căn cứ của văn bản",
        [{"doc_id": "doc-related", "relation": "CITES", "raw_label": "Căn cứ"}],
    )

    assert len(contexts) == 1
    assert contexts[0].source == "graph"
    assert contexts[0].chunk_id == "chunk-related"
    assert contexts[0].doc_id == "doc-related"
    assert contexts[0].relation == "CITES"
    assert contexts[0].raw_label == "Căn cứ"

    kwargs = client.search.call_args.kwargs
    assert kwargs["index"] == "vietlegal_chunks"
    assert kwargs["size"] == 1
    assert kwargs["source_excludes"] == ["vector"]
    assert {"term": {"doc_id": "doc-related"}} in kwargs["query"]["bool"]["filter"]


# --- B4: RetrievalService wiring ---


def test_hybrid_runs_one_bm25_and_one_knn_when_dense_configured() -> None:
    dense = Mock()
    dense.search.return_value = [_hit("chunk:1", "dense")]
    sparse = Mock()
    sparse.search.return_value = [_hit("chunk:2", "bm25")]
    service = RetrievalService(dense_retriever=dense, sparse_retriever=sparse)

    hits = service.search(_request(retrieval_mode="hybrid"))

    assert dense.search.call_count == 1
    assert sparse.search.call_count == 1
    assert {hit.chunk_id for hit in hits} == {"chunk:1", "chunk:2"}
    assert all("rrf" in hit.scores for hit in hits)


def test_hybrid_runs_single_bm25_pass_when_dense_absent() -> None:
    sparse = Mock()
    sparse.search.return_value = [_hit("chunk:2")]
    service = RetrievalService(dense_retriever=None, sparse_retriever=sparse)

    hits = service.search(_request(retrieval_mode="hybrid"))

    assert sparse.search.call_count == 1
    assert [hit.chunk_id for hit in hits] == ["chunk:2"]
    assert not service.dense_enabled


def test_identical_dense_and_sparse_retriever_collapses_to_single_pass() -> None:
    retriever = Mock()
    retriever.search.return_value = [_hit("chunk:3")]
    service = RetrievalService(dense_retriever=retriever, sparse_retriever=retriever)

    service.search(_request(retrieval_mode="hybrid"))

    assert retriever.search.call_count == 1
    assert not service.dense_enabled


def test_dense_mode_falls_back_to_sparse_when_dense_absent() -> None:
    sparse = Mock()
    sparse.search.return_value = [_hit("chunk:4")]
    service = RetrievalService(dense_retriever=None, sparse_retriever=sparse)

    hits = service.search(_request(retrieval_mode="dense"))

    assert sparse.search.call_count == 1
    assert [hit.chunk_id for hit in hits] == ["chunk:4"]


def test_dense_mode_uses_dense_retriever_when_configured() -> None:
    dense = Mock()
    dense.search.return_value = [_hit("chunk:5", "dense")]
    sparse = Mock()
    service = RetrievalService(dense_retriever=dense, sparse_retriever=sparse)

    hits = service.search(_request(retrieval_mode="dense"))

    assert dense.search.call_count == 1
    sparse.search.assert_not_called()
    assert [hit.chunk_id for hit in hits] == ["chunk:5"]
