import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "pipeline" / "07_evaluation"
sys.path.insert(0, str(EVALUATION_DIR))


def test_resolves_all_retrieval_execution_modes():
    from retrieval_modes import resolve_execution_mode

    assert resolve_execution_mode("dense", False) == "dense"
    assert resolve_execution_mode("dense", True) == "dense_rerank"
    assert resolve_execution_mode("sparse", False) == "sparse"
    assert resolve_execution_mode("sparse", True) == "sparse_rerank"
    assert resolve_execution_mode("hybrid", False) == "hybrid"
    assert resolve_execution_mode("hybrid", True) == "hybrid_rerank"


def test_retrieval_request_defaults_are_mvp_safe():
    from retrieval_modes import RetrievalRequest

    request = RetrievalRequest(query="Dieu kien cap giay phep xay dung la gi?")

    assert request.retrieval_mode == "hybrid"
    assert request.rerank.enabled is True
    assert request.rerank.candidate_k == 50
    assert request.top_k == 5
    assert request.llm.temperature == 0.2
    assert request.execution_mode == "hybrid_rerank"


def test_retrieval_request_validates_mode_and_temperature():
    from retrieval_modes import RetrievalRequest

    try:
        RetrievalRequest(query="q", retrieval_mode="graph")
    except ValueError as exc:
        assert "retrieval_mode" in str(exc)
    else:
        raise AssertionError("invalid retrieval mode was accepted")

    try:
        RetrievalRequest(query="q", llm={"temperature": 1.5})
    except ValueError as exc:
        assert "temperature" in str(exc)
    else:
        raise AssertionError("invalid temperature was accepted")
