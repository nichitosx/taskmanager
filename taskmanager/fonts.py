"""Шрифты, которые лежат рядом с программой.

Пиксельное оформление имеет смысл только с пиксельным шрифтом, а ставить его в
систему на рабочем компьютере не всегда можно и не всегда хочется. Поэтому файлы
шрифтов кладутся в папку ``fonts`` рядом с программой: при запуске они
подключаются к приложению и доступны только ему. Установка в Windows не нужна,
права администратора тоже.

Готовых шрифтов в поставке нет: чужие файлы распространять нельзя, а те
свободные, что подходили по лицензии, на разных компьютерах вели себя
по-разному. Поэтому шрифт каждый кладёт себе сам — любой .ttf/.otf. Где его
взять, написано в настройках и в ``fonts/README.md``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import app_dir

SUFFIXES = (".ttf", ".otf", ".ttc")

# Семейства, подключённые из папки fonts за время работы программы.
_loaded: list[str] = []


def fonts_dir() -> Path:
    """Папка для своих шрифтов."""
    path = app_dir() / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def files() -> list[Path]:
    """Файлы шрифтов, положенные в папку."""
    return sorted(p for p in fonts_dir().iterdir() if p.suffix.lower() in SUFFIXES)


def loaded_families() -> list[str]:
    return list(_loaded)


def load_bundled() -> list[str]:
    """Подключает все шрифты из папки. Вызывается один раз при запуске."""
    from PySide6.QtGui import QFontDatabase

    _loaded.clear()
    for path in files():
        identifier = QFontDatabase.addApplicationFont(str(path))
        if identifier < 0:
            continue
        for family in QFontDatabase.applicationFontFamilies(identifier):
            if family not in _loaded:
                _loaded.append(family)
    return list(_loaded)


def add_file(source: Path) -> str:
    """Копирует файл шрифта в папку программы и сразу подключает его.

    Возвращает название семейства или пустую строку, если файл не подошёл.
    """
    from PySide6.QtGui import QFontDatabase

    source = Path(source)
    if source.suffix.lower() not in SUFFIXES:
        return ""

    target = fonts_dir() / source.name
    if source.resolve() != target.resolve():
        try:
            shutil.copyfile(source, target)
        except OSError:
            return ""

    identifier = QFontDatabase.addApplicationFont(str(target))
    if identifier < 0:
        return ""
    families = QFontDatabase.applicationFontFamilies(identifier)
    for family in families:
        if family not in _loaded:
            _loaded.append(family)
    return families[0] if families else ""
