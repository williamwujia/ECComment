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

function Find-AvailableTcpPort {
    param([int]$StartPort)

    if ($StartPort -lt 1 -or $StartPort -gt 65535) {
        throw "Port must be between 1 and 65535."
    }

    for ($candidate = $StartPort; $candidate -le 65535; $candidate++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new(
                [System.Net.IPAddress]::Any,
                $candidate
            )
            $listener.Start()
            return $candidate
        } catch [System.Net.Sockets.SocketException] {
            Write-Host "Port $candidate is in use; trying $($candidate + 1)..."
        } finally {
            if ($null -ne $listener) {
                $listener.Stop()
            }
        }
    }

    throw "No available TCP port was found at or above $StartPort."
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
$selectedPort = Find-AvailableTcpPort -StartPort $Port
Write-Host "Local URL: http://localhost:$selectedPort" -ForegroundColor Green
& $pythonExe -m streamlit run (Join-Path $PSScriptRoot "app.py") --server.port $selectedPort
