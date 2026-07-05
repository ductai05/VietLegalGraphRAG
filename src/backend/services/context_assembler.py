from __future__ import annotations

from contracts import AnswerContext, GraphContext, RetrievalHit


class ContextAssembler:
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

        if graph_context is None:
            return contexts

        for item in graph_context.related_chunks:
            if item.chunk_id and item.chunk_id in seen_chunk_ids:
                continue
            if item.chunk_id:
                seen_chunk_ids.add(item.chunk_id)
            contexts.append(item)

        return contexts
