@echo off
title TaskManager - установка
cd /d "%~dp0"

echo.
echo   TaskManager - подготовка к работе
echo   --------------------------------
echo.

rem Ищем Python: сначала лаунчер py, потом python из PATH.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo   Python не найден.
    echo.
    echo   Скачайте его с https://www.python.org/downloads/
    echo   и при установке отметьте "Add python.exe to PATH".
    echo   Потом запустите этот файл ещё раз.
    echo.
    pause
    exit /b 1
)

%PY% install.py
if errorlevel 1 (
    echo.
    echo   Что-то пошло не так - смотрите сообщение выше.
    pause
    exit /b 1
)
exit /b 0
