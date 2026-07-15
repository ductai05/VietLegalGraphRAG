"""Upsert VietLegal RAG pipe function on every container start."""
import os
import time
import sys
import logging
import requests
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("init_pipe")

WEBUI_URL = "http://localhost:8080"
ADMIN_EMAIL = os.environ.get("WEBUI_ADMIN_EMAIL", "admin@vietlegal.local")
ADMIN_PASSWORD = os.environ.get("WEBUI_ADMIN_PASSWORD", "VietLegalAdmin2026!")

# Path to the pipe.py file that contains our Pipe class
PIPE_PATH = Path("/app/vietlegal_rag/pipe.py")

def wait_for_webui(max_retries=60, interval=2):
    """Wait for Open WebUI to start and be responsive (using readiness check)."""
    for i in range(max_retries):
        try:
            # Use /ready endpoint to ensure DB migrations and provisions are done
            r = requests.get(f"{WEBUI_URL}/ready", timeout=5)
            if r.status_code == 200:
                logger.info("Open WebUI readiness check passed.")
                return
        except Exception:
            pass
        logger.info(f"Waiting for Open WebUI database/readiness... ({i+1}/{max_retries})")
        time.sleep(interval)
    sys.exit("ERROR: Open WebUI did not become ready in time.")

def get_admin_token() -> str:
    """Authenticate using auto-provisioned admin credentials to obtain JWT token."""
    signin_url = f"{WEBUI_URL}/api/v1/auths/signin"
    logger.info(f"Authenticating as {ADMIN_EMAIL} via {signin_url}...")
    r = requests.post(signin_url, json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    }, timeout=10)
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise ValueError("No token returned in auth response")
    logger.info("Authentication successful.")
    return token

def upsert_function(token: str):
    """Register or update the Pipe function inside Open WebUI's database."""
    if not PIPE_PATH.exists():
        logger.error(f"Pipe source file not found at {PIPE_PATH}")
        return
        
    code_content = PIPE_PATH.read_text(encoding="utf-8")
    
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "id": "vietlegal_rag",
        "name": "VietLegal RAG",
        "type": "pipe",
        "content": code_content,
        "meta": {
            "description": "Vietnamese Legal RAG with Graph-enhanced retrieval"
        },
        "is_active": True,
        "is_global": True,
    }
    
    # Try updating the existing function first
    update_url = f"{WEBUI_URL}/api/v1/functions/id/vietlegal_rag/update"
    logger.info(f"Attempting to update existing pipe function at {update_url}...")
    try:
        r = requests.post(update_url, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            logger.info("Pipe function updated successfully.")
            return
        elif r.status_code == 404:
            logger.info("Function not found, creating a new one...")
        else:
            r.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to update function (might not exist yet): {e}")
        
    # Create the function since update returned 404
    create_url = f"{WEBUI_URL}/api/v1/functions/create"
    logger.info(f"Creating pipe function at {create_url}...")
    try:
        r = requests.post(create_url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        logger.info("Pipe function registered successfully.")
    except Exception as e:
        logger.error(f"Failed to register pipe function: {e}")

if __name__ == "__main__":
    wait_for_webui()
    
    # Try to authenticate. Since the admin auto-creation runs on first launch,
    # we might need to retry a few times in case the DB migrations are still running.
    token = ""
    for attempt in range(10):
        try:
            token = get_admin_token()
            if token:
                break
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed to obtain admin token: {e}")
        
        logger.info("Retrying authentication in 5 seconds...")
        time.sleep(5)
        
    if not token:
        logger.error("Could not obtain admin token. Auto-registration aborted.")
        sys.exit(1)
        
    upsert_function(token)

    # Force enable the function in SQLite to ensure is_active and is_global are 1 (True)
    try:
        import sqlite3
        db_path = '/app/backend/data/webui.db'
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE function SET is_active = 1, is_global = 1 WHERE id = 'vietlegal_rag'")
            conn.commit()
            logger.info(f"Forced function activation in SQLite. Rows updated: {cursor.rowcount}")
            conn.close()
    except Exception as e:
        logger.error(f"Failed to force enable function in SQLite database: {e}")

