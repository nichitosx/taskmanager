"""Шрифты, которые лежат рядом с программой.

Пиксельное оформление имеет смысл только с пиксельным шрифтом, а ставить его в
систему на рабочем компьютере не всегда можно и не всегда хочется. Поэтому файлы
шрифтов кладутся в папку ``fonts`` рядом с программой: при запуске они
подключаются к приложению и доступны только ему. Установка в Windows не нужна,
права администратора тоже.

Внутри две папки:

* ``fonts/bundled`` — шрифты, которые идут вместе с программой. Там только те,
  чья лицензия разрешает распространение (SIL Open Font License).
* ``fonts`` — ваши собственные файлы. Они не попадают ни в репозиторий, ни в
  архив и остаются на месте при обновлении.

Шрифта Minecraft в поставке нет и быть не может: это ресурс игры, его лицензия
распространение не разрешает. Свой файл можно положить рядом — программа
подхватит любой .ttf/.otf.
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


def bundled_dir() -> Path:
    """Папка со шрифтами, которые идут вместе с программой."""
    return fonts_dir() / "bundled"


def files() -> list[Path]:
    """Все файлы шрифтов: сначала свои, потом входящие в поставку.

    Свои идут первыми: если человек положил шрифт сам, он и должен победить.
    """
    own = sorted(p for p in fonts_dir().iterdir() if p.suffix.lower() in SUFFIXES)
    shipped = []
    if bundled_dir().is_dir():
        shipped = sorted(
            p for p in bundled_dir().iterdir() if p.suffix.lower() in SUFFIXES
        )
    return own + shipped


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
