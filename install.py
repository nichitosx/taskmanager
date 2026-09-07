"""Первый запуск на новом компьютере: зависимости, ярлыки, старт.

Запускается один раз после распаковки архива — обычно через «Установить.cmd»,
но можно и напрямую: ``python install.py``. Права администратора не нужны:
библиотека ставится в профиль пользователя (``pip install --user``), ярлыки
кладутся на рабочий стол и рядом с программой, данные живут в %APPDATA%.

Ничего не «устанавливает» в системном смысле: ни служб, ни записей в реестр, ни
файлов вне профиля. Удаление — просто удалить папку и ярлыки.
"""

from __future__ import annotations

import importlib
import os
import site
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)

# Признак того, что скрипт уже перезапускал сам себя после установки библиотеки.
RETRY_FLAG = "TASKMANAGER_SETUP_RETRY"

# Чем закончилась установка библиотеки.
OK = "ok"
RESTART = "restart"
FAILED = "failed"


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


def refresh_import_paths() -> None:
    """Добавляет в поиск модулей папку, куда pip только что положил библиотеку.

    Python составляет список путей при старте. Если папки пользовательских
    пакетов тогда ещё не было (обычная ситуация при первой установке через
    ``pip --user``), свежепоставленная библиотека в этом же процессе не видна.
    """
    candidates = []
    try:
        candidates.append(site.getusersitepackages())
    except (AttributeError, TypeError):
        pass
    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()


def restart_self() -> int:
    """Перезапускает установщик новым процессом — он увидит новые пути.

    Нужен, когда библиотека встала в место, которого не было на момент запуска:
    добавить путь задним числом удаётся не всегда, а новый процесс собирает
    список путей заново.
    """
    environment = dict(os.environ, **{RETRY_FLAG: "1"})
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                env=environment)
    except OSError:
        return 1
    return result.returncode


def has_pyside_in_fresh_process() -> bool:
    """Проверяет импорт в новом процессе — он видит пути, которых не было у нас."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import PySide6"], capture_output=True
        )
    except OSError:
        return False
    return result.returncode == 0


def install_pyside() -> str:
    """Ставит PySide6 в профиль пользователя.

    Возвращает: OK — можно работать дальше; RESTART — библиотека встала, но
    видна только новому процессу; FAILED — установить не удалось.
    """
    say("Ставлю библиотеку интерфейса PySide6 (несколько минут, ~100 МБ)…")
    command = [
        sys.executable, "-m", "pip", "install", "--user",
        "-r", str(APP_DIR / "requirements.txt"),
    ]
    try:
        result = subprocess.run(command)
    except OSError as exc:
        say("Не удалось запустить pip: %s" % exc)
        return FAILED
    if result.returncode != 0:
        say("")
        say("pip завершился с ошибкой. Если в компании закрыт доступ к интернету,")
        say("попросите коллег принести файл PySide6 и поставьте его командой:")
        say("    python -m pip install --user путь-к-файлу.whl")
        return FAILED

    refresh_import_paths()
    if has_pyside():
        return OK
    return RESTART if has_pyside_in_fresh_process() else FAILED


def remember_version() -> None:
    """Записывает, какая версия установлена, — от неё считает «Обновить»."""
    try:
        sys.path.insert(0, str(APP_DIR))
        import update

        info = update.latest()
        if info:
            update.remember(info)
            say("Версия: %s от %s" % (info["sha"], info["date"]))
    except Exception:
        pass  # без интернета просто нечего записывать


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
    else:
        status = install_pyside()
        if status == FAILED:
            return 1
        if status == RESTART:
            if os.environ.get(RETRY_FLAG):
                say("")
                say("Библиотека установилась, но Python её по-прежнему не видит.")
                say("Закройте окно и запустите «Установить.cmd» ещё раз.")
                return 1
            # Библиотека встала в папку, которой не было при запуске: новый
            # процесс соберёт список путей заново и всё увидит.
            say("Библиотека установлена, продолжаю в новом окне…")
            say()
            return restart_self()
        say("Библиотека установлена.")

    remember_version()

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
