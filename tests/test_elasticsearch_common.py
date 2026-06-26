import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from elasticsearch_common import (
    build_elasticsearch_filter,
    build_index_definition,
    make_index_action,
    normalize_search_hits,
    resolve_credentials,
    resolve_num_candidates,
)



class ElasticsearchCommonTests(unittest.TestCase):
    def test_resolve_credentials_prefers_explicit_values(self):
        with patch.dict(
            os.environ,
            {"ELASTIC_CLOUD_ID": "env-id", "ELASTIC_API_KEY": "env-key"},
        ):
            self.assertEqual(
                resolve_credentials("arg-id", "arg-key"),
                ("arg-id", "arg-key"),
            )

    def test_resolve_credentials_reads_environment(self):
        with patch.dict(
            os.environ,
            {"ELASTIC_CLOUD_ID": "env-id", "ELASTIC_API_KEY": "env-key"},
        ):
            self.assertEqual(resolve_credentials(None, None), ("env-id", "env-key"))

    def test_resolve_credentials_rejects_missing_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ELASTIC_CLOUD_ID"):
                resolve_credentials(None, None)

    def test_mapping_contains_vector_and_legal_filter_fields(self):
        definition = build_index_definition(number_of_shards=1)
        properties = definition["mappings"]["properties"]

        self.assertEqual(properties["vector"]["dims"], 1024)
        self.assertEqual(properties["vector"]["similarity"], "cosine")
        self.assertEqual(properties["issuance_date_ts"]["type"], "long")
        self.assertEqual(properties["effect_status"]["type"], "keyword")
        self.assertEqual(properties["section_path"]["type"], "keyword")
        self.assertEqual(
            definition["settings"]["index"]["refresh_interval"],
            "-1",
        )
        self.assertEqual(
            definition["settings"]["index"]["number_of_replicas"],
            0,
        )

    def test_make_action_preserves_payload_types_and_omits_nulls(self):
        row = {
            "chunk_id": "c1",
            "doc_id": 10000174386,
            "issuance_date_ts": np.int64(20200101),
            "effect_date_ts": None,
            "section_path": ["Chuong I", "Dieu 1"],
            "do_not_answer_from_summary": np.bool_(True),
        }

        action = make_index_action(
            "legal",
            row,
            np.zeros(1024, dtype=np.float16),
        )

        self.assertEqual(action["_source"]["doc_id"], "10000174386")
        self.assertEqual(action["_source"]["issuance_date_ts"], 20200101)
        self.assertEqual(
            action["_source"]["section_path"],
            ["Chuong I", "Dieu 1"],
        )
        self.assertIs(action["_source"]["do_not_answer_from_summary"], True)
        self.assertNotIn("effect_date_ts", action["_source"])
        self.assertEqual(len(action["_source"]["vector"]), 1024)

    def test_make_action_rejects_invalid_vector(self):
        with self.assertRaisesRegex(ValueError, "vector shape"):
            make_index_action("legal", {"chunk_id": "c1"}, np.zeros(10))

    def test_build_filter_translates_exact_list_and_range_conditions(self):
        result = build_elasticsearch_filter(
            {
                "effect_status": "Con hieu luc",
                "legal_type": ["Nghi dinh", "Thong tu"],
                "title": "Luat Dat dai",
                "doc_id": 42,
                "ranges": {"issuance_date_ts": {"gte": 20200101}},
            }
        )

        self.assertEqual(
            result,
            [
                {"term": {"effect_status": "Con hieu luc"}},
                {"terms": {"legal_type": ["Nghi dinh", "Thong tu"]}},
                {"term": {"title.keyword": "Luat Dat dai"}},
                {"term": {"doc_id": "42"}},
                {"range": {"issuance_date_ts": {"gte": 20200101}}},
            ],
        )

    def test_normalize_search_hits_removes_vector(self):
        hits = [
            {
                "_score": 0.9,
                "_source": {"chunk_id": "c1", "vector": [1.0]},
            }
        ]

        self.assertEqual(
            normalize_search_hits(hits),
            [(0.9, {"chunk_id": "c1"})],
        )

    def test_num_candidates_uses_safe_default_and_cap(self):
        self.assertEqual(resolve_num_candidates(5, None), 100)
        self.assertEqual(resolve_num_candidates(100, None), 2000)
        self.assertEqual(resolve_num_candidates(5, 50), 50)
        self.assertEqual(resolve_num_candidates(9000, 12000), 10000)


if __name__ == "__main__":
    unittest.main()
