@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"

if not exist "output" mkdir "output"
set "LOG=%~dp0output\launcher.log"
set "PYTHON="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo [%date% %time%] Starting launcher > "%LOG%"
echo.
echo Starting extractor and review UI.
echo Launcher log: %LOG%
echo Pipeline log: output\run.log
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
  set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
) else if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
) else if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
  set "PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
) else if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
  set "PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe"
)

if not defined PYTHON (
  echo Python 3.10+ was not found. >> "%LOG%"
  echo.
  echo Python 3.10+ was not found.
  echo Please install Python or restore the project .venv folder.
  echo.
  pause
  exit /b 1
)

echo Using Python: "%PYTHON%" >> "%LOG%"
"%PYTHON%" --version >> "%LOG%" 2>&1

echo [1/3] Checking dependencies...
echo Checking dependencies... >> "%LOG%"
"%PYTHON%" -c "import bs4,lxml,pandas,openpyxl,yaml,tqdm,streamlit,plotly" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Installing dependencies... >> "%LOG%"
  echo Installing missing dependencies. This may take a while.
  "%PYTHON%" -m pip install -r "%~dp0requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/ --timeout 120 --retries 5 >> "%LOG%" 2>&1
  if errorlevel 1 goto fail
)

echo.
echo [2/3] Extracting HTML and running full sentiment LLM.
echo This can take several minutes. Progress will be shown below.
echo Extracting HTML files and running full sentiment LLM... >> "%LOG%"

if "%SKIP_SENTIMENT%"=="1" (
  echo SKIP_SENTIMENT=1; sentiment LLM is disabled for this run. >> "%LOG%"
  "%PYTHON%" "%~dp0main.py" --input "%~dp0input_html" --output "%~dp0output\ai_related_reviews.xlsx" --keywords "%~dp0config\ai_keywords.yaml" --no-enable-sentiment
) else (
  "%PYTHON%" "%~dp0main.py" --input "%~dp0input_html" --output "%~dp0output\ai_related_reviews.xlsx" --keywords "%~dp0config\ai_keywords.yaml" --sentiment-limit all --detail-limit all
)
if errorlevel 1 goto fail

echo.
echo [3/3] Starting review UI...
echo Starting review UI... >> "%LOG%"
set "PORT="
for /f "usebackq delims=" %%P in (`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$p=8501; while($p -le 65535) { $l=$null; try { $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch [Net.Sockets.SocketException] { if($null -ne $l){$l.Stop()}; $p++ } }; if($p -gt 65535){exit 1}"`) do set "PORT=%%P"
if not defined PORT (
  echo No available TCP port was found at or above 8501. >> "%LOG%"
  goto fail
)
echo Review UI port: %PORT% >> "%LOG%"
echo Review UI URL: http://localhost:%PORT%
start "" "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:%PORT%'"
"%PYTHON%" -m streamlit run "%~dp0app.py" --server.port %PORT% --server.address localhost
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" goto fail
exit /b 0

:fail
echo.
echo Launcher failed. See logs:
echo "%LOG%"
echo "%~dp0output\run.log"
echo.
type "%LOG%"
echo.
pause
exit /b 1
