param(
    [string]$InputDir = (Join-Path $PSScriptRoot "input_html"),
    [string]$OutputDir = (Join-Path $PSScriptRoot "output"),
    [string]$RunName = "",
    [int]$Port = 8501,
    [switch]$Recursive
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python310\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "Python 3.10+ was not found."
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$pythonExe = Find-Python
Write-Host "Using Python: $pythonExe" -ForegroundColor Green

Invoke-Step "Check dependencies" {
    & $pythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
}

$mainArgs = @(
    (Join-Path $PSScriptRoot "main.py"),
    "--input", $InputDir,
    "--output", $OutputDir,
    "--keywords", (Join-Path $PSScriptRoot "config\ai_keywords.yaml")
)
if ($RunName.Trim()) {
    $mainArgs += @("--run-name", $RunName)
}
if ($Recursive) {
    $mainArgs += "--recursive"
}

Invoke-Step "Extract new HTML files" {
    & $pythonExe @mainArgs
}

Write-Host ""
Write-Host "Extraction finished. Starting Streamlit review UI..." -ForegroundColor Green
Write-Host "Closing this window will stop the UI server." -ForegroundColor Yellow
$selectedPort = & (Join-Path $PSScriptRoot "find_available_tcp_port.ps1") -StartPort $Port
Write-Host "Local URL: http://localhost:$selectedPort" -ForegroundColor Green
& $pythonExe -m streamlit run (Join-Path $PSScriptRoot "app.py") --server.port $selectedPort
