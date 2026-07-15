from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
# Add vietlegal_rag package directories to sys.path
VIETLEGAL_RAG_SRC = ROOT / "src" / "vietlegal_rag"
VIETLEGAL_RAG_SERVICES = ROOT / "src" / "vietlegal_rag" / "services"
for path in (VIETLEGAL_RAG_SERVICES, VIETLEGAL_RAG_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Clear cached backend services from sys.modules
for mod_name in ["lightrag_service", "answer_service"]:
    sys.modules.pop(mod_name, None)

from contracts import AnswerContext, GraphContext, RetrievalHit
from retrieval_modes import RetrievalRequest
from lightrag_service import LightRAGService
from answer_service import OpenAICompatibleAnswerService, ExtractiveAnswerService


class LlmFallbackTests(unittest.TestCase):
    def test_openai_compatible_answer_service_uses_configured_max_tokens(self) -> None:
        client = Mock()
        client.chat.completions.create.return_value = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Chunk 1"))])
        ]
        service = OpenAICompatibleAnswerService(client=client, model="test-model", max_tokens=1024)
        
        # Must pass non-empty context so it doesn't return early
        ctx = AnswerContext(
            source="retrieval",
            chunk_id="c1",
            doc_id="d1",
            title="Title 1",
            text="Some context text",
            citation="Cite 1"
        )
        
        # Consume generator to trigger create call
        list(service.stream_answer("query", [ctx], 0.2))
        
        create_args = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_args["max_tokens"], 1024)

    def test_safe_stream_wrapper_success(self) -> None:
        mock_retrieval_service = Mock()
        mock_retrieval_service.search.return_value = [
            RetrievalHit(
                rank=1,
                chunk_id="c1",
                doc_id="d1",
                title="Title 1",
                document_number="Doc-1",
                legal_type="Type",
                effect_status="status",
                section_path="path",
                text="Text 1",
                scores={"hybrid": 1.0},
                citation="Cite 1"
            )
        ]
        mock_graph_retriever = Mock()
        mock_graph_retriever.enabled = False

        # Standard successful LLM response chunks
        mock_chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Xin "))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="chào "))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="bạn."))]),
        ]
        
        mock_openai_client = Mock()
        mock_openai_client.chat.completions.create.return_value = mock_chunks
        
        mock_answer_service = OpenAICompatibleAnswerService(client=mock_openai_client, model="model-x")
        
        service = LightRAGService(
            retrieval_service=mock_retrieval_service,
            graph_retriever=mock_graph_retriever,
            answer_service=mock_answer_service
        )
        
        req = RetrievalRequest(query="Xin chào")
        result = service.stream_answer(req)
        
        tokens = list(result["answer_stream"])
        self.assertEqual("".join(tokens), "Xin chào bạn.")

    def test_safe_stream_wrapper_fallback_on_init(self) -> None:
        mock_retrieval_service = Mock()
        mock_retrieval_service.search.return_value = [
            RetrievalHit(
                rank=1,
                chunk_id="c1",
                doc_id="d1",
                title="Title 1",
                document_number="Doc-1",
                legal_type="Type",
                effect_status="status",
                section_path="path",
                text="Văn bản gốc pháp luật.",
                scores={"hybrid": 1.0},
                citation="Cite 1"
            )
        ]
        mock_graph_retriever = Mock()
        mock_graph_retriever.enabled = False

        # Simulate connection error / 413 error immediately when calling create()
        mock_answer_service = Mock()
        mock_answer_service.stream_answer.side_effect = Exception("413 API Error on Init")
        
        service = LightRAGService(
            retrieval_service=mock_retrieval_service,
            graph_retriever=mock_graph_retriever,
            answer_service=mock_answer_service
        )
        
        req = RetrievalRequest(query="Hỏi gì?")
        result = service.stream_answer(req)
        
        # Should fall back to ExtractiveAnswerService and stream search chunks
        tokens = list(result["answer_stream"])
        joined = "".join(tokens)
        self.assertIn("Văn bản gốc pháp luật.", joined)

    def test_safe_stream_wrapper_fallback_on_first_token(self) -> None:
        mock_retrieval_service = Mock()
        mock_retrieval_service.search.return_value = [
            RetrievalHit(
                rank=1,
                chunk_id="c1",
                doc_id="d1",
                title="Title 1",
                document_number="Doc-1",
                legal_type="Type",
                effect_status="status",
                section_path="path",
                text="Văn bản gốc pháp luật.",
                scores={"hybrid": 1.0},
                citation="Cite 1"
            )
        ]
        mock_graph_retriever = Mock()
        mock_graph_retriever.enabled = False

        # Simulate stream created but fails on fetching the first chunk (e.g. rate limit error raised on next())
        def failing_generator(*args, **kwargs):
            raise Exception("413 Payload Too Large on first next()")
            yield "Never yielded"

        mock_answer_service = Mock()
        mock_answer_service.stream_answer.return_value = failing_generator()
        
        service = LightRAGService(
            retrieval_service=mock_retrieval_service,
            graph_retriever=mock_graph_retriever,
            answer_service=mock_answer_service
        )
        
        req = RetrievalRequest(query="Hỏi gì?")
        result = service.stream_answer(req)
        
        # Should fall back to ExtractiveAnswerService
        tokens = list(result["answer_stream"])
        joined = "".join(tokens)
        self.assertIn("Văn bản gốc pháp luật.", joined)

    def test_safe_stream_wrapper_fails_mid_stream(self) -> None:
        mock_retrieval_service = Mock()
        mock_retrieval_service.search.return_value = [
            RetrievalHit(
                rank=1,
                chunk_id="c1",
                doc_id="d1",
                title="Title 1",
                document_number="Doc-1",
                legal_type="Type",
                effect_status="status",
                section_path="path",
                text="Text 1",
                scores={"hybrid": 1.0},
                citation="Cite 1"
            )
        ]
        mock_graph_retriever = Mock()
        mock_graph_retriever.enabled = False

        # Yields first token successfully, then fails
        def mid_fail_generator(*args, **kwargs):
            yield "Đầu "
            raise Exception("API connection lost mid stream")

        mock_answer_service = Mock()
        mock_answer_service.stream_answer.return_value = mid_fail_generator()
        
        service = LightRAGService(
            retrieval_service=mock_retrieval_service,
            graph_retriever=mock_graph_retriever,
            answer_service=mock_answer_service
        )
        
        req = RetrievalRequest(query="Hỏi gì?")
        result = service.stream_answer(req)
        
        tokens = list(result["answer_stream"])
        joined = "".join(tokens)
        self.assertTrue(joined.startswith("Đầu "))
        self.assertIn("⚠️ Đã xảy ra lỗi khi tạo câu trả lời từ mô hình ngôn ngữ.", joined)


if __name__ == "__main__":
    unittest.main()
