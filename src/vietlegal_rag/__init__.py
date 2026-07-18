import sys
import os
import threading
from pathlib import Path
from typing import Any

# Add package directories to sys.path to allow legacy absolute imports
_PACKAGE_ROOT = Path(__file__).resolve().parent
_SERVICES_DIR = _PACKAGE_ROOT / "services"
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))


# Lock for building services to avoid race conditions during concurrent startup
_build_lock = threading.Lock()

def build_services(valves: Any):
    """
    Map Valves attributes to environment variables, clear config cache,
    and build service dependency graph.
    """
    with _build_lock:
        # Map Open WebUI Valves to Environment Variables
        env_mappings = {
            "ELASTICSEARCH_URL": valves.elasticsearch_url,
            "ELASTICSEARCH_API_KEY": valves.elasticsearch_api_key,
            "ELASTICSEARCH_INDEX": valves.elasticsearch_index,
            "NEO4J_URI": valves.neo4j_uri,
            "NEO4J_USER": valves.neo4j_user,
            "NEO4J_PASSWORD": valves.neo4j_password,
            "RERANK_PROVIDER": valves.rerank_provider,
            "RERANK_MODEL": valves.rerank_model,
            "EMBEDDING_PROVIDER": valves.embedding_provider,
            "EMBEDDING_MODEL": valves.embedding_model,
            "EMBEDDING_ONNX_MODEL_PATH": valves.embedding_onnx_model_path,
            "EMBEDDING_ONNX_TOKENIZER_PATH": valves.embedding_onnx_tokenizer_path,
            "LLM_PROVIDER": valves.llm_provider,
            "LLM_BASE_URL": valves.llm_base_url,
            "LLM_API_KEY": valves.llm_api_key,
            "LLM_MODEL": valves.llm_model,
            "LLM_MAX_TOKENS": valves.llm_max_tokens,
            "AGENT_ENABLED": valves.agent_enabled,
            "AGENT_MAX_ITERATIONS": valves.agent_max_iterations,
            "WEB_SEARCH_PROVIDER": valves.web_search_provider,
            "EXA_API_KEY": valves.exa_api_key,
        }
        
        for env_key, value in env_mappings.items():
            if value is not None:
                os.environ[env_key] = str(value)
                
        # Import config and dependencies after env vars are set
        from config import get_settings
        from dependencies import get_runtime_services
        
        # Clear both caches so changed Open WebUI Valves rebuild the dependency
        # graph instead of reusing clients configured for older values.
        get_settings.cache_clear()
        get_runtime_services.cache_clear()
        
        # Build and return the services namespace
        return get_runtime_services()
