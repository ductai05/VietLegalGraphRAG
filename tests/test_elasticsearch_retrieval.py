import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from pipeline.embedding.dense_retrieval import DenseRetriever



class FakeElasticsearchClient:
    def __init__(self):
        self.search = Mock(
            return_value={
                "hits": {
                    "hits": [
                        {
                            "_score": 0.935,
                            "_source": {
                                "chunk_id": "c1",
                                "doc_id": "42",
                                "vector": [0.1],
                            },
                        }
                    ]
                }
            }
        )
        self.indices = Mock()
        self.indices.exists.return_value = True
        self.close = Mock()


class ElasticsearchRetrievalTests(unittest.TestCase):
    def test_cli_help_does_not_require_optional_storage_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "pipeline" / "embedding" / "dense_retrieval.py",
            root / "pipeline" / "evaluation" / "evaluate_dense.py",
        ]
        for script in scripts:
            with self.subTest(script=script.name):
                env = os.environ.copy()
                env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
                result = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--elastic-cloud-id", result.stdout)
                self.assertNotIn("--storage-dir", result.stdout)
                self.assertNotIn("--url", result.stdout)

    def test_search_builds_knn_prefilter_and_normalizes_cosine_score(self):
        client = FakeElasticsearchClient()
        retriever = DenseRetriever.__new__(DenseRetriever)
        retriever.elasticsearch_client = client
        retriever.elastic_index = "legal"
        retriever.elastic_num_candidates = 250

        points = retriever._search_elasticsearch(
            np.zeros(1024, dtype=np.float32),
            {
                "effect_status": "Con hieu luc",
                "ranges": {"issuance_date_ts": {"gte": 20200101}},
            },
            top_k=5,
        )

        self.assertAlmostEqual(points[0][0], 0.87)
        self.assertEqual(points[0][1], {"chunk_id": "c1", "doc_id": "42"})
        request = client.search.call_args.kwargs
        self.assertEqual(request["index"], "legal")
        self.assertEqual(request["size"], 5)
        self.assertEqual(request["knn"]["field"], "vector")
        self.assertEqual(request["knn"]["k"], 5)
        self.assertEqual(request["knn"]["num_candidates"], 250)
        self.assertEqual(
            request["knn"]["filter"],
            [
                {"term": {"effect_status": "Con hieu luc"}},
                {"range": {"issuance_date_ts": {"gte": 20200101}}},
            ],
        )
        self.assertEqual(request["source_excludes"], ["vector"])

    def test_constructor_accepts_elasticsearch_as_the_only_target(self):
        client = FakeElasticsearchClient()

        with (
            patch("pipeline.embedding.dense_retrieval.Elasticsearch", return_value=client),
            patch(
                "pipeline.embedding.dense_retrieval.load_encoder",
                return_value=("tokenizer", "model", "cpu", "revision"),
            ),
        ):
            retriever = DenseRetriever(
                elastic_cloud_id="cloud-id",
                elastic_api_key="api-key",
                elastic_index="legal",
            )

        self.assertIs(retriever.elasticsearch_client, client)
        self.assertIsNone(retriever.client)
        client.indices.exists.assert_called_once_with(index="legal")
        retriever.close()
        client.close.assert_called_once_with()

    def test_constructor_rejects_qdrant_targets(self):
        with self.assertRaisesRegex(ValueError, "Qdrant"):
            DenseRetriever(
                url="http://localhost:6333",
            )


if __name__ == "__main__":
    unittest.main()
