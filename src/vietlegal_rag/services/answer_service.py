from typing import Any, Protocol, Generator

from contracts import AnswerContext
from think_tags import CLOSER, has_unclosed_think

SYSTEM_PROMPT = (
    "Bạn là trợ lý pháp lý AI chuyên nghiệp của Việt Nam. Nhiệm vụ của bạn là giải thích luật pháp và phân tích tình huống pháp lý một cách chính xác, khách quan.\n\n"
    "QUY TẮC PHÁP LÝ BẮT BUỘC:\n"
    "1. Chỉ trả lời dựa trên ngữ cảnh pháp lý (các đoạn văn bản luật) được cung cấp. Tuyệt đối không được tự bịa ra căn cứ pháp lý, điều luật, hay số hiệu văn bản.\n"
    "2. Luôn kiểm tra và cảnh báo rõ ràng về hiệu lực của văn bản. Nếu tài liệu đi kèm ghi nhận trạng thái [TRẠNG THÁI: HẾT HIỆU LỰC] hoặc [TRẠNG THÁI: PHIÊN BẢN CŨ], bạn PHẢI chủ động ghi thêm cảnh báo bằng biểu tượng ⚠️ ở phần trả lời tương ứng để người dùng biết.\n"
    "3. Nếu có văn bản mới hơn/thay thế đi kèm trong ngữ cảnh, hãy ưu tiên áp dụng quy định mới để trả lời, đồng thời giải thích ngắn gọn điểm chuyển tiếp pháp lý từ luật cũ sang luật mới.\n"
    "4. Trình bày câu trả lời rõ ràng, có cấu trúc, sử dụng các gạch đầu dòng hợp lý để người dùng dễ theo dõi."
)


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
                "text": context.text,
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
    def __init__(self, client: object, model: str, max_tokens: int = 2048) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

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
                    "content": SYSTEM_PROMPT,
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
            max_tokens=self.max_tokens,
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
                    "text": context.text,
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
                    "content": SYSTEM_PROMPT,
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
            max_tokens=self.max_tokens,
        )
        
        in_thinking = False
        # Models that inline <think> in content never set reasoning_content, so
        # `in_thinking` stays False for them; track the raw text to catch a block
        # the model opened but never closed (e.g. cut off by max_tokens).
        streamed_content = ""
        for chunk in response:
            if not getattr(chunk, "choices", None):
                continue
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
                    yield CLOSER
                    in_thinking = False

                # Yield standard text content
                if delta.content:
                    streamed_content += delta.content
                    yield delta.content

        if in_thinking or has_unclosed_think(streamed_content):
            yield CLOSER



