from __future__ import annotations

from typing import TYPE_CHECKING

from contracts import AnswerContext, GraphContext, RetrievalHit

if TYPE_CHECKING:
    from document_resolver import DocumentResolver, ResolvedResult


class ContextAssembler:
    def __init__(
        self,
        document_resolver: DocumentResolver | None = None,
    ) -> None:
        self.document_resolver = document_resolver

    def merge(
        self,
        retrieval_hits: list[RetrievalHit],
        graph_context: GraphContext | None,
    ) -> list[AnswerContext]:
        contexts: list[AnswerContext] = []
        seen_chunk_ids: set[str] = set()

        for hit in retrieval_hits:
            context = hit.to_answer_context()
            if context.chunk_id:
                seen_chunk_ids.add(context.chunk_id)
            contexts.append(context)

        if graph_context is not None:
            for item in graph_context.related_chunks:
                if item.chunk_id and item.chunk_id in seen_chunk_ids:
                    continue
                if item.chunk_id:
                    seen_chunk_ids.add(item.chunk_id)
                contexts.append(item)

        # Run document resolution if resolver is available.
        if self.document_resolver is not None:
            resolved = self.document_resolver.resolve(contexts, graph_context)
            self._last_resolved = resolved
            return resolved.contexts

        self._last_resolved = None
        return contexts

    @property
    def last_resolved(self) -> ResolvedResult | None:
        """Access the most recent resolution result (for trace reporting)."""
        return getattr(self, "_last_resolved", None)

