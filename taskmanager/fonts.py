"""Шрифты, которые лежат рядом с программой.

Терминальный вид держится на шрифте, а ставить шрифты в систему на рабочем
компьютере не всегда можно и не всегда хочется. Поэтому файлы
шрифтов кладутся в папку ``fonts`` рядом с программой: при запуске они
подключаются к приложению и доступны только ему. Установка в Windows не нужна,
права администратора тоже.

В поставке один шрифт — IBM VGA 8×16 (The Ultimate Oldschool PC Font Pack,
CC BY-SA 4.0): на нём набран весь интерфейс. Он лежит в
``taskmanager/assets/fonts``. Свой шрифт для заголовков пользователь кладёт
в папку ``fonts``: его можно выбрать в настройках.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import app_dir

SUFFIXES = (".ttf", ".otf", ".ttc")

# Семейства, подключённые из папки fonts за время работы программы.
_loaded: list[str] = []
# Семейства шрифтов поставки — они есть всегда, но уступают своим.
_shipped: list[str] = []


def shipped_dir() -> Path:
    """Папка со шрифтами, которые едут вместе с программой."""
    return Path(__file__).resolve().parent / "assets" / "fonts"


def shipped_families() -> list[str]:
    return list(_shipped)


def _add(path: Path, into: list[str]) -> list[str]:
    from PySide6.QtGui import QFontDatabase

    identifier = QFontDatabase.addApplicationFont(str(path))
    if identifier < 0:
        return []
    families = QFontDatabase.applicationFontFamilies(identifier)
    for family in families:
        if family not in into:
            into.append(family)
    return families


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
    """Подключает шрифты поставки и свои. Вызывается один раз при запуске."""
    _shipped.clear()
    folder = shipped_dir()
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in SUFFIXES:
                _add(path, _shipped)

    _loaded.clear()
    for path in files():
        _add(path, _loaded)
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
