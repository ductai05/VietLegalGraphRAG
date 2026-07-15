from __future__ import annotations

from pathlib import Path
import re

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_compose_manages_only_app_services() -> None:
    compose = read("src/infra/docker-compose.production.yml")

    assert not (ROOT / "src/infra/docker-compose.droplet.yml").exists()
    assert "  open-webui:" in compose
    assert "  graph_db:" not in compose
    assert "neo4j_prod_data" not in compose
    assert "depends_on:" not in compose
    assert "bolt://graph_db:7687" not in compose
    assert "ELASTICSEARCH_INDEX" in compose
    assert "ELASTICSEARCH_ALIAS" in compose
    assert "ELASTICSEARCH_DENSE_INDEX" not in compose
    assert "ELASTICSEARCH_SPARSE_INDEX" not in compose
    assert "external: true" in compose
    assert "name: vietlegal_net" in compose
    assert '"${FRONTEND_PORT:-80}:8080"' in compose


def test_deploy_workflow_rebuilds_all_app_services() -> None:
    workflow = read(".github/workflows/deploy.yml")

    assert "up -d --no-deps open-webui" in workflow
    assert "up --build -d" not in workflow
    assert "Waiting for open-webui health" in workflow
    assert "curl --fail --silent --show-error" in workflow


def test_ci_runs_lint_and_blocks_tracked_env_files() -> None:
    workflow = read(".github/workflows/ci.yml")

    assert "ruff check" in workflow
    assert "git ls-files '*.env'" in workflow
    assert "!*.env.example" in read(".gitignore")
    assert "https://download.pytorch.org/whl/cpu" in workflow
    assert "grep -v '^torch==' src/backend/requirements.txt" in workflow


def test_neo4j_setup_script_is_destructive_but_guarded() -> None:
    script = read("src/infra/setup_neo4j_droplet.sh")

    assert "--recreate" in script
    assert "--yes-destroy" not in script
    assert "docker volume rm" in script
    assert "rm -rf" in script
    assert "/opt/vietlegal/neo4j/data" in script
    assert "docker network create vietlegal_net" in script
    assert "--network vietlegal_net" in script
    assert "NEO4J_server_bolt_tls__level=OPTIONAL" in script


def test_neo4j_droplet_import_wrapper_uploads_graph_artifacts_over_ssh() -> None:
    script_path = ROOT / "src/infra/scripts/import_neo4j_droplet.sh"
    assert script_path.is_file()

    script = script_path.read_text(encoding="utf-8")
    assert "setup_neo4j_droplet.sh" in script
    assert "/opt/vietlegal/neo4j/import" in script
    assert "scp -P" in script
    assert "ssh -p" in script
    assert "--recreate" in script
    assert "--upload-only" in script
    assert "nodes" in script
    assert "edges" in script


def test_backend_requirements_are_installable_and_include_runtime_clients() -> None:
    requirements = read("src/backend/requirements.txt")

    assert "Cloud SDKs" not in requirements
    assert "python-dotenv" in requirements
    assert "neo4j" in requirements
    assert "elasticsearch" in requirements
    assert "openai" in requirements
    assert "voyageai" in requirements
    assert "onnxruntime" in requirements
    assert "transformers" in requirements
    assert "pypdf" in requirements
    for line in requirements.splitlines():
        if not line or line.startswith("#"):
            continue
        assert re.match(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[0-9][A-Za-z0-9_.!+-]*$", line), line


def test_backend_dockerfile_uses_onnx_runtime() -> None:
    dockerfile = read("src/backend/Dockerfile")

    assert "ONNX Runtime" in dockerfile
    assert "https://download.pytorch.org/whl/cpu" not in dockerfile
    assert "pip install --no-cache-dir -r /tmp/requirements.txt" in dockerfile


def test_production_env_uses_single_hybrid_elasticsearch_index() -> None:
    env = read("src/infra/production.env.example")

    assert "ELASTICSEARCH_INDEX=vietlegal_chunks_hybrid_v1" in env
    assert "ELASTICSEARCH_ALIAS=vietlegal_chunks" in env
    assert "ELASTICSEARCH_DENSE_INDEX" not in env
    assert "ELASTICSEARCH_SPARSE_INDEX" not in env


def test_hybrid_elasticsearch_mapping_combines_sparse_text_and_dense_vector() -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import (
        build_hybrid_index_definition,
    )

    mapping = build_hybrid_index_definition(vector_dims=1024, number_of_shards=2)
    props = mapping["mappings"]["properties"]

    assert props["chunk_text"]["type"] == "text"
    assert props["chunk_text_vi"]["analyzer"] == "vi_whitespace"
    assert props["keyword_index"]["type"] == "boolean"
    assert props["token_estimate"]["type"] == "integer"
    assert props["vector"] == {
        "type": "dense_vector",
        "dims": 1024,
        "index": True,
        "similarity": "cosine",
    }
    assert mapping["settings"]["index"]["number_of_shards"] == 2


def test_hybrid_elasticsearch_actions_use_one_index_and_sparse_then_dense_update() -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import (
        make_dense_update_action,
        make_sparse_index_action,
    )

    sparse_action = make_sparse_index_action(
        "vietlegal_chunks_hybrid_v1",
        {
            "chunk_id": "chunk-1",
            "doc_id": "doc-1",
            "chunk_text": "noi dung",
            "keyword_index": True,
            "token_estimate": 12,
        },
    )
    dense_action = make_dense_update_action(
        "vietlegal_chunks_hybrid_v1",
        {"chunk_id": "chunk-1"},
        np.zeros(1024, dtype=np.float16),
        vector_dims=1024,
    )

    assert sparse_action["_op_type"] == "index"
    assert sparse_action["_index"] == dense_action["_index"]
    assert sparse_action["_id"] == dense_action["_id"] == "chunk-1"
    assert sparse_action["_source"]["chunk_text"] == "noi dung"
    assert "vector" not in sparse_action["_source"]
    assert dense_action["_op_type"] == "update"
    assert dense_action["doc_as_upsert"] is False
    assert dense_action["doc"]["vector"] == [0.0] * 1024


def test_dense_action_batch_skips_duplicate_chunk_ids() -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import (
        DenseDedupeTracker,
        build_dense_action_batch,
    )

    tracker = DenseDedupeTracker()
    rows = [{"chunk_id": "chunk-1"}, {"chunk_id": "chunk-2"}, {"chunk_id": "chunk-1"}]
    vectors = np.zeros((3, 1024), dtype=np.float16)

    actions, failed = build_dense_action_batch(
        rows,
        vectors,
        index="vietlegal_chunks_hybrid_v1",
        vector_dims=1024,
        dead_letter_path=ROOT / "tmp.deadletter.jsonl",
        base_ordinal=0,
        dedupe_tracker=tracker,
    )

    assert failed == 0
    assert [action["_id"] for action in actions] == ["chunk-1", "chunk-2"]
    assert tracker.duplicates_skipped == 1


def test_bulk_actions_passes_trial_tier_sizing_and_backoff_options() -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import bulk_actions

    captured = {}

    class FakeClient:
        def __init__(self) -> None:
            self.option_calls = []

        def options(self, **kwargs):
            self.option_calls.append(kwargs)
            return "client-with-options"

    def fake_bulk(client, actions, **kwargs):
        captured["client"] = client
        captured["actions"] = list(actions)
        captured.update(kwargs)
        return len(captured["actions"]), []

    client = FakeClient()
    result = bulk_actions(
        client=client,
        actions=[{"_id": "1"}, {"_id": "2"}],
        batch_size=100,
        max_chunk_bytes=5 * 1024 * 1024,
        max_retries=4,
        initial_backoff=1.5,
        max_backoff=30.0,
        request_timeout=120,
        dead_letter_path=ROOT / "tmp.deadletter.jsonl",
        phase="sparse_bulk",
        bulk_fn=fake_bulk,
    )

    assert result.ok == 2
    assert result.failed == 0
    assert client.option_calls == [{"request_timeout": 120}]
    assert captured["client"] == "client-with-options"
    assert captured["chunk_size"] == 100
    assert captured["max_chunk_bytes"] == 5 * 1024 * 1024
    assert captured["max_retries"] == 4
    assert captured["initial_backoff"] == 1.5
    assert captured["max_backoff"] == 30.0
    assert captured["retry_on_status"] == (429, 502, 503, 504)
    assert "request_timeout" not in captured


def test_ensure_index_retries_without_shard_and_replica_settings_for_serverless() -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import ensure_index

    class ServerlessCreateError(Exception):
        def __str__(self) -> str:
            return (
                "BadRequestError(400, 'illegal_argument_exception', "
                "'Settings [index.number_of_replicas,index.number_of_shards] "
                "are not available when running in serverless mode')"
            )

    class FakeIndices:
        def __init__(self) -> None:
            self.created_bodies = []

        def exists(self, *, index):
            return False

        def create(self, *, index, body):
            self.created_bodies.append(body)
            if len(self.created_bodies) == 1:
                raise ServerlessCreateError()
            return {"acknowledged": True}

    class FakeClient:
        def __init__(self) -> None:
            self.indices = FakeIndices()

    client = FakeClient()

    ensure_index(
        client,
        index="vietlegal_chunks_hybrid_v1",
        recreate=False,
        vector_dims=1024,
        number_of_shards=1,
    )

    assert len(client.indices.created_bodies) == 2
    first_settings = client.indices.created_bodies[0]["settings"]["index"]
    second_settings = client.indices.created_bodies[1]["settings"]["index"]
    assert "number_of_shards" in first_settings
    assert "number_of_replicas" in first_settings
    assert "number_of_shards" not in second_settings
    assert "number_of_replicas" not in second_settings
    assert client.indices.created_bodies[1]["mappings"]["properties"]["vector"]["dims"] == 1024


def test_dense_shard_path_resolves_manifest_filenames_under_artifact_subdirs(tmp_path) -> None:
    from src.infra.scripts.import_elasticsearch_hybrid import resolve_dense_shard_path

    dense_dir = tmp_path / "vnlegal_lal_v0.1"
    payload_dir = dense_dir / "payload"
    vector_dir = dense_dir / "vectors"
    payload_dir.mkdir(parents=True)
    vector_dir.mkdir(parents=True)
    payload_file = payload_dir / "payload_shard_00000.parquet"
    vector_file = vector_dir / "vectors_shard_00000.npy"
    payload_file.touch()
    vector_file.touch()

    assert (
        resolve_dense_shard_path(
            dense_dir,
            "payload_shard_00000.parquet",
            artifact_subdir="payload",
        )
        == payload_file
    )
    assert (
        resolve_dense_shard_path(
            dense_dir,
            "vectors_shard_00000.npy",
            artifact_subdir="vectors",
        )
        == vector_file
    )


def test_env_examples_do_not_reintroduce_retired_backend_keys() -> None:
    retired = {
        "ELASTICSEARCH_DENSE_INDEX",
        "ELASTICSEARCH_SPARSE_INDEX",
        "DEFAULT_RETRIEVAL_MODE",
        "DEFAULT_TEMPERATURE",
        "BACKEND_HOST",
        "RERANK_DEVICE",
        "RERANK_TIMEOUT_MS",
    }
    for path in (
        ".env.example",
        "src/infra/.env.example",
        "src/infra/production.env.example",
    ):
        content = read(path)
        for key in retired:
            assert f"{key}=" not in content, f"{key} should not appear in {path}"


def test_hf_cache_is_ignored_and_warning_suppressed_in_examples() -> None:
    assert "src/infra/hf-cache/" in read(".gitignore")
    for path in (
        ".env.example",
        "src/infra/.env.example",
        "src/infra/production.env.example",
    ):
        assert "HF_HUB_DISABLE_SYMLINKS_WARNING=1" in read(path)
