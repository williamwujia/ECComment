param(
    [string]$AppPath = (Join-Path $PSScriptRoot "app.py"),
    [int]$Port = 8501
)

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

$selectedPort = Find-AvailableTcpPort -StartPort $Port

$localIp = (
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress -First 1
)

if ($localIp) {
    Write-Host "Client URL: http://$localIp`:$selectedPort"
}
Write-Host "Local URL: http://localhost:$selectedPort"

& $pythonExe -m streamlit run $AppPath `
    --server.address 0.0.0.0 `
    --server.port $selectedPort `
    --browser.gatherUsageStats false
