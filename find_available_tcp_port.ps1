[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$StartPort = 8501
)

for ($candidate = $StartPort; $candidate -le 65535; $candidate++) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Any,
            $candidate
        )
        $listener.Start()
        Write-Output $candidate
        return
    } catch [System.Net.Sockets.SocketException] {
        [Console]::Error.WriteLine("Port $candidate is in use; trying $($candidate + 1)...")
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

throw "No available TCP port was found at or above $StartPort."
