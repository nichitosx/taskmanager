"""Обновление программы без переустановки.

    python update.py            — проверить и обновить
    python update.py --check    — только проверить, ничего не менять

Скачивает свежую версию с GitHub и заменяет файлы программы. Задачи, настройки
и отчёты живут отдельно (в %APPDATA%\\TaskManager), поэтому обновление их не
трогает — как и папку ``fonts`` со своими шрифтами и ``data`` в портативном
режиме.

Если что-то пойдёт не так при замене файлов, прежняя версия возвращается из
резервной копии: программа не должна остаться сломанной.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

REPO = "nichitosx/taskmanager"
BRANCH = "main"
API_COMMIT = "https://api.github.com/repos/%s/commits/%s" % (REPO, BRANCH)
ARCHIVE = "https://github.com/%s/archive/refs/heads/%s.zip" % (REPO, BRANCH)

# Что переносим из новой версии. Всё остальное в папке программы не трогаем.
PACKAGE = "taskmanager"
# Шрифты поставки обновляются вместе с программой; свои файлы рядом не трогаются.
BUNDLED_FONTS = Path("fonts") / "bundled"
ROOT_FILES = [
    "run.py",
    "install.py",
    "update.py",
    "build_zip.py",
    "requirements.txt",
    "README.md",
    "Установить.cmd",
    "Обновить.cmd",
    "TaskManager.cmd",
]

TIMEOUT = 30

# Файлы, по которым считается «версия»: именно они и обновляются.
FINGERPRINT_SUFFIXES = (".py", ".cmd", ".txt", ".md")

TIMEOUT_NOTE = "Проверка обновлений"

# Имя канала одиночного запуска — через него просим программу закрыться.
SERVER_NAME = "TaskManager.SingleInstance"


def say(text: str = "") -> None:
    print(text, flush=True)


def marker_path() -> Path:
    from taskmanager.config import data_dir

    return data_dir() / "installed.json"


def installed() -> dict:
    try:
        return json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(info: dict) -> None:
    try:
        marker_path().write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def context():
    from taskmanager.integrations import net

    return net.ssl_context()


def fingerprint(root: Path) -> str:
    """Отпечаток версии — свёртка по содержимому файлов программы.

    Отметка в файле врёт: её можно записать при установке старого архива. А
    содержимое не соврёт — если файлы совпали, версия та же. Переводы строк
    приводим к одному виду: git на Windows переписывает их, и одна и та же
    версия иначе давала бы разные отпечатки.
    """
    digest = hashlib.sha256()
    for name in [PACKAGE] + ROOT_FILES:
        source = root / name
        if source.is_dir():
            items = sorted(p for p in source.rglob("*") if p.is_file())
        elif source.is_file():
            items = [source]
        else:
            continue
        for item in items:
            if item.suffix.lower() not in FINGERPRINT_SUFFIXES:
                continue
            if "__pycache__" in item.parts:
                continue
            digest.update(str(item.relative_to(root)).replace("\\", "/").encode("utf-8"))
            digest.update(item.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


def latest() -> dict | None:
    """Сведения о последней версии в репозитории."""
    request = urllib.request.Request(API_COMMIT, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            say("Репозиторий недоступен: он приватный или адрес изменился.")
            say("Сделайте репозиторий публичным либо обновляйтесь вручную.")
        else:
            say("GitHub ответил ошибкой %d." % exc.code)
        return None
    except (urllib.error.URLError, ssl.SSLError, ValueError) as exc:
        from taskmanager.integrations import net

        say("Не удалось связаться с GitHub: %s" % net.describe(exc))
        return None

    commit = payload.get("commit", {})
    return {
        "sha": payload.get("sha", "")[:12],
        "date": (commit.get("committer") or {}).get("date", "")[:10],
        "message": (commit.get("message") or "").splitlines()[0][:80],
    }


def download() -> Path | None:
    say("Скачиваю свежую версию…")
    try:
        with urllib.request.urlopen(ARCHIVE, timeout=TIMEOUT * 2, context=context()) as response:
            data = response.read()
    except (urllib.error.URLError, ssl.SSLError) as exc:
        say("Скачать не получилось: %s" % exc)
        return None

    target = Path(tempfile.mkdtemp()) / "update.zip"
    target.write_bytes(data)
    say("Получено %.1f МБ" % (len(data) / 1024 / 1024))
    return target


def unpack(archive: Path) -> Path | None:
    """Распаковывает архив и возвращает папку с новой версией."""
    folder = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(folder)
    except (zipfile.BadZipFile, OSError) as exc:
        say("Архив повреждён: %s" % exc)
        return None

    inner = [p for p in folder.iterdir() if p.is_dir()]
    source = inner[0] if len(inner) == 1 else folder
    if not (source / PACKAGE).is_dir() or not (source / "run.py").exists():
        say("В архиве нет ожидаемых файлов — обновление отменено.")
        return None
    return source


def apply(source: Path) -> bool:
    """Переносит новые файлы, сохраняя прежнюю версию до самого конца."""
    package = APP_DIR / PACKAGE
    backup = APP_DIR / (PACKAGE + ".backup")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    try:
        if package.exists():
            shutil.move(str(package), str(backup))
        shutil.copytree(source / PACKAGE, package)

        shipped = source / BUNDLED_FONTS
        if shipped.is_dir():
            target = APP_DIR / BUNDLED_FONTS
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(shipped, target)

        for name in ROOT_FILES:
            new_file = source / name
            if new_file.exists():
                shutil.copyfile(new_file, APP_DIR / name)
    except (OSError, shutil.Error) as exc:
        say("Ошибка при замене файлов: %s" % exc)
        if backup.exists():
            shutil.rmtree(package, ignore_errors=True)
            shutil.move(str(backup), str(package))
            say("Вернул прежнюю версию — программа осталась рабочей.")
        return False

    shutil.rmtree(backup, ignore_errors=True)
    return True


def ask_running_app_to_quit() -> bool:
    """Просит работающую программу закрыться. True — она была запущена.

    Файлы можно менять и под работающей программой, но она продолжит выполнять
    старый код и запишет свои настройки поверх новых. Поэтому сначала закрываем.
    """
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False

    application = QCoreApplication.instance() or QCoreApplication([])
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(400):
        return False

    say("Программа запущена — прошу её закрыться…")
    socket.write(b"quit")
    socket.flush()
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()

    # Ждём, пока канал освободится: значит, программа действительно закрылась.
    for _ in range(15):
        time.sleep(0.4)
        probe = QLocalSocket()
        probe.connectToServer(SERVER_NAME)
        alive = probe.waitForConnected(200)
        probe.abort()
        if not alive:
            say("Программа закрыта.")
            return True
    say("Программа закрывается дольше обычного — продолжаю обновление.")
    return True


def relaunch() -> None:
    """Запускает программу заново — уже с новыми файлами."""
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else interpreter)
    try:
        subprocess.Popen([executable, str(APP_DIR / "run.py")], cwd=str(APP_DIR))
        say("Программа запущена заново.")
    except OSError as exc:
        say("Запустить заново не получилось: %s" % exc)


def main() -> int:
    say("TaskManager — обновление")
    say("Папка программы: %s" % APP_DIR)
    say()

    current = installed()
    if current.get("sha"):
        say("Установлено: %s от %s" % (current["sha"], current.get("date", "—")))

    fresh = latest()
    if fresh is None:
        return 1

    say("В репозитории: %s от %s" % (fresh["sha"], fresh["date"]))
    if fresh.get("message"):
        say("Последнее изменение: %s" % fresh["message"])
    say()

    archive = download()
    if archive is None:
        return 1
    source = unpack(archive)
    if source is None:
        return 1

    # Сравниваем то, что лежит на диске, с тем, что пришло: отметка о версии
    # может быть неверной, а файлы — нет.
    if fingerprint(APP_DIR) == fingerprint(source):
        say("У вас уже последняя версия: файлы совпадают.")
        fresh["fingerprint"] = fingerprint(APP_DIR)
        remember(fresh)
        return 0

    if "--check" in sys.argv:
        say("Есть обновление. Запустите «Обновить.cmd», чтобы поставить его.")
        return 0

    was_running = ask_running_app_to_quit()
    if not apply(source):
        return 1

    fresh["fingerprint"] = fingerprint(APP_DIR)
    remember(fresh)
    say()
    say("Готово: обновлено до %s от %s." % (fresh["sha"], fresh["date"]))
    say("Задачи, настройки и свои шрифты остались на месте.")
    if was_running:
        relaunch()
    return 0


if __name__ == "__main__":
    code = main()
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nНажмите Enter, чтобы закрыть…")
    except (EOFError, KeyboardInterrupt):
        pass  # запустили без консоли — просто выходим
    sys.exit(code)
