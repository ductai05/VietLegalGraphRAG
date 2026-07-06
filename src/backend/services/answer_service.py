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


class OpenAICompatibleAnswerService:
    def __init__(self, client: object, model: str) -> None:
        self.client = client
        self.model = model

    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        if not contexts:
            return ExtractiveAnswerService().answer(query, contexts, temperature)

        context_text = "\n\n".join(
            f"[{index}] {context.citation}\n{context.text}"
            for index, context in enumerate(contexts, start=1)
            if context.text
        )
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý pháp lý Việt Nam. Trả lời ngắn gọn, "
                        "dựa trên ngữ cảnh được cung cấp và không tạo căn cứ "
                        "pháp lý nếu ngữ cảnh không hỗ trợ."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Câu hỏi: {query}\n\n"
                        f"Ngữ cảnh:\n{context_text}\n\n"
                        "Hãy trả lời bằng tiếng Việt và nêu rõ căn cứ liên quan."
                    ),
                },
            ],
        )
        answer = response.choices[0].message.content or ""
        return {
            "answer": answer.strip(),
            "citations": [
                {
                    "chunk_id": context.chunk_id,
                    "doc_id": context.doc_id,
                    "title": context.title,
                    "citation": context.citation,
                }
                for context in contexts
            ],
        }
