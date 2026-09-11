"""Собирает ZIP для раздачи: распаковал — запустил «Установить.cmd» — работаешь.

    python build_zip.py

Архив кладётся в ``dist/TaskManager-<дата>.zip``. Внутрь попадает только то, что
нужно для работы: исходники, скрипты запуска и README. Личные данные (база,
настройки, ярлыки, кеш Python) не попадают — проверяется по списку исключений.

Файл прикладывается к релизу на GitHub: «Releases → Draft a new release →
Attach binaries». Тогда скачивание сводится к одному клику по ссылке.
"""

from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Что кладём в архив. Папки берутся целиком, кроме исключений ниже.
INCLUDE = [
    "taskmanager",
    "fonts",
    "run.py",
    "install.py",
    "update.py",
    "requirements.txt",
    "README.md",
    "Установить.cmd",
    "Обновить.cmd",
    "TaskManager.cmd",
]

# Что не должно попасть в архив ни при каких условиях.
SKIP_DIRS = {"__pycache__", ".git", "dist", "data", ".idea", ".vscode"}
# Шрифты не распространяем: у файлов свои лицензии, а свой шрифт пользователь
# кладёт в папку fonts сам.
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".lnk", ".ico", ".log", ".ttf", ".otf", ".ttc"}
SKIP_NAMES = {"settings.json", "portable.flag"}


def keep(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.name not in SKIP_NAMES


def collect() -> list[Path]:
    files: list[Path] = []
    for item in INCLUDE:
        source = ROOT / item
        if not source.exists():
            print("нет файла, пропускаю: %s" % item)
            continue
        if source.is_dir():
            files.extend(p for p in sorted(source.rglob("*")) if p.is_file() and keep(p))
        elif keep(source):
            files.append(source)
    return files


def build() -> Path:
    DIST.mkdir(exist_ok=True)
    archive = DIST / ("TaskManager-%s.zip" % date.today().isoformat())
    files = collect()

    # Внутри архива всё лежит в одной папке: распаковка не мусорит в Загрузках.
    root_name = "TaskManager"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path in files:
            zip_file.write(path, str(Path(root_name) / path.relative_to(ROOT)))

    print("файлов: %d" % len(files))
    print("архив:  %s (%.1f КБ)" % (archive, archive.stat().st_size / 1024))
    return archive


def verify(archive: Path) -> bool:
    """Проверяет, что в архиве нет личных данных и есть всё нужное."""
    with zipfile.ZipFile(archive) as zip_file:
        names = zip_file.namelist()

    problems = [
        name for name in names if Path(name).suffix.lower() in SKIP_SUFFIXES
    ]
    problems += [name for name in names if Path(name).name in SKIP_NAMES]
    required = [
        "TaskManager/fonts/README.md",
        "TaskManager/run.py",
        "TaskManager/install.py",
        "TaskManager/update.py",
        "TaskManager/Установить.cmd",
        "TaskManager/Обновить.cmd",
        "TaskManager/taskmanager/ui/main_window.py",
    ]
    missing = [name for name in required if name not in names]

    for name in problems:
        print("лишнее в архиве: %s" % name)
    for name in missing:
        print("не хватает: %s" % name)
    return not problems and not missing


if __name__ == "__main__":
    path = build()
    sys.exit(0 if verify(path) else 1)
