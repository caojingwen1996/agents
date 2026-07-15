@echo off
setlocal
cd /d "%~dp0"

python -c "import akshare, bs4, dateutil, requests" >nul 2>nul
if errorlevel 1 (
  echo Installing local dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)

start "Grid Strategy Local Service" /min python server.py --open-browser
exit /b 0
