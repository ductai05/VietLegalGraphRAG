from typing import Any, Protocol, Generator

from contracts import AnswerContext


class AnswerService(Protocol):
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        ...

    def stream_answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> Generator[str, None, None]:
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

        # For extractive service, we can prefix the answer text with any document resolution warnings.
        warnings_text = []
        for ctx in contexts[:3]:
            if ctx.resolution:
                action = ctx.resolution.get("action")
                reason = ctx.resolution.get("reason")
                if action in ("replaced", "expired_warning", "superseded"):
                    warnings_text.append(f"[CẢNH BÁO PHÁP LÝ] {ctx.citation}: {reason}")

        prefix = "\n".join(warnings_text) + "\n\n" if warnings_text else ""
        answer_text = prefix + "\n\n".join(context.text for context in contexts[:3] if context.text)
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

    def stream_answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> Generator[str, None, None]:
        res = self.answer(query, contexts, temperature)
        yield res.get("answer", "")



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

        formatted_contexts = []
        for index, context in enumerate(contexts, start=1):
            if not context.text:
                continue
            header = f"[{index}] {context.citation}"
            if context.resolution:
                action = context.resolution.get("action")
                replacement_id = context.resolution.get("replacement_doc_id")
                if action == "replaced":
                    header += f" [TRẠNG THÁI: HẾT HIỆU LỰC - Thay thế bởi {replacement_id}]"
                elif action == "expired_warning":
                    header += " [TRẠNG THÁI: HẾT HIỆU LỰC - Không tìm thấy tài liệu thay thế]"
                elif action == "superseded":
                    header += f" [TRẠNG THÁI: PHIÊN BẢN CŨ - Đã có phiên bản mới hơn {replacement_id}]"
            formatted_contexts.append(f"{header}\n{context.text}")

        context_text = "\n\n".join(formatted_contexts)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý pháp lý Việt Nam. Trả lời ngắn gọn, "
                        "dựa trên ngữ cảnh được cung cấp và không tạo căn cứ "
                        "pháp lý nếu ngữ cảnh không hỗ trợ.\n\n"
                        "LƯU Ý QUAN TRỌNG VỀ HIỆU LỰC PHÁP LÝ:\n"
                        "- Khi gặp tài liệu được đánh dấu là [TRẠNG THÁI: HẾT HIỆU LỰC] hoặc [TRẠNG THÁI: PHIÊN BẢN CŨ], bạn PHẢI chủ động cảnh báo rõ cho người dùng biết văn bản đó đã hết hiệu lực hoặc đã cũ.\n"
                        "- Nếu ngữ cảnh đi kèm tài liệu thay thế/mới hơn, bạn phải trình bày câu trả lời dựa trên quy định của tài liệu mới (đang còn hiệu lực), đồng thời nêu rõ sự thay đổi so với luật cũ (hết hiệu lực) để người dùng dễ dàng nhận biết sự chuyển tiếp pháp lý."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Câu hỏi: {query}\n\n"
                        f"Ngữ cảnh:\n{context_text}\n\n"
                        "Hãy trả lời bằng tiếng Việt, nêu rõ căn cứ liên quan và cảnh báo hiệu lực văn bản nếu có."
                    ),
                },
            ],
            max_tokens=4096,
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
 
    def stream_answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> Generator[str, None, None]:
        if not contexts:
            for chunk in ExtractiveAnswerService().stream_answer(query, contexts, temperature):
                yield chunk
            return
 
        formatted_contexts = []
        for index, context in enumerate(contexts, start=1):
            if not context.text:
                continue
            header = f"[{index}] {context.citation}"
            if context.resolution:
                action = context.resolution.get("action")
                replacement_id = context.resolution.get("replacement_doc_id")
                if action == "replaced":
                    header += f" [TRẠNG THÁI: HẾT HIỆU LỰC - Thay thế bởi {replacement_id}]"
                elif action == "expired_warning":
                    header += " [TRẠNG THÁI: HẾT HIỆU LỰC - Không tìm thấy tài liệu thay thế]"
                elif action == "superseded":
                    header += f" [TRẠNG THÁI: PHIÊN BẢN CŨ - Đã có phiên bản mới hơn {replacement_id}]"
            formatted_contexts.append(f"{header}\n{context.text}")
 
        context_text = "\n\n".join(formatted_contexts)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý pháp lý Việt Nam. Trả lời ngắn gọn, "
                        "dựa trên ngữ cảnh được cung cấp và không tạo căn cứ "
                        "pháp lý nếu ngữ cảnh không hỗ trợ.\n\n"
                        "LƯU Ý QUAN TRỌNG VỀ HIỆU LỰC PHÁP LÝ:\n"
                        "- Khi gặp tài liệu được đánh dấu là [TRẠNG THÁI: HẾT HIỆU LỰC] hoặc [TRẠNG THÁI: PHIÊN BẢN CŨ], bạn PHẢI chủ động cảnh báo rõ cho người dùng biết văn bản đó đã hết hiệu lực hoặc đã cũ.\n"
                        "- Nếu ngữ cảnh đi kèm tài liệu thay thế/mới hơn, bạn phải trình bày câu trả lời dựa trên quy định của tài liệu mới (đang còn hiệu lực), đồng thời nêu rõ sự thay đổi so với luật cũ (hết hiệu lực) để người dùng dễ dàng nhận biết sự chuyển tiếp pháp lý."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Câu hỏi: {query}\n\n"
                        f"Ngữ cảnh:\n{context_text}\n\n"
                        "Hãy trả lời bằng tiếng Việt, nêu rõ căn cứ liên quan và cảnh báo hiệu lực văn bản nếu có."
                    ),
                },
            ],
            stream=True,
            max_tokens=4096,
        )
        
        in_thinking = False
        for chunk in response:
            delta = chunk.choices[0].delta
            
            # Check for reasoning_content (e.g. from DeepSeek R1 or Qwen reasoning endpoints)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not in_thinking:
                    yield "<think>\n"
                    in_thinking = True
                yield reasoning
            else:
                if in_thinking:
                    yield "\n</think>\n\n"
                    in_thinking = False
                
                # Yield standard text content
                if delta.content:
                    yield delta.content
                    
        if in_thinking:
            yield "\n</think>\n\n"



