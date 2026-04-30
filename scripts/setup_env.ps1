<#
.SYNOPSIS
    Setup virtual environment (conda or venv) and install dependencies for VietLegalGraphRAG.
#>
param(
    [string]$envName = "vlegal_env",
    [string]$pythonVersion = "3.12"
)

Write-Host "Setting up environment for VietLegalGraphRAG..." -ForegroundColor Cyan

# Check for conda
$condaPath = Get-Command "conda" -ErrorAction SilentlyContinue

if ($condaPath) {
    Write-Host "Found Conda. Proceeding to create environment '$envName' with Python $pythonVersion." -ForegroundColor Yellow
    cmd.exe /c "conda create -n $envName python=$pythonVersion -y"
    Write-Host "Conda environment created. To activate run: 'conda activate $envName'." -ForegroundColor Green

    # We cannot activate easily and run pip in powershell script directly correctly,
    # so we'll use conda run
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    cmd.exe /c "conda run -n $envName pip install -r requirements.txt"
    cmd.exe /c "conda run -n $envName pip install huggingface_hub"

    Write-Host "Running download data script..." -ForegroundColor Yellow
    cmd.exe /c "conda run -n $envName python scripts\download_data.py"

} else {
    Write-Host "Conda not found. Attempting to create Python venv..." -ForegroundColor Yellow

    python -m venv venv

    if ($?) {
        Write-Host "Venv created successfully." -ForegroundColor Green

        Write-Host "Installing dependencies..." -ForegroundColor Yellow
        .\venv\Scripts\pip install -r requirements.txt
        .\venv\Scripts\pip install huggingface_hub

        Write-Host "Running download data script..." -ForegroundColor Yellow
        .\venv\Scripts\python scripts\download_data.py
    } else {
        Write-Host "Failed to create environment. Please install Python or Conda manually." -ForegroundColor Red
        Exit 1
    }
}

Write-Host "Setup Completed! You can activate environment and run main.py." -ForegroundColor Cyan

