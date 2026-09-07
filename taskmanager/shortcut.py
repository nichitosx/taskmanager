"""Ярлыки Windows: на рабочий стол, в меню «Пуск» и в папку программы.

Чтобы запускать программу не через run.py, а обычным двойным кликом по значку.
Права администратора не нужны — пишем только в профиль пользователя, а сам .lnk
создаётся внутри процесса через COM (см. winshell), без запуска PowerShell.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import winshell
from .appicon import write_ico
from .config import app_dir, data_dir

desktop_dir = winshell.desktop_dir
start_menu_dir = winshell.start_menu_dir

SHORTCUT_NAME = "TaskManager.lnk"

DESKTOP = "desktop"
START_MENU = "startmenu"
APP_FOLDER = "folder"


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


def target_dir(kind: str) -> Path:
    """Куда класть ярлык: рабочий стол, меню «Пуск» или папка самой программы."""
    if kind == START_MENU:
        return start_menu_dir()
    if kind == APP_FOLDER:
        return app_dir()
    return desktop_dir()


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

    created = winshell.create_shortcut(
        path,
        executable,
        arguments,
        str(app_dir()),
        str(icon) if icon and str(icon) else "",
        "TaskManager — трекер рабочих задач",
    )
    if not created:
        raise OSError("не удалось создать ярлык")
    return path


def remove(kind: str = DESKTOP) -> None:
    path = target_dir(kind) / SHORTCUT_NAME
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
