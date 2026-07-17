param(
    [string]$AppPath = (Join-Path $PSScriptRoot "app.py")
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
    throw "未找到可用的 Python 安装，请确认已安装 Python 3.10+。"
}

& $pythonExe -m streamlit run $AppPath
