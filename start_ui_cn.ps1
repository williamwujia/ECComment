param(
    [string]$AppPath = (Join-Path $PSScriptRoot "app.py"),
    [int]$Port = 8501
)

$candidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python310\python.exe"),
    "python"
)

$pythonExe = $candidates | Where-Object {
    if ($_ -eq "python") {
        Get-Command python -ErrorAction SilentlyContinue
    } else {
        Test-Path $_
    }
} | Select-Object -First 1

if (-not $pythonExe) {
    throw "Python 3.10+ was not found. Please install Python first."
}

$localIp = (
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress -First 1
)

if ($localIp) {
    Write-Host "Client URL: http://$localIp`:$Port"
}
Write-Host "Local URL: http://localhost:$Port"

& $pythonExe -m streamlit run $AppPath `
    --server.address 0.0.0.0 `
    --server.port $Port `
    --browser.gatherUsageStats false
