@echo off
title TaskManager - обновление
cd /d "%~dp0"

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo   Python не найден. Сначала запустите "Установить.cmd".
    pause
    exit /b 1
)

%PY% update.py %*
