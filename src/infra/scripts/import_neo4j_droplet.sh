#!/usr/bin/env bash
set -Eeuo pipefail

# Upload graph CSV artifacts to a DigitalOcean Droplet and optionally recreate
# the Neo4j container using src/infra/setup_neo4j_droplet.sh.

usage() {
    cat <<'EOF'
Usage:
  import_neo4j_droplet.sh --host <droplet_ip> --neo4j-password <password> --recreate [options]
  import_neo4j_droplet.sh --host <droplet_ip> --upload-only [options]

Options:
  --host <host>                 Droplet host or IP. Required.
  --user <user>                 SSH user. Default: root.
  --ssh-port <port>             SSH port. Default: 22.
  --source <dir>                Graph artifact directory. Default: data/retrieval/graph/kg_v0.1.
  --remote-import-dir <dir>     Remote Neo4j import dir. Default: /opt/vietlegal/neo4j/import.
  --setup-script <path>         Local setup_neo4j_droplet.sh path.
  --neo4j-password <password>   Neo4j password used by setup script.
  --recreate                    After upload, destroy/recreate Neo4j data and import CSVs.
  --upload-only                 Upload CSVs only, do not run setup.
  -h, --help                    Show this help.

The source directory may contain CSVs directly or under nodes/ and edges/.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd -P)"

SSH_HOST=""
SSH_USER="root"
SSH_PORT="22"
SOURCE_DIR="${REPO_ROOT}/data/retrieval/graph/kg_v0.1"
REMOTE_IMPORT_DIR="/opt/vietlegal/neo4j/import"
SETUP_SCRIPT="${REPO_ROOT}/src/infra/setup_neo4j_droplet.sh"
NEO4J_PASSWORD=""
RECREATE="false"
UPLOAD_ONLY="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            SSH_HOST="${2:?--host requires a value}"
            shift 2
            ;;
        --user)
            SSH_USER="${2:?--user requires a value}"
            shift 2
            ;;
        --ssh-port)
            SSH_PORT="${2:?--ssh-port requires a value}"
            shift 2
            ;;
        --source)
            SOURCE_DIR="${2:?--source requires a value}"
            shift 2
            ;;
        --remote-import-dir)
            REMOTE_IMPORT_DIR="${2:?--remote-import-dir requires a value}"
            shift 2
            ;;
        --setup-script)
            SETUP_SCRIPT="${2:?--setup-script requires a value}"
            shift 2
            ;;
        --neo4j-password)
            NEO4J_PASSWORD="${2:?--neo4j-password requires a value}"
            shift 2
            ;;
        --recreate)
            RECREATE="true"
            shift
            ;;
        --upload-only)
            UPLOAD_ONLY="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${SSH_HOST}" ]]; then
    echo "--host is required" >&2
    usage >&2
    exit 2
fi

if [[ "${RECREATE}" == "true" && "${UPLOAD_ONLY}" == "true" ]]; then
    echo "Use either --recreate or --upload-only, not both" >&2
    exit 2
fi

if [[ "${UPLOAD_ONLY}" != "true" && "${RECREATE}" != "true" ]]; then
    echo "Refusing to run without --recreate or --upload-only" >&2
    exit 2
fi

if [[ "${RECREATE}" == "true" && -z "${NEO4J_PASSWORD}" ]]; then
    echo "--neo4j-password is required with --recreate" >&2
    exit 2
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
    echo "Graph source directory not found: ${SOURCE_DIR}" >&2
    exit 1
fi

if [[ ! -f "${SETUP_SCRIPT}" ]]; then
    echo "Neo4j setup script not found: ${SETUP_SCRIPT}" >&2
    exit 1
fi

mapfile -t CSV_FILES < <(
    {
        find "${SOURCE_DIR}" -maxdepth 1 -type f -name "*.csv"
        if [[ -d "${SOURCE_DIR}/nodes" ]]; then
            find "${SOURCE_DIR}/nodes" -maxdepth 1 -type f -name "*.csv"
        fi
        if [[ -d "${SOURCE_DIR}/edges" ]]; then
            find "${SOURCE_DIR}/edges" -maxdepth 1 -type f -name "*.csv"
        fi
    } | sort -u
)

if [[ "${#CSV_FILES[@]}" -eq 0 ]]; then
    echo "No CSV files found under ${SOURCE_DIR}, ${SOURCE_DIR}/nodes, or ${SOURCE_DIR}/edges" >&2
    exit 1
fi

REMOTE="${SSH_USER}@${SSH_HOST}"

echo "Creating remote import directory: ${REMOTE_IMPORT_DIR}"
ssh -p "${SSH_PORT}" "${REMOTE}" "mkdir -p '${REMOTE_IMPORT_DIR}' && rm -f '${REMOTE_IMPORT_DIR}'/*.csv"

echo "Uploading ${#CSV_FILES[@]} graph CSV file(s)"
for csv_file in "${CSV_FILES[@]}"; do
    scp -P "${SSH_PORT}" "${csv_file}" "${REMOTE}:${REMOTE_IMPORT_DIR}/"
done

if [[ "${UPLOAD_ONLY}" == "true" ]]; then
    echo "Upload complete. Neo4j setup was not run because --upload-only was selected."
    exit 0
fi

echo "Uploading setup script"
scp -P "${SSH_PORT}" "${SETUP_SCRIPT}" "${REMOTE}:/tmp/setup_neo4j_droplet.sh"

echo "Running Neo4j recreate/import on Droplet"
ssh -p "${SSH_PORT}" "${REMOTE}" \
    "bash /tmp/setup_neo4j_droplet.sh --recreate '${NEO4J_PASSWORD}' '${REMOTE_IMPORT_DIR}'"

echo "Neo4j recreate/import command completed"
