import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from evaluate_dense import main



class ElasticsearchEvaluationTests(unittest.TestCase):
    def test_main_forwards_elasticsearch_target_options(self):
        retriever = Mock()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            gold_path = tmp_path / "gold.jsonl"
            output_path = tmp_path / "report.json"
            gold_path.write_text("", encoding="utf-8")
            argv = [
                "evaluate_dense.py",
                "--gold",
                str(gold_path),
                "--elastic-cloud-id",
                "cloud-id",
                "--elastic-api-key",
                "api-key",
                "--elastic-index",
                "legal",
                "--elastic-num-candidates",
                "300",
                "--output",
                str(output_path),
            ]
            with (
                patch("evaluate_dense.DenseRetriever", return_value=retriever) as factory,
                patch("evaluate_dense.setup_logging"),
                patch("builtins.print"),
                patch.object(sys, "argv", argv),
            ):
                main()

        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["elastic_cloud_id"], "cloud-id")
        self.assertEqual(kwargs["elastic_api_key"], "api-key")
        self.assertEqual(kwargs["elastic_index"], "legal")
        self.assertEqual(kwargs["elastic_num_candidates"], 300)
        retriever.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
