from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"


def test_pipeline_uses_numbered_local_execution_stages() -> None:
    expected_dirs = [
        "01_eda/download",
        "01_eda/eda",
        "02_preprocessing/clean",
        "02_preprocessing/merge",
        "02_preprocessing/chunk",
        "03_embeddings/dense",
        "03_embeddings/sparse",
        "04_graph",
        "05_evaluation",
    ]

    for relative in expected_dirs:
        assert (PIPELINE / relative).is_dir(), relative


def test_pipeline_python_files_do_not_import_global_pipeline_package() -> None:
    offenders: list[str] = []
    for path in PIPELINE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from pipeline." in text or "import pipeline." in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_pipeline_branch_keeps_only_pipeline_tests() -> None:
    removed_backend_tests = [
        "test_answer_service.py",
        "test_api_contract.py",
        "test_context_assembly.py",
        "test_graph_retriever.py",
        "test_lightrag_service.py",
        "test_retrieval_modes.py",
        "test_retrieval_service.py",
        "test_service_contracts.py",
    ]

    for filename in removed_backend_tests:
        assert not (ROOT / "tests" / filename).exists(), filename
