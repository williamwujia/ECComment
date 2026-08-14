param(
    [string]$AppPath = (Join-Path $PSScriptRoot "app.py"),
    [int]$Port = 8501
)

$candidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python310\python.exe")
)

$pythonExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExe) {
    throw "Python 3.10+ was not found. Please install Python first."
}

$selectedPort = & (Join-Path $PSScriptRoot "find_available_tcp_port.ps1") -StartPort $Port
Write-Host "Local URL: http://localhost:$selectedPort"
& $pythonExe -m streamlit run $AppPath --server.port $selectedPort
