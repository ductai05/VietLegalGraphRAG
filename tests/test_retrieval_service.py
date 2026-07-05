from contracts import RetrievalHit
from retrieval_modes import RetrievalRequest
from retrieval_service import FusionRetriever, RetrievalService


class FakeRetriever:
    def __init__(self, name, hits):
        self.name = name
        self.hits = hits
        self.calls = []

    def search(self, request, candidate_k):
        self.calls.append((request, candidate_k))
        return self.hits


class FakeReranker:
    def rerank(self, query, hits, top_k):
        for index, hit in enumerate(reversed(hits), start=1):
            hit.rank = index
            hit.scores["rerank"] = float(100 - index)
        return list(reversed(hits))[:top_k]


def make_hit(rank, chunk_id, score_key, score):
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        doc_id=chunk_id.split(":")[1],
        title=f"Doc {chunk_id}",
        document_number="01/2026/QH",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text=f"Text {chunk_id}",
        scores={score_key: score},
        citation=f"Citation {chunk_id}",
    )


def test_fusion_retriever_merges_dense_sparse_by_rrf():
    dense = [make_hit(1, "chunk:1:000001", "dense", 0.9)]
    sparse = [make_hit(1, "chunk:2:000001", "sparse", 12.0)]
    fusion = FusionRetriever(k=60)

    merged = fusion.merge(dense, sparse, top_k=2)

    assert [hit.chunk_id for hit in merged] == ["chunk:1:000001", "chunk:2:000001"]
    assert all("rrf" in hit.scores for hit in merged)


def test_retrieval_service_resolves_hybrid_rerank():
    dense = FakeRetriever("dense", [make_hit(1, "chunk:1:000001", "dense", 0.9)])
    sparse = FakeRetriever("sparse", [make_hit(1, "chunk:2:000001", "sparse", 12.0)])
    service = RetrievalService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        fusion_retriever=FusionRetriever(),
        reranker=FakeReranker(),
    )

    hits = service.search(
        RetrievalRequest(
            query="q",
            retrieval_mode="hybrid",
            rerank={"enabled": True, "candidate_k": 20},
            top_k=1,
        )
    )

    assert len(hits) == 1
    assert hits[0].scores["rerank"] > 0
    assert dense.calls[0][1] == 20
    assert sparse.calls[0][1] == 20
