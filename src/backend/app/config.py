from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    # VM auto-start/stop management
    vm_provider: str = os.getenv("VM_PROVIDER", "none")
    vm_instance_id: str = os.getenv("VM_INSTANCE_ID", "")
    vm_zone: str = os.getenv("VM_ZONE", "")
    vm_project: str = os.getenv("VM_PROJECT", "")
    vm_idle_timeout: int = int(os.getenv("VM_IDLE_TIMEOUT", "600"))


def get_settings() -> Settings:
    return Settings()
