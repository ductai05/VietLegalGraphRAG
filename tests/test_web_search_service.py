"""Hermetic tests for the web search providers. No live Exa calls."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICES = ROOT / "src" / "vietlegal_rag" / "services"
if str(RAG_SERVICES) not in sys.path:
    sys.path.insert(0, str(RAG_SERVICES))


class _StubProvider:
    def __init__(self, results: list[dict[str, str]] | None = None, error: Exception | None = None):
        self.results = results or []
        self.error = error
        self.calls: list[str] = []

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return self.results


def _result(url: str = "https://thuvienphapluat.vn/nd15") -> dict[str, str]:
    return {"title": "Nghị định 15/2020/NĐ-CP", "url": url, "snippet": "...", "provider": "exa"}


# ----------------------------------------------------------------------
# NoopWebSearch
# ----------------------------------------------------------------------


def test_noop_web_search_returns_empty() -> None:
    from web_search_service import NoopWebSearch

    assert NoopWebSearch().search("bất kỳ") == []


# ----------------------------------------------------------------------
# FallbackWebSearch
# ----------------------------------------------------------------------


def test_fallback_uses_primary_when_it_returns_results() -> None:
    from web_search_service import FallbackWebSearch

    primary = _StubProvider(results=[_result()])
    secondary = _StubProvider(results=[_result("https://vbpl.vn/other")])

    results = FallbackWebSearch(primary, secondary).search("Nghị định 15/2020/NĐ-CP")

    assert results == [_result()]
    assert secondary.calls == []


def test_fallback_uses_secondary_when_primary_raises() -> None:
    from web_search_service import FallbackWebSearch

    primary = _StubProvider(error=RuntimeError("exa down"))
    secondary = _StubProvider(results=[_result()])

    results = FallbackWebSearch(primary, secondary).search("Nghị định 15/2020/NĐ-CP")

    assert results == [_result()]
    assert len(secondary.calls) == 1


def test_fallback_uses_secondary_when_primary_returns_empty() -> None:
    from web_search_service import FallbackWebSearch

    primary = _StubProvider(results=[])
    secondary = _StubProvider(results=[_result()])

    results = FallbackWebSearch(primary, secondary).search("Nghị định 15/2020/NĐ-CP")

    assert results == [_result()]
    assert len(secondary.calls) == 1


def test_fallback_returns_empty_when_both_fail() -> None:
    from web_search_service import FallbackWebSearch

    primary = _StubProvider(error=RuntimeError("exa down"))
    secondary = _StubProvider(error=RuntimeError("secondary down"))

    assert FallbackWebSearch(primary, secondary).search("truy vấn") == []


# ----------------------------------------------------------------------
# ExaWebSearch
# ----------------------------------------------------------------------


class _FakeExaResult:
    def __init__(self, url: str, title: str = "", text: str = "") -> None:
        self.url = url
        self.title = title
        self.text = text


class _FakeExaResponse:
    def __init__(self, results: list[_FakeExaResult]) -> None:
        self.results = results


class _FakeExaClient:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def search_and_contents(self, query: str, **kwargs: Any) -> Any:
        self.kwargs = {"query": query, **kwargs}
        return self.response


def test_exa_search_maps_results_and_restricts_domains() -> None:
    from web_search_service import DEFAULT_LEGAL_DOMAINS, ExaWebSearch

    client = _FakeExaClient(
        _FakeExaResponse([_FakeExaResult("https://thuvienphapluat.vn/nd15", "ND 15", "nội dung")])
    )

    results = ExaWebSearch(client).search("Nghị định 15/2020/NĐ-CP toàn văn")

    assert results == [
        {
            "title": "ND 15",
            "url": "https://thuvienphapluat.vn/nd15",
            "snippet": "nội dung",
            "provider": "exa",
        }
    ]
    assert client.kwargs["include_domains"] == list(DEFAULT_LEGAL_DOMAINS)
    assert client.kwargs["type"] == "auto"


def test_exa_search_skips_results_without_url() -> None:
    from web_search_service import ExaWebSearch

    client = _FakeExaClient(_FakeExaResponse([_FakeExaResult("", "no url")]))

    assert ExaWebSearch(client).search("truy vấn") == []


def test_exa_search_failure_is_absorbed_by_fallback() -> None:
    from web_search_service import ExaWebSearch, FallbackWebSearch, NoopWebSearch

    class _BrokenClient:
        def search_and_contents(self, query: str, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    search = FallbackWebSearch(ExaWebSearch(_BrokenClient()), NoopWebSearch())

    assert search.search("truy vấn") == []
