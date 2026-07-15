@echo off
setlocal
cd /d "%~dp0"

python -c "import akshare, bs4, dateutil, requests" >nul 2>nul
if errorlevel 1 (
  echo Installing local dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)

start "Grid Strategy Local Service" /min python server.py
powershell -NoProfile -Command "$url='http://127.0.0.1:52341/'; for($i=0; $i -lt 30; $i++){ try { Invoke-WebRequest $url -UseBasicParsing | Out-Null; Start-Process $url; exit 0 } catch { Start-Sleep -Milliseconds 300 } }; Write-Error 'Local service did not start'; exit 1"
exit /b %errorlevel%
