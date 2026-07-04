#!/usr/bin/env bash
# =============================================================================
# VietLegalGraphRAG — GCP Neo4j VM Setup Script
# =============================================================================
# This script sets up a GCE VM with:
#   - Docker + Neo4j 5 Community (containerised)
#   - Self-signed TLS for bolt+s:// connections
#   - Strong authentication
#   - Firewall rules for bolt (7687) and HTTPS browser (7473)
#
# Prerequisites:
#   - gcloud CLI authenticated with a project that has Compute Engine enabled
#   - The neo4j_imports data uploaded to the VM (see upload step below)
#
# Usage:
#   1. Edit the variables below to match your GCP project
#   2. Run: bash setup_neo4j_gcp.sh
#   3. Upload CSV data: see STEP 2 instructions
#   4. Run import: see STEP 3 instructions
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — EDIT THESE
# ---------------------------------------------------------------------------
PROJECT_ID="${VM_PROJECT:-your-gcp-project-id}"
ZONE="${VM_ZONE:-asia-southeast1-b}"
INSTANCE_NAME="${VM_INSTANCE_ID:-neo4j-legal}"
MACHINE_TYPE="e2-standard-2"               # 2 vCPU, 8 GB RAM (recommended)
BOOT_DISK_SIZE="50GB"
BOOT_DISK_TYPE="pd-ssd"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-$(openssl rand -base64 24)}"
NEO4J_IMAGE="neo4j:5-community"
DOMAIN_OR_IP=""                             # Set if you have a domain for Let's Encrypt

# Firewall tag
NETWORK_TAG="neo4j-server"

echo "============================================"
echo "  VietLegalGraphRAG — Neo4j GCP VM Setup"
echo "============================================"
echo "Project:  ${PROJECT_ID}"
echo "Zone:     ${ZONE}"
echo "Instance: ${INSTANCE_NAME}"
echo "Machine:  ${MACHINE_TYPE}"
echo "Disk:     ${BOOT_DISK_SIZE} ${BOOT_DISK_TYPE}"
echo ""

# ---------------------------------------------------------------------------
# STEP 0: Create firewall rules (idempotent)
# ---------------------------------------------------------------------------
echo "=== STEP 0: Firewall rules ==="

# Allow bolt+s (7687) and Neo4j HTTPS browser (7473) from anywhere
gcloud compute firewall-rules describe allow-neo4j-bolt \
    --project="${PROJECT_ID}" &>/dev/null 2>&1 || \
gcloud compute firewall-rules create allow-neo4j-bolt \
    --project="${PROJECT_ID}" \
    --direction=INGRESS \
    --action=ALLOW \
    --rules=tcp:7687,tcp:7473 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${NETWORK_TAG}" \
    --description="Allow Neo4j bolt (TLS) and HTTPS browser"

echo "✅ Firewall rules configured"

# ---------------------------------------------------------------------------
# STEP 1: Create the VM
# ---------------------------------------------------------------------------
echo ""
echo "=== STEP 1: Create GCE VM ==="

# Check if instance already exists
if gcloud compute instances describe "${INSTANCE_NAME}" \
    --project="${PROJECT_ID}" --zone="${ZONE}" &>/dev/null 2>&1; then
    echo "Instance '${INSTANCE_NAME}' already exists. Skipping creation."
else
    gcloud compute instances create "${INSTANCE_NAME}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONE}" \
        --machine-type="${MACHINE_TYPE}" \
        --boot-disk-size="${BOOT_DISK_SIZE}" \
        --boot-disk-type="${BOOT_DISK_TYPE}" \
        --image-family=ubuntu-2404-lts-amd64 \
        --image-project=ubuntu-os-cloud \
        --tags="${NETWORK_TAG}" \
        --metadata=startup-script='#!/bin/bash
# Install Docker on first boot
if ! command -v docker &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq docker.io
    systemctl enable docker
    systemctl start docker
    # Add current user to docker group
    usermod -aG docker $(logname 2>/dev/null || echo ubuntu)
fi
'
    echo "✅ VM created: ${INSTANCE_NAME}"
    echo "   Waiting 30s for startup script..."
    sleep 30
fi

# Get external IP
EXTERNAL_IP=$(gcloud compute instances describe "${INSTANCE_NAME}" \
    --project="${PROJECT_ID}" --zone="${ZONE}" \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

echo "   External IP: ${EXTERNAL_IP}"

# ---------------------------------------------------------------------------
# STEP 2: Upload CSV data
# ---------------------------------------------------------------------------
echo ""
echo "=== STEP 2: Upload graph data ==="
echo ""
echo "Upload your CSV files to the VM with:"
echo ""
echo "  # Option A: Upload directory directly"
echo "  gcloud compute scp --recurse data/graph/ \\"
echo "      ${INSTANCE_NAME}:/tmp/neo4j_imports/ \\"
echo "      --project=${PROJECT_ID} --zone=${ZONE}"
echo ""
echo "  # Option B: Upload zip and extract"
echo "  gcloud compute scp neo4j_imports.zip \\"
echo "      ${INSTANCE_NAME}:/tmp/ \\"
echo "      --project=${PROJECT_ID} --zone=${ZONE}"
echo "  gcloud compute ssh ${INSTANCE_NAME} \\"
echo "      --project=${PROJECT_ID} --zone=${ZONE} \\"
echo "      --command='cd /tmp && unzip neo4j_imports.zip -d neo4j_imports'"
echo ""

# ---------------------------------------------------------------------------
# STEP 3: Generate TLS certificate + Neo4j setup script
# ---------------------------------------------------------------------------
echo "=== STEP 3: Generating remote setup script ==="

# Create setup script to run ON the VM
cat > /tmp/neo4j_remote_setup.sh << 'REMOTE_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

NEO4J_PASSWORD="${1:?Usage: $0 <neo4j_password>}"
IMPORT_DIR="${2:-/tmp/neo4j_imports}"
NEO4J_IMAGE="${3:-neo4j:5-community}"

CERT_DIR="/opt/neo4j-certs"
DATA_DIR="/opt/neo4j-data"

echo "=== Generating self-signed TLS certificate ==="
sudo mkdir -p "${CERT_DIR}" "${DATA_DIR}"

# Generate self-signed cert (valid 3 years)
sudo openssl req -x509 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/private.key" \
    -out "${CERT_DIR}/public.crt" \
    -days 1095 -nodes \
    -subj "/CN=neo4j-legal/O=VietLegalGraphRAG" \
    2>/dev/null

# Neo4j expects specific file structure for bolt TLS
sudo mkdir -p "${CERT_DIR}/bolt/trusted" "${CERT_DIR}/bolt/revoked"
sudo cp "${CERT_DIR}/private.key" "${CERT_DIR}/bolt/"
sudo cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/"
sudo cp "${CERT_DIR}/public.crt" "${CERT_DIR}/bolt/trusted/"

# Same for HTTPS connector
sudo mkdir -p "${CERT_DIR}/https/trusted" "${CERT_DIR}/https/revoked"
sudo cp "${CERT_DIR}/private.key" "${CERT_DIR}/https/"
sudo cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/"
sudo cp "${CERT_DIR}/public.crt" "${CERT_DIR}/https/trusted/"

# Fix permissions
sudo chown -R 7474:7474 "${CERT_DIR}"
sudo chmod 600 "${CERT_DIR}/bolt/private.key" "${CERT_DIR}/https/private.key"

echo "✅ TLS certificates generated"

# --- Stop existing container if running ---
docker stop neo4j-legal 2>/dev/null || true
docker rm neo4j-legal 2>/dev/null || true

# --- Run bulk import ---
echo "=== Running Neo4j bulk import ==="
if [ ! -d "${IMPORT_DIR}" ]; then
    echo "ERROR: Import directory not found: ${IMPORT_DIR}"
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

echo "✅ Bulk import completed"

# --- Start Neo4j with TLS ---
echo "=== Starting Neo4j with TLS ==="
docker run -d \
    --name neo4j-legal \
    --restart unless-stopped \
    -p 7687:7687 \
    -p 7473:7473 \
    -v "${DATA_DIR}:/data" \
    -v "${CERT_DIR}:/certificates" \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_memory_heap_initial__size=1536m \
    -e NEO4J_server_memory_heap_max__size=1536m \
    -e NEO4J_server_memory_pagecache_size=1536m \
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

echo "✅ Neo4j started with TLS"
echo ""
echo "=== Connection Info ==="
echo "  Bolt (TLS):   neo4j+s://$(hostname -I | awk '{print $1}'):7687"
echo "  Browser:      https://$(hostname -I | awk '{print $1}'):7473"
echo "  Username:     neo4j"
echo "  Password:     ${NEO4J_PASSWORD}"
echo ""
echo "  For .env:"
echo "  NEO4J_URI=neo4j+s://<EXTERNAL_IP>:7687"
echo "  NEO4J_USER=neo4j"
echo "  NEO4J_PASSWORD=${NEO4J_PASSWORD}"
REMOTE_SCRIPT

echo "✅ Setup script generated at /tmp/neo4j_remote_setup.sh"
echo ""
echo "=== Next steps ==="
echo ""
echo "1. Upload CSV data (see STEP 2 above)"
echo ""
echo "2. Upload and run the setup script:"
echo "   gcloud compute scp /tmp/neo4j_remote_setup.sh \\"
echo "       ${INSTANCE_NAME}:/tmp/ \\"
echo "       --project=${PROJECT_ID} --zone=${ZONE}"
echo ""
echo "   gcloud compute ssh ${INSTANCE_NAME} \\"
echo "       --project=${PROJECT_ID} --zone=${ZONE} \\"
echo "       --command='bash /tmp/neo4j_remote_setup.sh \"${NEO4J_PASSWORD}\"'"
echo ""
echo "3. Update your .env with:"
echo "   NEO4J_URI=neo4j+s://${EXTERNAL_IP}:7687"
echo "   NEO4J_USER=neo4j"
echo "   NEO4J_PASSWORD=${NEO4J_PASSWORD}"
echo "   VM_PROVIDER=gcp"
echo "   VM_INSTANCE_ID=${INSTANCE_NAME}"
echo "   VM_ZONE=${ZONE}"
echo "   VM_PROJECT=${PROJECT_ID}"
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
