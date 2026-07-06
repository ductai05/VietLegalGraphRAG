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
    assert "  backend:" in compose
    assert "  frontend:" in compose
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


def test_frontend_has_nginx_container_definition() -> None:
    compose = read("src/infra/docker-compose.production.yml")
    nginx = read("src/frontend/nginx.conf")

    assert "dockerfile: src/frontend/Dockerfile" in compose
    assert (ROOT / "src/frontend/Dockerfile").is_file()
    assert (ROOT / "src/frontend/nginx.conf").is_file()
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass $backend_upstream" in nginx


def test_deploy_workflow_rebuilds_only_changed_app_services() -> None:
    workflow = read(".github/workflows/deploy.yml")

    assert "git diff --name-only" in workflow
    assert "DEPLOY_BACKEND" in workflow
    assert "DEPLOY_FRONTEND" in workflow
    assert "up -d --no-deps backend" in workflow
    assert "up -d --no-deps frontend" in workflow
    assert "up --build -d" not in workflow


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
    for line in requirements.splitlines():
        if not line or line.startswith("#"):
            continue
        assert re.match(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[0-9][A-Za-z0-9_.!+-]*$", line), line


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
