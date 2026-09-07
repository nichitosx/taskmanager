"""Автозапуск при входе в Windows — через ярлык в папке «Автозагрузка».

Права администратора не нужны: пишем только в профиль пользователя.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import winshell
from .config import app_dir

SHORTCUT_NAME = "TaskManager.lnk"
FALLBACK_NAME = "TaskManager.cmd"


startup_dir = winshell.startup_dir


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
    """Создаёт .lnk через COM. False, если не получилось."""
    from .shortcut import icon_path

    icon = icon_path()
    return winshell.create_shortcut(
        path,
        executable,
        arguments,
        str(app_dir()),
        str(icon) if icon and str(icon) else "",
        "TaskManager — трекер рабочих задач",
    )


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
