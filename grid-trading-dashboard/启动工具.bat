@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [首次运行] 正在创建本地环境，请稍候...
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

echo 正在启动网格交易收益仪表盘...
".venv\Scripts\python.exe" app.py
goto :end

:failed
echo.
echo 启动失败，请检查网络连接和 Python 3.11 是否已安装。
pause

:end
