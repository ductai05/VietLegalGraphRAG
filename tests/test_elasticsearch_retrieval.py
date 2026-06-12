import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

EMBEDDING_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "04_embedding"
sys.path.insert(0, str(EMBEDDING_DIR))

if "polars" not in sys.modules:
    polars_module = types.ModuleType("polars")
    sys.modules["polars"] = polars_module

if "pyarrow" not in sys.modules:
    pyarrow_module = types.ModuleType("pyarrow")
    pyarrow_ipc_module = types.ModuleType("pyarrow.ipc")
    pyarrow_module.ipc = pyarrow_ipc_module
    sys.modules["pyarrow"] = pyarrow_module
    sys.modules["pyarrow.ipc"] = pyarrow_ipc_module

if "elasticsearch" not in sys.modules:
    elasticsearch_module = types.ModuleType("elasticsearch")
    elasticsearch_helpers_module = types.ModuleType("elasticsearch.helpers")
    elasticsearch_module.Elasticsearch = object
    elasticsearch_module.helpers = elasticsearch_helpers_module
    sys.modules["elasticsearch"] = elasticsearch_module
    sys.modules["elasticsearch.helpers"] = elasticsearch_helpers_module

from dense_retrieval import DenseRetriever  # noqa: E402


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
            patch("dense_retrieval.Elasticsearch", return_value=client),
            patch(
                "dense_retrieval.load_encoder",
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

    def test_constructor_rejects_multiple_targets(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            DenseRetriever(
                url="http://localhost:6333",
                elastic_cloud_id="cloud-id",
                elastic_api_key="api-key",
            )


if __name__ == "__main__":
    unittest.main()
