"""Kaggle single-cell runner for only the Indexing step (using pre-tokenized payload)."""

from __future__ import annotations

import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

SPARSE_VERSION = os.environ.get("SPARSE_VERSION", "v0.1")
SPARSE_DIR = Path(os.environ["SPARSE_DIR"]) if "SPARSE_DIR" in os.environ else None
PAYLOAD_PATH = Path(os.environ["PAYLOAD_PATH"]) if "PAYLOAD_PATH" in os.environ else None
WORK_DIR = Path(os.environ.get("SPARSE_WORK_DIR", "/kaggle/working/legal_sparse"))
ELASTIC_VERSION = os.environ.get("ELASTIC_VERSION", "8.15.3")
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://127.0.0.1:9200")
INDEX_NAME = os.environ.get("ELASTIC_INDEX", "vietlegal_chunks_sparse_v1")
INDEX_ALIAS = os.environ.get("ELASTIC_ALIAS", "vietlegal_chunks_sparse_current")
JAVA_HEAP = os.environ.get("ES_JAVA_HEAP", "2g")
ES_NETWORK_HOST = os.environ.get("ES_NETWORK_HOST", "127.0.0.1")
KEEP_ALIVE = os.environ.get("KEEP_ALIVE", "1") == "1"
RECREATE_INDEX = os.environ.get("RECREATE_INDEX", "1") == "1"
ES_RUN_USER = os.environ.get("ES_RUN_USER", "kaggle_es")
LOG_DIR = WORK_DIR / "logs"

def download_file(url: str, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path)

def ensure_elasticsearch() -> Path:
    archive = WORK_DIR / f"elasticsearch-{ELASTIC_VERSION}-linux-x86_64.tar.gz"
    es_dir = WORK_DIR / f"elasticsearch-{ELASTIC_VERSION}"
    if not es_dir.exists():
        url = f"https://artifacts.elastic.co/downloads/elasticsearch/{archive.name}"
        download_file(url, archive)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(WORK_DIR)
    config_path = es_dir / "config/elasticsearch.yml"
    config_path.write_text(
        "\n".join(
            [
                "cluster.name: vietlegal-sparse",
                "node.name: kaggle-node-1",
                f"network.host: {ES_NETWORK_HOST}",
                "http.port: 9200",
                "discovery.type: single-node",
                "xpack.security.enabled: false",
                f"path.data: {WORK_DIR / 'es_data'}",
                f"path.logs: {WORK_DIR / 'es_logs'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return es_dir

def ensure_cloudflared() -> Path:
    binary = WORK_DIR / "cloudflared"
    if not binary.exists():
        download_file(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
            binary,
        )
    binary.chmod(0o755)
    return binary

def wait_for_elasticsearch(
    url: str,
    timeout_sec: int = 180,
    process: subprocess.Popen | None = None,
) -> None:
    from elasticsearch import Elasticsearch

    client = Elasticsearch(url, verify_certs=False, request_timeout=10)
    started = time.time()
    while time.time() - started < timeout_sec:
        if process is not None and process.poll() is not None:
            client.close()
            raise RuntimeError("Elasticsearch process exited before it became ready")
        try:
            if client.ping():
                client.close()
                return
        except Exception:
            pass
        time.sleep(5)
    client.close()
    raise TimeoutError(f"Elasticsearch did not become ready at {url}")

def running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0

def ensure_es_run_user(es_dir: Path) -> str | None:
    if not running_as_root():
        return None
    exists = subprocess.run(
        ["id", "-u", ES_RUN_USER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        subprocess.run(["useradd", "-m", "-s", "/bin/bash", ES_RUN_USER], check=True)
    subprocess.run(
        ["chown", "-R", f"{ES_RUN_USER}:{ES_RUN_USER}", str(WORK_DIR), str(es_dir)],
        check=True,
    )
    return ES_RUN_USER

def start_elasticsearch(es_dir: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["ES_JAVA_OPTS"] = f"-Xms{JAVA_HEAP} -Xmx{JAVA_HEAP}"
    cmd = [str(es_dir / "bin/elasticsearch")]
    run_user = ensure_es_run_user(es_dir)
    if run_user:
        if shutil.which("runuser"):
            cmd = ["runuser", "-u", run_user, "--", *cmd]
        else:
            cmd = ["su", "-s", "/bin/bash", "-c", shlex.join(cmd), run_user]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = (LOG_DIR / "elasticsearch_stdout.log").open("ab")
    return subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
    )

def start_cloudflared() -> tuple[subprocess.Popen, str | None]:
    binary = ensure_cloudflared()
    proc = subprocess.Popen(
        [str(binary), "tunnel", "--url", ELASTIC_URL],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: queue.Queue[str] = queue.Queue()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = (LOG_DIR / "cloudflared.log").open("a", encoding="utf-8")

    def collect_stdout() -> None:
        try:
            if not proc.stdout:
                return
            for line in proc.stdout:
                log_handle.write(line)
                log_handle.flush()
                lines.put(line)
        finally:
            log_handle.close()

    threading.Thread(target=collect_stdout, daemon=True).start()
    public_url = None
    pattern = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")
    started = time.time()
    while time.time() - started < 90:
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        match = pattern.search(line)
        if match:
            public_url = match.group(0)
            break
    return proc, public_url

def run_step(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], cwd=SPARSE_DIR, check=True)

def require_path(name: str, path: Path | None, env_var: str | None = None) -> None:
    if path is None or not path.exists():
        hint = f" Override this path with the {env_var} environment variable." if env_var else ""
        raise FileNotFoundError(f"{name} not found: {path}.{hint}")

def terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()

def main() -> None:
    require_path("SPARSE_DIR", SPARSE_DIR, "SPARSE_DIR")
    require_path("PAYLOAD_PATH", PAYLOAD_PATH, "PAYLOAD_PATH")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    es_proc = None
    tunnel_proc = None
    try:
        es_dir = ensure_elasticsearch()
        es_proc = start_elasticsearch(es_dir)
        wait_for_elasticsearch(ELASTIC_URL, process=es_proc)
        tunnel_proc, public_url = start_cloudflared()
        print("Elasticsearch local URL:", ELASTIC_URL)
        print("Cloudflare public URL:", public_url or "not detected")

        mapping_path = SPARSE_DIR / "mappings/vietlegal_chunks_sparse_v1.json"
        require_path("mapping", mapping_path)
        
        print(f"Using merged payload from: {PAYLOAD_PATH}")
        
        create_args = [
            "scripts/create_index.py",
            "--url", ELASTIC_URL,
            "--index", INDEX_NAME,
            "--mapping", str(mapping_path),
        ]
        if RECREATE_INDEX:
            create_args.append("--recreate")
        run_step(create_args)
        
        run_step(
            [
                "scripts/ingest_chunks.py",
                "--url", ELASTIC_URL,
                "--payload", str(PAYLOAD_PATH),
                "--index", INDEX_NAME,
                "--alias", INDEX_ALIAS,
                "--batch-size", "1000",
                "--refresh",
            ]
        )

        if KEEP_ALIVE:
            print("Keeping Elasticsearch and Cloudflare tunnel alive.")
            while True:
                time.sleep(60)
    finally:
        terminate_process(tunnel_proc)
        terminate_process(es_proc)

if __name__ == "__main__":
    main()
