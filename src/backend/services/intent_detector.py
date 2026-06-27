from __future__ import annotations

import re


class IntentDetector:
    DOCUMENT_NUMBER_PATTERN = re.compile(r"\b\d{1,4}/\d{4}/[A-Z0-9-]+\b", re.IGNORECASE)

    def detect(self, query: str) -> dict[str, str | None]:
        normalized = query.lower()
        document_match = self.DOCUMENT_NUMBER_PATTERN.search(query)
        intent = "general"
        if any(term in normalized for term in ("sua doi", "bo sung", "sửa đổi", "bổ sung")):
            intent = "amendment"
        elif any(term in normalized for term in ("bai bo", "het hieu luc", "bãi bỏ", "hết hiệu lực")):
            intent = "repeal"
        elif any(term in normalized for term in ("dan chieu", "can cu", "dẫn chiếu", "căn cứ")):
            intent = "citation"
        elif any(term in normalized for term in ("huong dan", "quy dinh chi tiet", "hướng dẫn", "quy định chi tiết")):
            intent = "guideline"

        return {
            "intent": intent,
            "document_number": document_match.group(0) if document_match else None,
        }
