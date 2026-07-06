#!/usr/bin/env bash
# VietLegalGraphRAG Neo4j setup for a DigitalOcean Droplet.
#
# This script is intentionally destructive. It stops old Neo4j containers,
# removes known old Neo4j Docker volumes, deletes the new Neo4j data directory,
# imports CSV files, and starts a fresh Neo4j container on the shared Docker
# bridge network used by the backend and frontend.
#
# Upload data first, for example:
#   ssh root@<DROPLET_IP> 'mkdir -p /opt/vietlegal/neo4j/import'
#   scp documents.csv articles.csv legal_types.csv authorities.csv sectors.csv root@<DROPLET_IP>:/opt/vietlegal/neo4j/import/
#   scp *_edges.csv root@<DROPLET_IP>:/opt/vietlegal/neo4j/import/
#
# Run:
#   bash setup_neo4j_droplet.sh --yes-recreate '<neo4j_password>'

set -euo pipefail

if [ "${1:-}" != "--yes-recreate" ]; then
    echo "Refusing to run without explicit destructive confirmation."
    echo "Usage: $0 --yes-recreate <neo4j_password> [import_dir] [neo4j_image]"
    exit 2
fi

NEO4J_PASSWORD="${2:?Usage: $0 --yes-recreate <neo4j_password> [import_dir] [neo4j_image]}"
IMPORT_DIR="${3:-/opt/vietlegal/neo4j/import}"
NEO4J_IMAGE="${4:-neo4j:5-community}"

RUNTIME_ROOT="/opt/vietlegal"
NEO4J_ROOT="${RUNTIME_ROOT}/neo4j"
DATA_DIR="${NEO4J_ROOT}/data"
CERT_DIR="${NEO4J_ROOT}/certs"
NETWORK_NAME="vietlegal_net"
CONTAINER_NAME="vietlegal-neo4j"

REQUIRED_FILES=(
    documents.csv
    articles.csv
    legal_types.csv
    authorities.csv
    sectors.csv
    doc_doc_edges.csv
    doc_art_edges.csv
    art_art_next_edges.csv
    art_art_parent_edges.csv
    doc_type_edges.csv
    doc_auth_edges.csv
    doc_sector_edges.csv
)

echo "============================================"
echo "  VietLegalGraphRAG Neo4j destructive setup"
echo "============================================"
echo "Runtime root: ${RUNTIME_ROOT}"
echo "Import dir:   ${IMPORT_DIR}"
echo "Data dir:     ${DATA_DIR}"
echo "Container:    ${CONTAINER_NAME}"
echo "Network:      ${NETWORK_NAME}"
echo ""

echo "=== STEP 1: Installing Docker prerequisites ==="
if ! command -v docker >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq docker.io
    systemctl enable docker
    systemctl start docker
    echo "Docker installed"
else
    echo "Docker already installed"
fi

if ! docker compose version >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose-v2 || true
fi

echo "=== STEP 2: Configuring swap ==="
if ! swapon --show | grep -q "/swapfile"; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    if ! grep -q '^/swapfile ' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    echo "Swap configured"
else
    echo "Swap already configured"
fi

echo "=== STEP 3: Configuring firewall ==="
if command -v ufw >/dev/null 2>&1; then
    ufw allow OpenSSH
    ufw allow 80/tcp
    ufw allow 8000/tcp
    ufw allow 7687/tcp
    ufw allow 7473/tcp
    ufw --force enable
    echo "UFW configured"
else
    echo "ufw not found, skipping firewall configuration"
fi

echo "=== STEP 4: Validating import files ==="
if [ ! -d "${IMPORT_DIR}" ]; then
    echo "Import directory does not exist: ${IMPORT_DIR}"
    exit 1
fi

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "${IMPORT_DIR}/${file}" ]; then
        echo "Missing required import file: ${IMPORT_DIR}/${file}"
        exit 1
    fi
done
echo "Import files validated"

echo "=== STEP 5: Creating Docker network ==="
docker network create vietlegal_net >/dev/null 2>&1 || true

echo "=== STEP 6: Generating TLS certificates ==="
rm -rf "${CERT_DIR}"
mkdir -p "${CERT_DIR}/bolt/trusted" "${CERT_DIR}/bolt/revoked"
mkdir -p "${CERT_DIR}/https/trusted" "${CERT_DIR}/https/revoked"

openssl req -x509 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/private.key" \
    -out "${CERT_DIR}/public.crt" \
    -days 1095 -nodes \
    -subj "/CN=vietlegal-neo4j/O=VietLegalGraphRAG" \
    >/dev/null 2>&1

cp "${CERT_DIR}/private.key" "${CERT_DIR}/bolt/private.key"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/public.crt"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/trusted/public.crt"
cp "${CERT_DIR}/private.key" "${CERT_DIR}/https/private.key"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/public.crt"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/trusted/public.crt"
chown -R 7474:7474 "${CERT_DIR}"
chmod 600 "${CERT_DIR}/bolt/private.key" "${CERT_DIR}/https/private.key"
echo "TLS certificates generated"

echo "=== STEP 7: Removing old Neo4j containers, volumes, and data ==="
docker stop "${CONTAINER_NAME}" neo4j-legal graph_db infra-graph_db-1 vietlegal-app-graph_db-1 vietlegal-neo4j-neo4j-1 2>/dev/null || true
docker rm "${CONTAINER_NAME}" neo4j-legal graph_db infra-graph_db-1 vietlegal-app-graph_db-1 vietlegal-neo4j-neo4j-1 2>/dev/null || true
docker volume rm neo4j_prod_data infra_neo4j_prod_data vietlegal_neo4j_prod_data vietlegal-app_neo4j_prod_data 2>/dev/null || true

case "${DATA_DIR}" in
    /opt/vietlegal/neo4j/data)
        rm -rf "${DATA_DIR}"
        ;;
    *)
        echo "Refusing to delete unexpected data directory: ${DATA_DIR}"
        exit 1
        ;;
esac

mkdir -p "${DATA_DIR}"
chown -R 7474:7474 "${DATA_DIR}"
echo "Old Neo4j runtime removed"

echo "=== STEP 8: Running Neo4j bulk import ==="
docker run --rm \
    -v "${IMPORT_DIR}:/import:ro" \
    -v "${DATA_DIR}:/data" \
    "${NEO4J_IMAGE}" \
    neo4j-admin database import full \
        --skip-duplicate-nodes=true \
        --skip-bad-relationships=true \
        --report-file=/data/import.report \
        --nodes=Document=/import/documents.csv \
        --nodes=Article=/import/articles.csv \
        --nodes=LegalType=/import/legal_types.csv \
        --nodes=Authority=/import/authorities.csv \
        --nodes=Sector=/import/sectors.csv \
        --relationships=/import/doc_doc_edges.csv \
        --relationships=/import/doc_art_edges.csv \
        --relationships=/import/art_art_next_edges.csv \
        --relationships=/import/art_art_parent_edges.csv \
        --relationships=/import/doc_type_edges.csv \
        --relationships=/import/doc_auth_edges.csv \
        --relationships=/import/doc_sector_edges.csv \
        --overwrite-destination=true \
        neo4j

chown -R 7474:7474 "${DATA_DIR}"
echo "Bulk import completed"

echo "=== STEP 9: Starting Neo4j container ==="
docker run -d \
    --name "${CONTAINER_NAME}" \
    --hostname "${CONTAINER_NAME}" \
    --network vietlegal_net \
    --restart unless-stopped \
    -p 7687:7687 \
    -p 7473:7473 \
    -v "${DATA_DIR}:/data" \
    -v "${CERT_DIR}:/certificates:ro" \
    -v "${IMPORT_DIR}:/import:ro" \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_memory_heap_initial__size=1024m \
    -e NEO4J_server_memory_heap_max__size=1024m \
    -e NEO4J_server_memory_pagecache_size=1500m \
    -e NEO4J_server_bolt_enabled=true \
    -e NEO4J_server_bolt_tls__level=OPTIONAL \
    -e NEO4J_server_bolt_listen__address=0.0.0.0:7687 \
    -e NEO4J_server_https_enabled=true \
    -e NEO4J_server_https_listen__address=0.0.0.0:7473 \
    -e NEO4J_server_http_enabled=false \
    -e NEO4J_dbms_ssl_policy_bolt_enabled=true \
    -e NEO4J_dbms_ssl_policy_bolt_base__directory=/certificates/bolt \
    -e NEO4J_dbms_ssl_policy_bolt_private__key=private.key \
    -e NEO4J_dbms_ssl_policy_bolt_public__certificate=public.crt \
    -e NEO4J_dbms_ssl_policy_bolt_client__auth=NONE \
    -e NEO4J_dbms_ssl_policy_https_enabled=true \
    -e NEO4J_dbms_ssl_policy_https_base__directory=/certificates/https \
    -e NEO4J_dbms_ssl_policy_https_private__key=private.key \
    -e NEO4J_dbms_ssl_policy_https_public__certificate=public.crt \
    -e NEO4J_dbms_ssl_policy_https_client__auth=NONE \
    "${NEO4J_IMAGE}"

echo ""
echo "Neo4j setup complete"
echo "Internal backend URI: bolt://vietlegal-neo4j:7687"
echo "External Bolt URI:    neo4j+ssc://<DROPLET_IP>:7687"
echo "Browser console:      https://<DROPLET_IP>:7473"
echo "Username:             neo4j"
echo "Password:             ${NEO4J_PASSWORD}"
