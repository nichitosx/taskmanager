"""Первый запуск на новом компьютере: зависимости, ярлыки, старт.

Запускается один раз после распаковки архива — обычно через «Установить.cmd»,
но можно и напрямую: ``python install.py``. Права администратора не нужны:
библиотека ставится в профиль пользователя (``pip install --user``), ярлыки
кладутся на рабочий стол и рядом с программой, данные живут в %APPDATA%.

Ничего не «устанавливает» в системном смысле: ни служб, ни записей в реестр, ни
файлов вне профиля. Удаление — просто удалить папку и ярлыки.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)


def say(text: str = "") -> None:
    print(text, flush=True)


def check_python() -> bool:
    if sys.version_info >= MIN_PYTHON:
        return True
    say("Нужен Python %d.%d или новее, а сейчас %d.%d." % (
        MIN_PYTHON[0], MIN_PYTHON[1], sys.version_info[0], sys.version_info[1]
    ))
    say("Скачайте с python.org и поставьте, отметив «Add python.exe to PATH».")
    return False


def has_pyside() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def install_pyside() -> bool:
    """Ставит PySide6 в профиль пользователя."""
    say("Ставлю библиотеку интерфейса PySide6 (несколько минут, ~100 МБ)…")
    command = [
        sys.executable, "-m", "pip", "install", "--user",
        "-r", str(APP_DIR / "requirements.txt"),
    ]
    try:
        result = subprocess.run(command)
    except OSError as exc:
        say("Не удалось запустить pip: %s" % exc)
        return False
    if result.returncode != 0:
        say("")
        say("pip завершился с ошибкой. Если в компании закрыт доступ к интернету,")
        say("попросите коллег принести файл PySide6 и поставьте его командой:")
        say("    python -m pip install --user путь-к-файлу.whl")
        return False
    return has_pyside()


def make_shortcuts() -> list[Path]:
    """Создаёт ярлыки на рабочем столе и в папке программы."""
    sys.path.insert(0, str(APP_DIR))
    from PySide6.QtGui import QGuiApplication  # иконка рисуется средствами Qt

    from taskmanager import shortcut

    application = QGuiApplication.instance() or QGuiApplication([])
    created: list[Path] = []
    for kind in (shortcut.DESKTOP, shortcut.APP_FOLDER):
        try:
            created.append(shortcut.create(kind))
        except OSError as exc:
            say("Ярлык (%s) создать не удалось: %s" % (kind, exc))
    del application
    return created


def launch() -> None:
    """Запускает программу без окна консоли."""
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else interpreter)
    subprocess.Popen([executable, str(APP_DIR / "run.py")], cwd=str(APP_DIR))


def main() -> int:
    say("TaskManager — подготовка к работе")
    say("Папка программы: %s" % APP_DIR)
    say()

    if not check_python():
        return 1

    if has_pyside():
        say("Библиотека интерфейса уже стоит.")
    elif not install_pyside():
        return 1
    else:
        say("Библиотека установлена.")

    say()
    for path in make_shortcuts():
        say("Ярлык: %s" % path)

    from taskmanager.config import data_dir

    say()
    say("Задачи и настройки будут храниться здесь:")
    say("    %s" % data_dir())
    say()
    say("Всё готово. Запускать можно ярлыком «TaskManager».")

    answer = input("Запустить сейчас? [Enter — да, n — нет]: ").strip().lower()
    if answer in ("", "y", "д", "да"):
        launch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
