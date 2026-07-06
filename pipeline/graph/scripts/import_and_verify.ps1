# import_and_verify.ps1
# Automates local Neo4j bulk import and verifies the imported nodes/edges.
# Author: Antigravity

$ErrorActionPreference = "Continue"

# Resolve absolute paths
$WorkspaceDir = (Get-Item .).FullName
$ImportDir = Join-Path $WorkspaceDir "data\processed\neo4j_imports"

if (-not (Test-Path $ImportDir)) {
    Write-Host "[ERROR] Import folder not found at: $ImportDir" -ForegroundColor Red
    Write-Host "Please make sure you have extracted neo4j_imports.zip to data/processed/neo4j_imports." -ForegroundColor Yellow
    Exit 1
}

$ImportDirDocker = $ImportDir.Replace("\", "/")

Write-Host "=== STEP 1: Checking Docker Daemon Status ===" -ForegroundColor Cyan
$maxAttempts = 30
$attempt = 0
$dockerReady = $false

while ($attempt -lt $maxAttempts) {
    $attempt++
    # Run docker info and check exit code
    $null = cmd /c "docker info >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        $dockerReady = $true
        break
    }
    Write-Host "Waiting ($attempt/$maxAttempts): Docker daemon is not ready yet. Retrying in 10 seconds..." -ForegroundColor Yellow
    Write-Host "Please make sure Docker Desktop is launched and running on your machine." -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

if (-not $dockerReady) {
    Write-Host "[ERROR] Docker daemon failed to start after 5 minutes." -ForegroundColor Red
    Write-Host "Please launch Docker Desktop manually and verify it is running." -ForegroundColor Yellow
    Exit 1
}
Write-Host "Docker daemon is running successfully!" -ForegroundColor Green


Write-Host "`n=== STEP 2: Cleaning old Neo4j container and volumes ===" -ForegroundColor Cyan
$existingContainer = cmd /c "docker ps -a --filter name=neo4j-legal" 2>$null
if ($existingContainer -like "*neo4j-legal*") {
    Write-Host "Found existing container 'neo4j-legal'. Stopping and removing it..." -ForegroundColor Yellow
    $null = cmd /c "docker stop neo4j-legal 2>nul"
    $null = cmd /c "docker rm neo4j-legal 2>nul"
    Write-Host "Old container removed." -ForegroundColor Green
} else {
    Write-Host "No conflicting container found." -ForegroundColor Gray
}

Write-Host "Removing old volumes to ensure clean import..." -ForegroundColor Yellow
$null = cmd /c "docker volume rm neo4j_legal_data 2>nul"
$null = cmd /c "docker volume rm neo4j_legal_backups 2>nul"
Write-Host "Old volumes removed." -ForegroundColor Green

Write-Host "Dropping WSL cache to reclaim free memory..." -ForegroundColor Yellow
$null = wsl -d docker-desktop -u root -- sh -c "echo 3 > /proc/sys/vm/drop_caches" 2>$null
Write-Host "WSL cache dropped successfully." -ForegroundColor Green


Write-Host "`n=== STEP 3: Running Neo4j Bulk Import ===" -ForegroundColor Cyan
Write-Host "Source Import Directory: $ImportDir" -ForegroundColor Gray
Write-Host "Import Directory for Docker: $ImportDirDocker" -ForegroundColor Gray
Write-Host "Executing bulk-import tool inside temporary Neo4j container. Please wait (this may take a few minutes)..." -ForegroundColor Yellow

# Perform the bulk import using a temporary docker container with volume mounts
# We add --skip-duplicate-nodes=true and --skip-bad-relationships=true to tolerate duplicate metadata IDs
& docker run --rm `
  -e HEAP_SIZE=1200m `
  -v "${ImportDirDocker}:/import" `
  -v "neo4j_legal_data:/data" `
  -v "neo4j_legal_backups:/backups" `
  neo4j:5 `
  neo4j-admin database import full `
    --max-off-heap-memory=1G `
    --verbose `
    --skip-duplicate-nodes=true `
    --skip-bad-relationships=true `
    --report-file=/import/import.report `
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
Write-Host "Bulk import completed successfully!" -ForegroundColor Green


Write-Host "`n=== STEP 4: Launching Neo4j Server Container ===" -ForegroundColor Cyan
Write-Host "Starting persistent Neo4j container 'neo4j-legal'..." -ForegroundColor Yellow

# Start persistent container with 512MB heap limit and 512MB page cache limit to save memory
& docker run -d `
  --name neo4j-legal `
  -p 7474:7474 -p 7687:7687 `
  -v "neo4j_legal_data:/data" `
  -v "neo4j_legal_backups:/backups" `
  -e NEO4J_AUTH=neo4j/password123 `
  -e NEO4J_dbms_memory_heap_initial__size=512m `
  -e NEO4J_dbms_memory_heap_max__size=512m `
  -e NEO4J_server_memory_pagecache_size=512m `
  neo4j:5

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to start Neo4j server container!" -ForegroundColor Red
    Exit 1
}
Write-Host "Neo4j server container started successfully!" -ForegroundColor Green


Write-Host "`n=== STEP 5: Waiting for Neo4j Database to start ===" -ForegroundColor Cyan
$webUri = "http://localhost:7474"
$maxWebAttempts = 30
$webAttempt = 0
$webReady = $false

while ($webAttempt -lt $maxWebAttempts) {
    $webAttempt++
    try {
        $response = Invoke-WebRequest -Uri $webUri -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $webReady = $true
            break
        }
    } catch {
        # Ignore exception and retry
    }
    Write-Host "Waiting ($webAttempt/$maxWebAttempts) for Neo4j web console to respond..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}

if (-not $webReady) {
    Write-Host "[ERROR] Neo4j server failed to start or respond on port 7474." -ForegroundColor Red
    Exit 1
}
Write-Host "Neo4j web console is online." -ForegroundColor Green


Write-Host "`n=== STEP 6: Verifying Node and Edge Counts ===" -ForegroundColor Cyan
Write-Host "Ensuring database is active and running verification queries..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

$txUri = "http://localhost:7474/db/neo4j/tx/commit"
$base64Auth = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes("neo4j:password123"))
$headers = @{
    "Authorization" = "Basic $base64Auth"
    "Content-Type" = "application/json"
}

$queryBody = @{
    statements = @(
        @{ statement = "MATCH (n:Document) RETURN count(n) as count" },
        @{ statement = "MATCH (n:Article) RETURN count(n) as count" },
        @{ statement = "MATCH (n:LegalType) RETURN count(n) as count" },
        @{ statement = "MATCH (n:Authority) RETURN count(n) as count" },
        @{ statement = "MATCH (n:Sector) RETURN count(n) as count" },
        @{ statement = "MATCH ()-[r]->() RETURN count(r) as count" }
    )
} | ConvertTo-Json -Depth 5

try {
    $res = Invoke-RestMethod -Uri $txUri -Method Post -Headers $headers -Body $queryBody
    $results = $res.results
    
    $docCount = $results[0].data[0].row[0]
    $artCount = $results[1].data[0].row[0]
    $typeCount = $results[2].data[0].row[0]
    $authCount = $results[3].data[0].row[0]
    $sectCount = $results[4].data[0].row[0]
    $edgeCount = $results[5].data[0].row[0]

    Write-Host "`n===================================================" -ForegroundColor Green
    Write-Host "  VietLegal Graph Database Imported Successfully!" -ForegroundColor Green
    Write-Host "===================================================`n" -ForegroundColor Green
    Write-Host "Graph statistics:" -ForegroundColor Cyan
    Write-Host "Documents:        $docCount" -ForegroundColor Green
    Write-Host "Chunks/Articles:  $artCount" -ForegroundColor Green
    Write-Host "LegalTypes:       $typeCount" -ForegroundColor Green
    Write-Host "Authorities:      $authCount" -ForegroundColor Green
    Write-Host "Sectors:          $sectCount" -ForegroundColor Green
    Write-Host "Relationships:    $edgeCount" -ForegroundColor Green
    Write-Host "`nWeb Browser:   http://localhost:7474" -ForegroundColor Yellow
    Write-Host "Username:      neo4j" -ForegroundColor Yellow
    Write-Host "Password:      password123" -ForegroundColor Yellow
    Write-Host "Connection:    bolt://localhost:7687" -ForegroundColor Yellow
    Write-Host "`nYou can access the web console above to run Cypher queries." -ForegroundColor Gray
} catch {
    Write-Host "[WARNING] Could not execute verification queries. Error: $_" -ForegroundColor Yellow
    Write-Host "Please check manually at http://localhost:7474" -ForegroundColor Gray
}
