import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_DIR = ROOT / "pipeline" / "04_embedding"
EVALUATION_DIR = ROOT / "pipeline" / "07_evaluation"
sys.path.insert(0, str(EMBEDDING_DIR))
sys.path.insert(0, str(EVALUATION_DIR))

if "polars" not in sys.modules:
    sys.modules["polars"] = types.ModuleType("polars")

if "pyarrow" not in sys.modules:
    pyarrow_module = types.ModuleType("pyarrow")
    pyarrow_ipc_module = types.ModuleType("pyarrow.ipc")
    pyarrow_module.ipc = pyarrow_ipc_module
    sys.modules["pyarrow"] = pyarrow_module
    sys.modules["pyarrow.ipc"] = pyarrow_ipc_module

from evaluate_dense import main  # noqa: E402


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
