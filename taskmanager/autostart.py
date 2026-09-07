"""Автозапуск при входе в Windows — через ярлык в папке «Автозагрузка».

Права администратора не нужны: пишем только в профиль пользователя.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import app_dir

SHORTCUT_NAME = "TaskManager.lnk"
FALLBACK_NAME = "TaskManager.cmd"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / "Startup"
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _launch_target() -> tuple[str, str]:
    """Возвращает (исполняемый файл, аргументы) для запуска приложения."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--tray"
    # pythonw.exe запускает приложение без окна консоли.
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else interpreter)
    return executable, '"%s" --tray' % (app_dir() / "run.py")


def is_enabled() -> bool:
    return (startup_dir() / SHORTCUT_NAME).exists() or (startup_dir() / FALLBACK_NAME).exists()


def _create_shortcut(path: Path, executable: str, arguments: str) -> bool:
    """Создаёт .lnk через WScript.Shell. False, если не получилось."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.WindowStyle = 7;"
        "$s.Description = 'TaskManager — трекер рабочих задач';"
        "$s.Save()"
    ) % (path, executable, arguments.replace("'", "''"), app_dir())
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=25,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and path.exists()


def _create_cmd(path: Path, executable: str, arguments: str) -> None:
    """Запасной вариант, если PowerShell недоступен."""
    body = '@echo off\r\nstart "" "%s" %s\r\n' % (executable, arguments)
    path.write_text(body, encoding="utf-8")


def enable() -> Path:
    """Включает автозапуск и возвращает путь к созданному файлу."""
    folder = startup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    executable, arguments = _launch_target()
    shortcut = folder / SHORTCUT_NAME
    if _create_shortcut(shortcut, executable, arguments):
        return shortcut
    fallback = folder / FALLBACK_NAME
    _create_cmd(fallback, executable, arguments)
    return fallback


def disable() -> None:
    for name in (SHORTCUT_NAME, FALLBACK_NAME):
        path = startup_dir() / name
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def apply(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
