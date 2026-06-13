import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "pipeline" / "07_evaluation"
sys.path.insert(0, str(EVALUATION_DIR))

from ftfy import fix_text

from evaluate_llm import GroqKeyPool, build_context, parse_response, summarize  # noqa: E402


class LlmEvaluationTests(unittest.TestCase):
    def test_parse_response_accepts_json_and_fallback_letter(self):
        self.assertEqual(
            parse_response('{"answer":"B","cited_chunk_ids":["c1"]}'),
            ("B", ["c1"], True),
        )
        self.assertEqual(parse_response("Đáp án: C"), ("C", [], False))

    def test_build_context_preserves_all_ranked_ids_with_balanced_truncation(self):
        chunks = {
            "c1": {"chunk_text": "first", "title": "One"},
            "c2": {"chunk_text": "second" * 20, "title": "Two"},
        }
        text, included, truncated = build_context(
            ["c1", "c2"],
            chunks,
            max_chars=1000,
        )
        self.assertIn("first", text)
        self.assertEqual(included, ["c1", "c2"])
        self.assertFalse(truncated)

        text, included, truncated = build_context(
            ["c1", "c2"],
            chunks,
            max_chars=100,
        )
        self.assertEqual(included, ["c1", "c2"])
        self.assertLessEqual(len(text), 100)
        self.assertTrue(truncated)

    def test_build_context_keeps_tail_of_long_legal_chunk(self):
        chunks = {"c1": {"chunk_text": "START" + ("x" * 2000) + "LEGAL_END"}}
        text, _, truncated = build_context(["c1"], chunks, max_chars=1000)
        self.assertIn("START", text)
        self.assertIn("LEGAL_END", text)
        self.assertTrue(truncated)

    def test_ftfy_repairs_elasticsearch_mojibake(self):
        self.assertEqual(fix_text("Hoáº¡t Ä‘á»™ng khoÃ¡ng sáº£n"), "Hoạt động khoáng sản")

    def test_key_pool_deduplicates_and_refreshes_new_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(
                "GROQ_API_KEY=test-key-first\n"
                "GROQ_API_KEY2=test-key-second\n"
                "GROQ_API_KEY3=test-key-second\n",
                encoding="utf-8",
            )
            pool = GroqKeyPool(env, offset=1)
            self.assertEqual([name for name, _ in pool.keys], ["GROQ_API_KEY", "GROQ_API_KEY2"])
            self.assertEqual(pool.active_name, "GROQ_API_KEY2")
            env.write_text(
                env.read_text(encoding="utf-8") + "GROQ_API_KEY4=test-key-fourth\n",
                encoding="utf-8",
            )
            pool.refresh()
            self.assertEqual(len(pool.keys), 3)

    def test_summary_reports_accuracy_and_paired_outcomes(self):
        rows = [
            {
                "status": "ok",
                "model": "m",
                "setup": "no_rag",
                "question_id": "q1",
                "question_type": "factual",
                "correct": False,
                "valid_json": True,
                "latency_seconds": 1.0,
            },
            {
                "status": "ok",
                "model": "m",
                "setup": "hybrid_rerank",
                "question_id": "q1",
                "question_type": "factual",
                "correct": True,
                "valid_json": True,
                "latency_seconds": 2.0,
                "retrieval_hit": True,
                "citation_valid": True,
                "cites_gold": True,
            },
        ]
        result = summarize(rows)
        self.assertEqual(result["results"]["m"]["no_rag"]["accuracy"], 0.0)
        self.assertEqual(result["results"]["m"]["hybrid_rerank"]["accuracy"], 1.0)
        self.assertEqual(result["paired_outcomes"]["rag_only"], 1)


if __name__ == "__main__":
    unittest.main()
