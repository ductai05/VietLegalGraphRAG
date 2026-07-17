"""Web search providers backing the agent's ``web_find_source_link`` tool.

Only Exa is implemented. TinyFish was left out deliberately — no SDK is pinned
and its API surface is unknown. ``FallbackWebSearch`` keeps the two-provider
seam so a second provider can be dropped in behind ``WebSearch`` later without
touching any caller.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("vietlegal_rag.services.web_search_service")

DEFAULT_LEGAL_DOMAINS = (
    "thuvienphapluat.vn",
    "vanban.chinhphu.vn",
    "vbpl.vn",
    "datafiles.chinhphu.vn",
)

_MAX_SNIPPET_CHARS = 300
_MAX_RESULTS_CEILING = 10


class WebSearch(Protocol):
    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Returns [{"title", "url", "snippet", "provider"}]; [] on failure."""
        ...


class NoopWebSearch:
    """Used when no provider is configured."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        return []


class ExaWebSearch:
    def __init__(
        self,
        client: Any,
        include_domains: tuple[str, ...] = DEFAULT_LEGAL_DOMAINS,
        num_results: int = 3,
    ) -> None:
        self.client = client
        self.include_domains = list(include_domains)
        self.num_results = num_results

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        count = max(1, min(max_results or self.num_results, _MAX_RESULTS_CEILING))
        response = self.client.search_and_contents(
            query,
            include_domains=self.include_domains,
            num_results=count,
            type="auto",
        )
        results: list[dict[str, str]] = []
        for item in getattr(response, "results", None) or []:
            url = getattr(item, "url", "") or ""
            if not url:
                continue
            snippet = getattr(item, "text", "") or getattr(item, "summary", "") or ""
            results.append(
                {
                    "title": getattr(item, "title", "") or "",
                    "url": url,
                    "snippet": snippet[:_MAX_SNIPPET_CHARS],
                    "provider": "exa",
                }
            )
        return results


class FallbackWebSearch:
    """Tries *primary*, then *secondary* when it raises or returns nothing."""

    def __init__(self, primary: Any, secondary: Any) -> None:
        self.primary = primary
        self.secondary = secondary

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        for provider in (self.primary, self.secondary):
            if provider is None:
                continue
            try:
                results = provider.search(query, max_results=max_results)
            except Exception:
                logger.warning(
                    "Web search provider %s failed", type(provider).__name__, exc_info=True
                )
                continue
            if results:
                return list(results)
        return []
