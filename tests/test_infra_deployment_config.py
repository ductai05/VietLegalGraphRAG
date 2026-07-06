from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_compose_manages_only_app_services() -> None:
    compose = read("src/infra/docker-compose.production.yml")

    assert "  backend:" in compose
    assert "  frontend:" in compose
    assert "  graph_db:" not in compose
    assert "neo4j_prod_data" not in compose
    assert "depends_on:" not in compose
    assert "bolt://graph_db:7687" not in compose
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
