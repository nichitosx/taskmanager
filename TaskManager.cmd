@echo off
cd /d "%~dp0"

rem pythonw запускает программу без окна консоли.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=pyw -3"
if not defined PY pythonw -c "import sys" >nul 2>&1 && set "PY=pythonw"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo Python не найден. Запустите "Установить.cmd".
    pause
    exit /b 1
)

start "" %PY% "%~dp0run.py" %*
