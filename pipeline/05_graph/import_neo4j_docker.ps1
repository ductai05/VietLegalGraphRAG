# import_neo4j_docker.ps1
# Automates importing Vietnamese Legal GraphRAG CSVs into Neo4j via Docker.
# Author: Antigravity

$ErrorActionPreference = "Stop"

Write-Host "=== 🔍 STEP 1: Checking Docker Status ===" -ForegroundColor Cyan
try {
    # Check if docker command exists
    $null = Get-Command docker -ErrorAction Stop
} catch {
    Write-Host "[ERROR] Docker is not installed or not in the PATH. Please install Docker Desktop first." -ForegroundColor Red
    Exit 1
}

# Check if Docker daemon is running
$dockerCheck = & docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker daemon is not running." -ForegroundColor Red
    Write-Host "👉 Please launch Docker Desktop on your machine, wait for it to start, and run this script again." -ForegroundColor Yellow
    Exit 1
}
Write-Host "✅ Docker daemon is running successfully." -ForegroundColor Green


Write-Host "`n=== 🧹 STEP 2: Cleaning old Neo4j Containers ===" -ForegroundColor Cyan
$existingContainer = & docker ps -a --filter "name=neo4j-legal" --format "{{.Names}}"
if ($existingContainer -eq "neo4j-legal") {
    Write-Host "Found existing container 'neo4j-legal'. Stopping and removing it..." -ForegroundColor Yellow
    & docker stop neo4j-legal | Out-Null
    & docker rm neo4j-legal | Out-Null
    Write-Host "✅ Old container removed." -ForegroundColor Green
} else {
    Write-Host "No conflicting container found." -ForegroundColor Gray
}


Write-Host "`n=== 🚀 STEP 3: Running Neo4j Bulk Import ===" -ForegroundColor Cyan
# Resolve absolute paths
$WorkspaceDir = (Get-Item .).FullName
$ImportDir = Join-Path $WorkspaceDir "data\processed\neo4j_imports"

if (-not (Test-Path $ImportDir)) {
    Write-Host "[ERROR] Import folder not found at: $ImportDir" -ForegroundColor Red
    Write-Host "👉 Make sure you have extracted neo4j_imports.zip to data/processed/neo4j_imports." -ForegroundColor Yellow
    Exit 1
}

Write-Host "Source Import Directory: $ImportDir" -ForegroundColor Gray
Write-Host "Executing bulk-import tool inside temporary Neo4j container. Please wait (this may take a few minutes)..." -ForegroundColor Yellow

# Perform the bulk import using a temporary docker container with volume mounts
& docker run --rm `
  -v "${ImportDir}:/import" `
  -v "neo4j_legal_data:/data" `
  -v "neo4j_legal_backups:/backups" `
  neo4j:latest `
  neo4j-admin database import full `
    --nodes=Document=/import/documents.csv `
    --nodes=Article=/import/articles.csv `
    --nodes=LegalType=/import/legal_types.csv `
    --nodes=Authority=/import/authorities.csv `
    --nodes=Sector=/import/sectors.csv `
    --relationships=/import/doc_doc_edges.csv `
    --relationships=/import/doc_art_edges.csv `
    --relationships=/import/art_art_next_edges.csv `
    --relationships=/import/art_art_parent_edges.csv `
    --relationships=/import/doc_type_edges.csv `
    --relationships=/import/doc_auth_edges.csv `
    --relationships=/import/doc_sector_edges.csv `
    --overwrite-destination=true `
    neo4j

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Bulk import failed!" -ForegroundColor Red
    Exit 1
}
Write-Host "✅ Bulk import completed successfully!" -ForegroundColor Green


Write-Host "`n=== 🌟 STEP 4: Launching Neo4j Server Container ===" -ForegroundColor Cyan
Write-Host "Starting persistent Neo4j container 'neo4j-legal'..." -ForegroundColor Yellow

& docker run -d `
  --name neo4j-legal `
  -p 7474:7474 -p 7687:7687 `
  -v "neo4j_legal_data:/data" `
  -v "neo4j_legal_backups:/backups" `
  -e NEO4J_AUTH=neo4j/password123 `
  neo4j:latest

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to start Neo4j server container!" -ForegroundColor Red
    Exit 1
}

Write-Host "`n🚀 =================================================== 🚀" -ForegroundColor Green
Write-Host "  Hệ thống Đồ thị Tri thức đã khởi chạy thành công!" -ForegroundColor Green
Write-Host "🚀 =================================================== 🚀`n" -ForegroundColor Green
Write-Host "Thông tin kết nối cơ sở dữ liệu:" -ForegroundColor Cyan
Write-Host "🔗 Web Browser: http://localhost:7474" -ForegroundColor Yellow
Write-Host "🔑 Username:    neo4j" -ForegroundColor Yellow
Write-Host "🔒 Password:    password123" -ForegroundColor Yellow
Write-Host "⚡ Connection:  bolt://localhost:7687" -ForegroundColor Yellow
Write-Host "`n👉 Bạn có thể mở trình duyệt, truy cập địa chỉ trên để xem và truy vấn đồ thị." -ForegroundColor Gray
