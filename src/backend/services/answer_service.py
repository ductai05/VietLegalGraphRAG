from __future__ import annotations

from typing import Any, Protocol

from contracts import AnswerContext


class AnswerService(Protocol):
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        ...


class ExtractiveAnswerService:
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        if not contexts:
            return {
                "answer": "Không tìm thấy đủ ngữ cảnh để trả lời.",
                "citations": [],
            }
        answer_text = "\n\n".join(context.text for context in contexts[:3] if context.text)
        citations = [
            {
                "chunk_id": context.chunk_id,
                "doc_id": context.doc_id,
                "title": context.title,
                "citation": context.citation,
            }
            for context in contexts
        ]
        return {"answer": answer_text, "citations": citations}
