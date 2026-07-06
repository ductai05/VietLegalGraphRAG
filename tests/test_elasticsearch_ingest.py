import sys
import types
import unittest
from pathlib import Path

import numpy as np

from pipeline.embedding.scripts.build_elasticsearch import (
    prepare_build_manifest,
    upload_and_checkpoint_shard,
    upload_shard,
)



class FakePayload:
    def __init__(self, rows):
        self._rows = rows
        self.height = len(rows)

    def iter_rows(self, *, named):
        if not named:
            raise AssertionError("upload_shard must request named rows")
        yield from self._rows


class ElasticsearchIngestTests(unittest.TestCase):
    def setUp(self):
        self.payload = FakePayload(
            [
                {"chunk_id": "c1", "doc_id": 1},
                {"chunk_id": "c2", "doc_id": 2},
            ]
        )
        self.vectors = np.zeros((2, 1024), dtype=np.float16)

    def test_prepare_manifest_marks_resumed_run_unfinalized(self):
        manifest = {
            "index": "legal",
            "source_manifest_fingerprint": "same-source",
            "finalized": True,
            "shards": {"00000": {"status": "done", "rows": 2}},
        }

        prepared = prepare_build_manifest(
            manifest,
            index="legal",
            source_manifest_fingerprint="same-source",
            recreate=False,
            workers=2,
            batch_size=500,
            max_chunk_mb=20,
            queue_size=2,
        )

        self.assertIs(prepared, manifest)
        self.assertFalse(prepared["finalized"])
        self.assertEqual(prepared["shards"]["00000"]["status"], "done")

    def test_prepare_manifest_rejects_changed_source_on_resume(self):
        manifest = {
            "index": "legal",
            "source_manifest_fingerprint": "old-source",
            "shards": {"00000": {"status": "done", "rows": 2}},
        }

        with self.assertRaisesRegex(ValueError, "source manifest changed"):
            prepare_build_manifest(
                manifest,
                index="legal",
                source_manifest_fingerprint="new-source",
                recreate=False,
                workers=2,
                batch_size=500,
                max_chunk_mb=20,
                queue_size=2,
            )

    def test_upload_shard_uses_bounded_parallel_bulk_settings(self):
        captured = {}

        def fake_parallel_bulk(client, actions, **kwargs):
            captured["client"] = client
            captured.update(kwargs)
            materialized = list(actions)
            captured["actions"] = materialized
            return iter(
                (True, {"index": {"_id": action["_id"], "status": 201}})
                for action in materialized
            )

        result = upload_shard(
            es="fake-client",
            index="legal",
            payload_df=self.payload,
            vectors=self.vectors,
            workers=2,
            batch_size=500,
            max_chunk_bytes=20 * 1024 * 1024,
            queue_size=2,
            parallel_bulk_fn=fake_parallel_bulk,
        )

        self.assertEqual(result.uploaded, 2)
        self.assertEqual(result.failed, 0)
        self.assertGreater(result.rows_per_second, 0)
        self.assertEqual(captured["client"], "fake-client")
        self.assertEqual(captured["thread_count"], 2)
        self.assertEqual(captured["chunk_size"], 500)
        self.assertEqual(captured["max_chunk_bytes"], 20 * 1024 * 1024)
        self.assertEqual(captured["queue_size"], 2)
        self.assertNotIn("retry_on_status", captured)
        self.assertNotIn("max_retries", captured)
        self.assertNotIn("yield_ok", captured)
        self.assertEqual(len(captured["actions"]), 2)

    def test_upload_shard_retries_only_retryable_failed_actions(self):
        calls = []
        sleeps = []

        def fake_parallel_bulk(client, actions, **kwargs):
            materialized = list(actions)
            calls.append(materialized)
            if len(calls) == 1:
                return iter(
                    [
                        (True, {"index": {"_id": materialized[0]["_id"], "status": 201}}),
                        (
                            False,
                            {
                                "index": {
                                    "_id": materialized[1]["_id"],
                                    "status": 429,
                                    "error": {"reason": "busy"},
                                }
                            },
                        ),
                    ]
                )
            return iter(
                [(True, {"index": {"_id": materialized[0]["_id"], "status": 201}})]
            )

        with self.assertLogs(level="WARNING"):
            result = upload_shard(
                es="fake-client",
                index="legal",
                payload_df=self.payload,
                vectors=self.vectors,
                workers=2,
                batch_size=500,
                max_chunk_bytes=20 * 1024 * 1024,
                queue_size=2,
                parallel_bulk_fn=fake_parallel_bulk,
                max_retries=2,
                sleep_fn=sleeps.append,
            )

        self.assertEqual(result.uploaded, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[1]), 1)
        self.assertEqual(calls[1][0]["_id"], calls[0][1]["_id"])
        self.assertEqual(sleeps, [2])

    def test_upload_shard_raises_when_any_bulk_item_fails(self):
        def fake_parallel_bulk(client, actions, **kwargs):
            materialized = list(actions)
            return iter(
                [
                    (True, {"index": {"_id": materialized[0]["_id"], "status": 201}}),
                    (
                        False,
                        {
                            "index": {
                                "_id": materialized[1]["_id"],
                                "status": 429,
                                "error": {
                                    "type": "es_rejected_execution_exception",
                                    "reason": "trial cluster is busy",
                                },
                            }
                        },
                    ),
                ]
            )

        with self.assertLogs(level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "1 document"):
                upload_shard(
                    es="fake-client",
                    index="legal",
                    payload_df=self.payload,
                    vectors=self.vectors,
                    workers=2,
                    batch_size=500,
                    max_chunk_bytes=20 * 1024 * 1024,
                    queue_size=2,
                    parallel_bulk_fn=fake_parallel_bulk,
                    max_retries=0,
                )

    def test_upload_shard_rejects_payload_vector_row_mismatch(self):
        with self.assertRaisesRegex(ValueError, "row mismatch"):
            upload_shard(
                es="fake-client",
                index="legal",
                payload_df=self.payload,
                vectors=self.vectors[:1],
                workers=2,
                batch_size=500,
                max_chunk_bytes=20 * 1024 * 1024,
                queue_size=2,
                parallel_bulk_fn=lambda *args, **kwargs: iter(()),
            )

    def test_failed_upload_does_not_checkpoint_shard(self):
        manifest = {"shards": {}}
        writes = []

        def failed_parallel_bulk(client, actions, **kwargs):
            action = next(iter(actions))
            return iter(
                [
                    (
                        False,
                        {
                            "index": {
                                "_id": action["_id"],
                                "status": 429,
                                "error": {"reason": "busy"},
                            }
                        },
                    )
                ]
            )

        with self.assertLogs(level="ERROR"):
            with self.assertRaises(RuntimeError):
                upload_and_checkpoint_shard(
                    es="fake-client",
                    index="legal",
                    shard_key="00000",
                    payload_df=FakePayload([{"chunk_id": "c1"}]),
                    vectors=self.vectors[:1],
                    build_manifest=manifest,
                    build_manifest_path=Path("manifest.json"),
                    workers=2,
                    batch_size=500,
                    max_chunk_bytes=20 * 1024 * 1024,
                    queue_size=2,
                    parallel_bulk_fn=failed_parallel_bulk,
                    max_retries=0,
                    write_manifest_fn=lambda path, data: writes.append((path, data)),
                )

        self.assertEqual(manifest, {"shards": {}})
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
