<#
.SYNOPSIS
    Runs the full setup script to get environment up and running.
#>
param(
    [string]$envName = "vlegal_env",
    [string]$pythonVersion = "3.12"
)

Write-Host "Starting setup..." -ForegroundColor Green
.\scripts\setup_env.ps1 -envName $envName -pythonVersion $pythonVersion

