from typing import Any, Protocol, Generator

from contracts import AnswerContext
from think_tags import CLOSER, has_unclosed_think

SYSTEM_PROMPT = (
    "Bạn là trợ lý pháp lý AI chuyên nghiệp cho pháp luật Việt Nam. Nhiệm vụ của bạn là tra cứu, giải thích văn bản pháp luật và phân tích tình huống pháp lý một cách chính xác, khách quan dựa trên ngữ cảnh được cung cấp.\n\n"
    "QUY TẮC PHÁP LÝ BẮT BUỘC:\n"
    "1. Chỉ trả lời dựa trên ngữ cảnh pháp lý được cung cấp. Tuyệt đối không tự bịa căn cứ pháp lý, điều luật, số hiệu văn bản, mức phạt, thời hạn, thủ tục hoặc URL.\n"
    "2. Mỗi nhận định pháp lý quan trọng phải có citation inline dạng [1], [2] khớp với số thứ tự đoạn ngữ cảnh. Đặt citation ngay sau câu hoặc mệnh đề được hỗ trợ bởi nguồn đó.\n"
    "3. Không tự tạo mục 'Căn cứ pháp lý', 'Nguồn', danh sách tài liệu hoặc URL ở cuối câu trả lời. Open WebUI sẽ hiển thị chi tiết căn cứ trong Sources và citation modal.\n"
    "4. Cảnh báo hiệu lực CHỈ áp dụng cho văn bản bạn thực sự dùng làm căn cứ trong câu trả lời. Nếu một đoạn ngữ cảnh có trạng thái [TRẠNG THÁI: HẾT HIỆU LỰC] hoặc [TRẠNG THÁI: PHIÊN BẢN CŨ] VÀ bạn dựa vào nó để trả lời, ghi cảnh báo ⚠️ ngay tại nhận định đó. TUYỆT ĐỐI không cảnh báo về văn bản hết hiệu lực mà bạn không dùng đến hoặc không liên quan tới câu hỏi.\n"
    "5. Nếu ngữ cảnh có văn bản mới hơn hoặc văn bản thay thế cho một văn bản cũ, ưu tiên áp dụng quy định mới và giải thích ngắn gọn điểm chuyển tiếp pháp lý từ văn bản cũ sang văn bản mới.\n"
    "6. Bỏ qua các đoạn ngữ cảnh không liên quan đến câu hỏi; không gượng ép đưa chúng vào câu trả lời. Nếu một phần câu hỏi không có căn cứ trong ngữ cảnh, nói rõ phần đó chưa đủ căn cứ trong tài liệu được cung cấp; khi đó bạn có thể đưa hướng dẫn thực tế an toàn chung (ví dụ: trình báo cơ quan công an, giữ chứng cứ) nhưng KHÔNG được bịa điều luật, số hiệu, mức phạt hay thủ tục cụ thể. Không thay thế tư vấn pháp lý của luật sư trong vụ việc cụ thể.\n"
    "7. Trình bày bằng tiếng Việt rõ ràng, có cấu trúc. Ưu tiên trả lời trực tiếp trước rồi mới giải thích; câu hỏi nhiều vấn đề thì tách thành từng phần. Ngắn gọn, súc tích, độ dài co giãn theo câu hỏi; không lặp lại hoặc nhồi citation thừa."
)


class AnswerService(Protocol):
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        ...

    def stream_answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        ...



DEGRADED_NOTICE = (
    "⚠️ **Không tạo được câu trả lời từ mô hình ngôn ngữ.** "
    "Dưới đây là nguyên văn các đoạn luật liên quan nhất, chưa qua tổng hợp — "
    "vui lòng tự đối chiếu."
)


class ExtractiveAnswerService:
    def __init__(self, degraded: bool = False) -> None:
        # True when standing in for a failed LLM rather than serving as the
        # configured provider: the caller gets raw chunks either way, but only the
        # failure case is a degradation worth announcing.
        self.degraded = degraded

    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not contexts:
            return {
                "answer": "Không tìm thấy đủ ngữ cảnh để trả lời.",
                "citations": [],
            }

        # For extractive service, we can prefix the answer text with any document resolution warnings.
        warnings_text = []
        if self.degraded:
            warnings_text.append(DEGRADED_NOTICE)
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
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
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
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
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
            model=model or self.model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": self._system_prompt(system_prompt),
                },
                {
                    "role": "user",
                    "content": (
                        f"Câu hỏi: {query}\n\n"
                        f"Ngữ cảnh:\n{context_text}\n\n"
                        "Hãy trả lời bằng tiếng Việt. Dùng citation inline dạng [1], [2] theo số thứ tự trong ngữ cảnh; không tạo mục căn cứ hoặc nguồn riêng ở cuối câu trả lời."
                    ),
                },
            ],
            max_tokens=max_tokens or self.max_tokens,
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
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
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
            model=model or self.model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": self._system_prompt(system_prompt),
                },
                {
                    "role": "user",
                    "content": (
                        f"Câu hỏi: {query}\n\n"
                        f"Ngữ cảnh:\n{context_text}\n\n"
                        "Hãy trả lời bằng tiếng Việt. Dùng citation inline dạng [1], [2] theo số thứ tự trong ngữ cảnh; không tạo mục căn cứ hoặc nguồn riêng ở cuối câu trả lời."
                    ),
                },
            ],
            stream=True,
            max_tokens=max_tokens or self.max_tokens,
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

    @staticmethod
    def _system_prompt(system_prompt: str | None = None) -> str:
        return (system_prompt or "").strip() or SYSTEM_PROMPT
