param(
    [string]$PythonExe = ""
)

if (-not $PythonExe) {
    $candidates = @(
        (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python310\python.exe"),
        "python"
    )
    $PythonExe = $candidates | Where-Object {
        if ($_ -eq "python") {
            Get-Command python -ErrorAction SilentlyContinue
        } else {
            Test-Path $_
        }
    } | Select-Object -First 1
}

if (-not $PythonExe) {
    throw "Python 3.10+ was not found. Please install Python first."
}

& $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") -i https://pypi.tuna.tsinghua.edu.cn/simple
