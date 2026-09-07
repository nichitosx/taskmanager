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

import json
import shutil
import ssl
import sys
import tempfile
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

    if current.get("sha") == fresh["sha"]:
        say("У вас уже последняя версия.")
        return 0

    if "--check" in sys.argv:
        say("Есть обновление. Запустите «Обновить.cmd», чтобы поставить его.")
        return 0

    archive = download()
    if archive is None:
        return 1
    source = unpack(archive)
    if source is None:
        return 1
    if not apply(source):
        return 1

    remember(fresh)
    say()
    say("Готово: обновлено до %s от %s." % (fresh["sha"], fresh["date"]))
    say("Задачи, настройки и шрифты остались на месте.")
    say("Если программа была открыта — закройте её и запустите заново.")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nНажмите Enter, чтобы закрыть…")
    except (EOFError, KeyboardInterrupt):
        pass  # запустили без консоли — просто выходим
    sys.exit(code)
