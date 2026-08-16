param(
    [int]$Port = 8501
)

function Find-AvailableTcpPort {
    param([int]$StartPort)
    for ($candidate = $StartPort; $candidate -le 65535; $candidate++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new(
                [System.Net.IPAddress]::Loopback,
                $candidate
            )
            $listener.Start()
            return $candidate
        } catch [System.Net.Sockets.SocketException] {
            Write-Host "Port $candidate is in use; trying $($candidate + 1)..."
        } finally {
            if ($null -ne $listener) { $listener.Stop() }
        }
    }
    throw "No available TCP port was found at or above $StartPort."
}

$pythonCandidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
    "python"
)
$pythonExe = $pythonCandidates | Where-Object {
    if ($_ -eq "python") { Get-Command python -ErrorAction SilentlyContinue } else { Test-Path $_ }
} | Select-Object -First 1
if (-not $pythonExe) { throw "Python 3.10+ was not found." }

$selectedPort = Find-AvailableTcpPort -StartPort $Port
Write-Host "Local URL: http://localhost:$selectedPort"
& $pythonExe -m streamlit run (Join-Path $PSScriptRoot "review_assets_app.py") `
    --server.address 127.0.0.1 `
    --server.port $selectedPort `
    --server.maxUploadSize 500 `
    --browser.gatherUsageStats false
