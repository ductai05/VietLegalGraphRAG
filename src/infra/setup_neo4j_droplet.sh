#!/usr/bin/env bash
# =============================================================================
# VietLegalGraphRAG — DigitalOcean Droplet Neo4j Setup Script
# =============================================================================
# This script sets up Neo4j with TLS on a DigitalOcean Droplet.
#
# Prerequisite:
#   1. Create an Ubuntu Droplet on DigitalOcean (2 vCPU, 4GB/8GB RAM recommended).
#   2. Copy the contents of your local 'data/graph/' directory to '/tmp/neo4j_imports/' on the Droplet:
#      scp -r data/graph/ root@<DROPLET_IP>:/tmp/neo4j_imports/
#   3. Copy this script to the Droplet and run it:
#      scp src/infra/setup_neo4j_droplet.sh root@<DROPLET_IP>:/tmp/
#      ssh root@<DROPLET_IP> 'bash /tmp/setup_neo4j_droplet.sh "your_strong_password"'
# =============================================================================

set -euo pipefail

NEO4J_PASSWORD="${1:?Usage: $0 <neo4j_password>}"
IMPORT_DIR="${2:-/tmp/neo4j_imports}"
NEO4J_IMAGE="${3:-neo4j:5-community}"

CERT_DIR="/opt/neo4j-certs"
DATA_DIR="/opt/neo4j-data"

echo "============================================"
echo "  VietLegalGraphRAG — Neo4j DO Droplet Setup"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# STEP 1: Install Docker and Configure Swap
# ---------------------------------------------------------------------------
echo "=== STEP 1: Installing Docker and Configuring Swap ==="
if ! command -v docker &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq docker.io
    systemctl enable docker
    systemctl start docker
    echo "✅ Docker installed successfully"
else
    echo "✅ Docker is already installed"
fi

# Configure Swap if not already configured (Crucial for 4GB Droplet during bulk import)
if ! swapon --show | grep -q "/swapfile"; then
    echo "Configuring 4GB Swap Space..."
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "✅ Swap space configured"
else
    echo "✅ Swap space already configured"
fi

# ---------------------------------------------------------------------------
# STEP 2: Configure UFW (Firewall)
# ---------------------------------------------------------------------------
echo "=== STEP 2: Configuring Firewall ==="
if command -v ufw &>/dev/null; then
    # Allow SSH (required to prevent lockouts)
    ufw allow OpenSSH
    # Allow bolt+s (7687) and HTTPS browser (7473)
    ufw allow 7687/tcp
    ufw allow 7473/tcp
    # Enable UFW non-interactively
    ufw --force enable
    echo "✅ UFW configured: ports 7687, 7473 allowed"
else
    echo "⚠️ ufw not found, skipping firewall config. Please ensure ports 7687 & 7473 are open."
fi

# ---------------------------------------------------------------------------
# STEP 3: Generate Self-signed TLS Certificates
# ---------------------------------------------------------------------------
echo "=== STEP 3: Generating TLS Certificates ==="
mkdir -p "${CERT_DIR}" "${DATA_DIR}"

# Generate self-signed cert (valid 3 years)
openssl req -x509 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/private.key" \
    -out "${CERT_DIR}/public.crt" \
    -days 1095 -nodes \
    -subj "/CN=neo4j-legal/O=VietLegalGraphRAG" \
    2>/dev/null

# Neo4j expects specific file structure for bolt TLS
mkdir -p "${CERT_DIR}/bolt/trusted" "${CERT_DIR}/bolt/revoked"
cp "${CERT_DIR}/private.key" "${CERT_DIR}/bolt/"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/trusted/"

# Same for HTTPS connector
mkdir -p "${CERT_DIR}/https/trusted" "${CERT_DIR}/https/revoked"
cp "${CERT_DIR}/private.key" "${CERT_DIR}/https/"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/"
cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/trusted/"

# Fix ownership for Neo4j Docker container (runs as 7474 by default)
chown -R 7474:7474 "${CERT_DIR}"
chmod 600 "${CERT_DIR}/bolt/private.key" "${CERT_DIR}/https/private.key"

echo "✅ TLS certificates generated at ${CERT_DIR}"

# ---------------------------------------------------------------------------
# STEP 4: Stop existing container
# ---------------------------------------------------------------------------
docker stop neo4j-legal 2>/dev/null || true
docker rm neo4j-legal 2>/dev/null || true

# ---------------------------------------------------------------------------
# STEP 5: Run Bulk Import
# ---------------------------------------------------------------------------
echo "=== STEP 5: Running Neo4j Bulk Import ==="
if [ ! -d "${IMPORT_DIR}" ]; then
    echo "❌ ERROR: Import directory not found at: ${IMPORT_DIR}"
    echo "Please upload your CSV files to the Droplet first."
    exit 1
fi

docker run --rm \
    -v "${IMPORT_DIR}:/import" \
    -v "${DATA_DIR}:/data" \
    "${NEO4J_IMAGE}" \
    neo4j-admin database import full \
        --skip-duplicate-nodes=true \
        --skip-bad-relationships=true \
        --report-file=/import/import.report \
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

echo "✅ Bulk import completed successfully"

# ---------------------------------------------------------------------------
# STEP 6: Launch Neo4j with TLS
# ---------------------------------------------------------------------------
echo "=== STEP 6: Starting Neo4j Container with TLS ==="
docker run -d \
    --name neo4j-legal \
    --restart unless-stopped \
    -p 7687:7687 \
    -p 7473:7473 \
    -v "${DATA_DIR}:/data" \
    -v "${CERT_DIR}:/certificates" \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_memory_heap_initial__size=1024m \
    -e NEO4J_server_memory_heap_max__size=1024m \
    -e NEO4J_server_memory_pagecache_size=1500m \
    -e NEO4J_server_bolt_enabled=true \
    -e NEO4J_server_bolt_tls__level=REQUIRED \
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

echo "✅ Neo4j started successfully"
echo ""
echo "=========================================================="
echo "  Setup Complete! Connection Details:"
echo "=========================================================="
echo "  Bolt URI (TLS): neo4j+s://<YOUR_DROPLET_IP>:7687"
echo "  Browser Console: https://<YOUR_DROPLET_IP>:7473"
echo "  Username:        neo4j"
echo "  Password:        ${NEO4J_PASSWORD}"
echo "=========================================================="
echo ""
echo "Configure your backend .env with:"
echo "NEO4J_URI=neo4j+ssc://<YOUR_DROPLET_IP>:7687  (ssc accepts self-signed cert)"
echo "NEO4J_USER=neo4j"
echo "NEO4J_PASSWORD=${NEO4J_PASSWORD}"
echo "=========================================================="
