"""Ярлыки Windows: на рабочий стол и в меню «Пуск».

Чтобы запускать программу не через run.py, а обычным двойным кликом по значку.
Права администратора не нужны — пишем только в профиль пользователя.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .appicon import write_ico
from .config import app_dir, data_dir

SHORTCUT_NAME = "TaskManager.lnk"

DESKTOP = "desktop"
START_MENU = "startmenu"


# Номер версии иконки в имени файла: Windows кеширует значки по пути, и без
# смены имени обновлённая иконка на старом ярлыке не появится.
ICON_VERSION = 2


def icon_path() -> Path:
    """Путь к .ico рядом с данными. Файл создаётся при первом обращении."""
    path = data_dir() / ("TaskManager-%d.ico" % ICON_VERSION)
    if path.exists():
        return path
    try:
        write_ico(path)
    except Exception:  # без иконки ярлык всё равно рабочий
        return Path()
    for stale in data_dir().glob("TaskManager*.ico"):
        if stale != path:
            try:
                stale.unlink()
            except OSError:
                pass
    return path


def _powershell(script: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def desktop_dir() -> Path:
    """Рабочий стол пользователя с учётом переезда в OneDrive."""
    result = _powershell("[Environment]::GetFolderPath('Desktop')")
    if result is not None and result.returncode == 0:
        path = Path(result.stdout.strip())
        if path.is_dir():
            return path
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Desktop"


def start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def target_dir(kind: str) -> Path:
    return start_menu_dir() if kind == START_MENU else desktop_dir()


def launch_target() -> tuple[str, str]:
    """(исполняемый файл, аргументы) для запуска приложения без окна консоли."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else interpreter)
    return executable, '"%s"' % (app_dir() / "run.py")


def exists(kind: str = DESKTOP) -> bool:
    return (target_dir(kind) / SHORTCUT_NAME).exists()


def create(kind: str = DESKTOP) -> Path:
    """Создаёт ярлык и возвращает путь к нему. Бросает OSError при неудаче."""
    folder = target_dir(kind)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SHORTCUT_NAME
    executable, arguments = launch_target()
    icon = icon_path()

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.Description = 'TaskManager — трекер рабочих задач';"
        "%s"
        "$s.Save()"
    ) % (
        path,
        executable,
        arguments.replace("'", "''"),
        app_dir(),
        ("$s.IconLocation = '%s';" % icon) if icon and str(icon) else "",
    )
    result = _powershell(script)
    if result is None or result.returncode != 0 or not path.exists():
        detail = (result.stderr.strip() if result is not None else "PowerShell недоступен")
        raise OSError(detail or "не удалось создать ярлык")
    return path


def remove(kind: str = DESKTOP) -> None:
    path = target_dir(kind) / SHORTCUT_NAME
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
