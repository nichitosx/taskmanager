"""Оформление: палитра, шрифты и таблица стилей.

Минимализм: тёплый почти-чёрный фон, один акцентный цвет, тонкие линии вместо
рамок и теней, моноширинные подписи капслоком для служебного текста.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QFont, QFontDatabase

# --- Палитры ------------------------------------------------------------------

DARK = {
    "bg": "#131211",
    "surface": "#1A1917",
    "surface_alt": "#232120",
    "surface_hover": "#282624",
    "border": "#302E2B",
    "border_soft": "#252321",
    "text": "#EDEAE3",
    "text_dim": "#9A958C",
    "text_faint": "#6B665F",
    "accent": "#D97757",
    "accent_soft": "#3A2620",
    "danger": "#D4433C",
    "danger_soft": "#3A1F1D",
    "warning": "#C99A3F",
    "warning_soft": "#332916",
    "success": "#6E9C6A",
    "success_soft": "#1E2A1D",
    "info": "#6E8CA8",
}

LIGHT = {
    "bg": "#FAF9F5",
    "surface": "#FFFFFF",
    "surface_alt": "#F2F0E9",
    "surface_hover": "#EDEAE0",
    "border": "#E0DCD1",
    "border_soft": "#EDEAE1",
    "text": "#1F1E1D",
    "text_dim": "#6B665F",
    "text_faint": "#918B81",
    "accent": "#C2603C",
    "accent_soft": "#FAEBE3",
    "danger": "#C0342C",
    "danger_soft": "#FBE7E5",
    "warning": "#96701C",
    "warning_soft": "#F8EFD9",
    "success": "#4F7A4B",
    "success_soft": "#E9F1E7",
    "info": "#4A6C8A",
}

# --- Темы с одним акцентом ----------------------------------------------------
# Ниже — приборные панели: почти чёрный фон, один цвет на всё и холодный синий
# для «информации», чтобы шкала важности оставалась различимой. Семантику
# (опасно, внимание, готово) не красим в цвет темы: красное должно быть
# красным даже на зелёном экране.

AMBER = {
    "bg": "#0C0A06",
    "surface": "#13100A",
    "surface_alt": "#1B1710",
    "surface_hover": "#241E14",
    "border": "#453519",
    "border_soft": "#2B2211",
    "text": "#FFCE73",
    "text_dim": "#BC8C3C",
    "text_faint": "#7E5D24",
    "accent": "#FFA51F",
    "accent_soft": "#33210A",
    "danger": "#FF5F4E",
    "danger_soft": "#361410",
    "warning": "#FFD166",
    "warning_soft": "#33280F",
    "success": "#9BD96B",
    "success_soft": "#1B2A13",
    "info": "#5FA8C7",
}

GREEN = {
    "bg": "#050A06",
    "surface": "#09110B",
    "surface_alt": "#0F1A12",
    "surface_hover": "#152318",
    "border": "#22402B",
    "border_soft": "#16291C",
    "text": "#8CF5AE",
    "text_dim": "#4FB375",
    "text_faint": "#30774B",
    "accent": "#3BFF8B",
    "accent_soft": "#092716",
    "danger": "#FF6B5B",
    "danger_soft": "#301612",
    "warning": "#E8D44D",
    "warning_soft": "#2C2A10",
    "success": "#5BE07F",
    "success_soft": "#122A1A",
    "info": "#58B8D6",
}

EMBER = {
    "bg": "#080506",
    "surface": "#110A08",
    "surface_alt": "#1A100C",
    "surface_hover": "#23160F",
    "border": "#4A2512",
    "border_soft": "#2F190D",
    "text": "#FFE3CE",
    "text_dim": "#C98A62",
    "text_faint": "#8A5A3C",
    "accent": "#FF5B1F",
    "accent_soft": "#331106",
    "danger": "#FF3B30",
    "danger_soft": "#36100D",
    "warning": "#FFA62B",
    "warning_soft": "#33210B",
    "success": "#7FD46A",
    "success_soft": "#1A2A14",
    "info": "#5A9FC4",
}

ICE = {
    "bg": "#070B10",
    "surface": "#0C1219",
    "surface_alt": "#111A23",
    "surface_hover": "#17222E",
    "border": "#27394C",
    "border_soft": "#1A2633",
    "text": "#DCEAF5",
    "text_dim": "#8AA6BE",
    "text_faint": "#5B7186",
    "accent": "#35C8E8",
    "accent_soft": "#072630",
    "danger": "#FF5A6E",
    "danger_soft": "#2E1218",
    "warning": "#FFC24D",
    "warning_soft": "#30260F",
    "success": "#56D39A",
    "success_soft": "#102A21",
    "info": "#6EA8FF",
}

MONO = {
    "bg": "#000000",
    "surface": "#060606",
    "surface_alt": "#0E0E0E",
    "surface_hover": "#171717",
    "border": "#3C3C3C",
    "border_soft": "#242424",
    "text": "#FFFFFF",
    "text_dim": "#9C9C9C",
    "text_faint": "#5E5E5E",
    "accent": "#E6E6E6",
    "accent_soft": "#1C1C1C",
    "danger": "#D96C6C",
    "danger_soft": "#2A1515",
    "warning": "#C9B682",
    "warning_soft": "#262114",
    "success": "#8FBF8F",
    "success_soft": "#152015",
    "info": "#8FA8BF",
}

# Порядок важен: в таком виде темы и показываются в настройках.
PALETTES = {
    "dark": DARK,
    "light": LIGHT,
    "amber": AMBER,
    "green": GREEN,
    "ember": EMBER,
    "ice": ICE,
    "mono": MONO,
}

PALETTE_LABELS = {
    "dark": "Тёплая тёмная",
    "light": "Светлая",
    "amber": "Янтарный терминал",
    "green": "Зелёный люминофор",
    "ember": "Угольный оранжевый",
    "ice": "Холодная синь",
    "mono": "Монохром",
}

# Пять ступеней — пять разных цветов: от спокойного серого к тревожному
# красному. Одинаковых быть не должно, иначе шкала перестаёт читаться.
PRIORITY_COLOR_KEYS = {
    0: "text_dim",
    1: "info",
    2: "warning",
    3: "accent",
    4: "danger",
}

# --- Стили оформления ---------------------------------------------------------
# «Мягкий» — скруглённые карточки и системный шрифт. «Пиксельный» — прямые углы,
# моноширинный шрифт и жёсткие рамки: ретро-цифровой вид без потери читаемости.
STYLE_SOFT = "soft"
STYLE_PIXEL = "pixel"

STYLE_LABELS = {
    STYLE_SOFT: "Мягкий",
    STYLE_PIXEL: "Пиксельный",
}

# Скругления по типам элементов для каждого стиля.
RADII = {
    STYLE_SOFT: {"card": 10, "input": 8, "button": 8, "pill": 9, "small": 6, "nav": 7},
    # Пиксельный стиль — приборная панель: ни одного скругления. Углы рамок
    # отмечены скобками, см. paint_brackets в widgets.py.
    STYLE_PIXEL: {"card": 0, "input": 0, "button": 0, "pill": 0, "small": 0, "nav": 0},
}

# Ступенчатое скругление карточек: радиус и высота одной «ступеньки».
PIXEL_CORNER = 6
PIXEL_STEP = 2

_style = STYLE_SOFT


def set_style(name: str) -> None:
    """Запоминает выбранный стиль: его читают и виджеты, и таблица стилей."""
    global _style
    _style = name if name in STYLE_LABELS else STYLE_SOFT


def current_style() -> str:
    return _style


# --- Масштаб ------------------------------------------------------------------
# За ноутбуком хочется интерфейс помельче, за большим монитором — покрупнее.
# Масштабируются размеры шрифтов и все расстояния в таблице стилей: один
# множитель вместо второго комплекта размеров на каждый случай.

SCALE_STEPS = (80, 90, 100, 110, 125, 150)
DEFAULT_SCALE = 100

_scale = 1.0


def set_scale(percent) -> None:
    """Запоминает масштаб. Слишком мелкое и слишком крупное подрезаем."""
    global _scale
    try:
        value = int(percent)
    except (TypeError, ValueError):
        value = DEFAULT_SCALE
    _scale = max(min(value, max(SCALE_STEPS)), min(SCALE_STEPS)) / 100


def scale() -> float:
    return _scale


def scale_percent() -> int:
    return round(_scale * 100)


def px(value: float, minimum: int = 1) -> int:
    """Размер в пикселях с учётом масштаба — но не меньше minimum."""
    return max(minimum, round(value * _scale))


_colors: dict[str, str] = dict(DARK)


def set_colors(values: dict[str, str]) -> None:
    """Запоминает цвета применённой темы.

    Их спрашивают виджеты, которые рисуют себя сами и не получают палитру
    через конструктор, — например, подпись раздела со своей линейкой.
    """
    global _colors
    _colors = dict(values)


def colors() -> dict[str, str]:
    return dict(_colors)


def is_pixel() -> bool:
    return _style == STYLE_PIXEL


def radius(kind: str = "card") -> int:
    value = RADII.get(_style, RADII[STYLE_SOFT]).get(kind, 0)
    return px(value, 0) if value else 0


# Акцентный шрифт пиксельного стиля: им набраны заголовки, подписи разделов,
# логотип и счётчики — то есть «вывеска», а не текст задач. Сплошной пиксельный
# шрифт в списке читался бы хуже, поэтому основной текст остаётся моноширинным,
# как в консоли.
PIXEL_CANDIDATES = [
    "Minecraft Rus",
    "Minecraft",
    "Monocraft",
    "Ndot 55",
    "Departure Mono",
    "Silkscreen",
    "Press Start 2P",
    "W95FA",
]

MONO_CANDIDATES = [
    "JetBrains Mono",
    "Cascadia Mono",
    "Consolas",
    "DejaVu Sans Mono",
    "Courier New",
]

UI_CANDIDATES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Inter",
    "Noto Sans",
]


def _pick(candidates: list[str], fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def mono_family() -> str:
    return _pick(MONO_CANDIDATES, "monospace")


def ui_family() -> str:
    return _pick(UI_CANDIDATES, "sans-serif")


def mono_font(size: int = 9, bold: bool = False, spacing: float = 0.0) -> QFont:
    """Служебный текст: метки, даты, тексты отчётов.

    В пиксельном стиле это тот же пиксельный шрифт, что и везде, только на
    размер крупнее — у таких шрифтов маленькая высота строчных букв.
    """
    family = pixel_family() if is_pixel() else mono_family()
    font = QFont(family, px(size + FONT_BUMP, 5))
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


# Шрифт, выбранный пользователем в настройках (пусто — подобрать самим).
_preferred_pixel = ""


def set_preferred_pixel(family: str) -> None:
    global _preferred_pixel
    _preferred_pixel = (family or "").strip()


def pixel_candidates() -> list[str]:
    """Что можно взять под пиксельный стиль: сначала свои файлы, потом система."""
    from ..fonts import loaded_families

    found: list[str] = []
    for family in loaded_families() + PIXEL_CANDIDATES:
        if family and family not in found:
            found.append(family)
    return found


def pixel_family() -> str:
    """Пиксельный шрифт: выбранный в настройках, свой из папки, системный.

    Файл из папки ``fonts`` идёт первым: его положили осознанно, а системные
    пиксельные шрифты могут оказаться на одном компьютере и отсутствовать на
    другом.
    """
    available = set(QFontDatabase.families())
    if _preferred_pixel and _preferred_pixel in available:
        return _preferred_pixel
    for family in pixel_candidates():
        if family in available:
            return family
    return mono_family()


def has_pixel_font() -> bool:
    return pixel_family() != mono_family()


def accent_family() -> str:
    """Шрифт вывесок: в пиксельном стиле — пиксельный, иначе моноширинный."""
    return pixel_family() if is_pixel() else mono_family()


def accent_font(size: int = 9, bold: bool = False, spacing: float = 0.0) -> QFont:
    """Заголовки, подписи разделов, счётчики.

    В пиксельном стиле это самое заметное отличие: вывески набраны пиксельным
    шрифтом, а текст задач остаётся читаемым моноширинным.
    """
    font = QFont(accent_family(), px(size + FONT_BUMP, 5))
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont(pixel_family() if is_pixel() else ui_family(), px(size + FONT_BUMP, 5))
    font.setBold(bold)
    return font


def title_px() -> int:
    """Размер названия задачи в пикселях.

    В пикселях, а не в пунктах, ровно по той же причине, что и у мелких меток:
    таблица стилей задаёт размер в пикселях и перебивает setFont. Пока размеры
    не совпадали, высота строки считалась по одному шрифту, а текст рисовался
    другим — и вторая строка названия не влезала.
    """
    return px(16 if is_pixel() else 17, 8)


def title_font(bold: bool = False) -> QFont:
    font = QFont(pixel_family() if is_pixel() else ui_family())
    font.setPixelSize(title_px())
    # В мягком стиле буквы чуть плотнее по начертанию: так текст читается
    # увереннее и ближе по весу к пиксельному шрифту.
    font.setWeight(
        QFont.Weight.DemiBold if bold
        else (QFont.Weight.Normal if is_pixel() else QFont.Weight.Medium)
    )
    return font


def title_css(bold: bool = False) -> str:
    """Тот же шрифт для таблицы стилей самой метки.

    Межбуквенный интервал обнуляем: общий стиль добавляет его в пиксельном
    режиме, а расчёт высоты строки про него не знает.
    """
    return 'font-family: "%s"; font-size: %dpx; font-weight: %d; letter-spacing: 0;' % (
        pixel_family() if is_pixel() else ui_family(),
        title_px(),
        700 if bold else (400 if is_pixel() else 500),
    )


def small_font_px() -> int:
    """Размер шрифта мелких меток в пикселях (не в пунктах — не зависит от DPI)."""
    return px(13 if is_pixel() else 12, 7)


def small_font() -> QFont:
    font = QFont(accent_family() if is_pixel() else mono_family())
    font.setPixelSize(small_font_px())
    return font


def small_font_css() -> str:
    """Тот же шрифт, но для таблицы стилей самого виджета.

    Общая таблица стилей задаёт шрифт всем QWidget и перебивает setFont, поэтому
    у метки шрифт указывается прямо в её собственных стилях — иначе ширина,
    посчитанная по метрикам, не совпадёт с нарисованным текстом.
    """
    # Межбуквенный интервал у мелких меток обнуляем: общая таблица стилей его
    # добавляет, а QFontMetrics про него не знает — и текст переставал влезать.
    return 'font-family: "%s"; font-size: %dpx; letter-spacing: 0;' % (
        accent_family() if is_pixel() else mono_family(),
        small_font_px(),
    )


# Общий подрост шрифта: чуть крупнее, чем было, в обоих стилях.
FONT_BUMP = 1


def nav_padding() -> tuple[int, int]:
    """Отступы пункта бокового меню: (по горизонтали, по вертикали).

    В мягком стиле меню плотное — списки «когда» и «состояние» занимают меньше
    места; в пиксельном воздуха больше, там строки крупнее.
    """
    return (px(10), px(8)) if is_pixel() else (px(10), px(4))


def nav_spacing() -> int:
    """Расстояние между соседними пунктами бокового меню.

    Одно на все разделы — и «когда» с «состоянием», и продукты: разный шаг
    в соседних списках сразу бросается в глаза.
    """
    # Пиксельный шрифт крупный и плотный — ему нужен воздух; системный тоньше
    # и мельче, и при таком же шаге список выглядел разреженным.
    return px(5) if is_pixel() else px(2)


def section_gap() -> int:
    """Отступ между разделами бокового меню."""
    return px(12) if is_pixel() else px(9)


def line_height_percent() -> int:
    """Межстрочный интервал в процентах от высоты строки.

    Пиксельные шрифты плотные, строки слипаются — в этом стиле их разводим.
    """
    return 150 if is_pixel() else 100


def line_extra() -> int:
    """Дополнительный воздух между строками внутри карточек, в пикселях."""
    return px(4, 0) if is_pixel() else 0


def multiline(text: str) -> str:
    """Многострочный текст с нужным межстрочным интервалом.

    В таблицах стилей Qt нет line-height, зато он есть в разметке — поэтому в
    пиксельном стиле текст отдаётся как HTML.
    """
    if not is_pixel():
        return text
    body = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
    return '<div style="line-height: %d%%">%s</div>' % (line_height_percent(), body)


def apply_text_spacing(edit) -> None:
    """Разводит строки в текстовом поле (отчёты, выгрузки)."""
    if not is_pixel():
        return
    from PySide6.QtGui import QTextBlockFormat, QTextCursor

    cursor = edit.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    block = QTextBlockFormat()
    block.setLineHeight(
        line_height_percent(), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor.mergeBlockFormat(block)
    cursor.clearSelection()
    edit.setTextCursor(cursor)


# --- Символы, которых нет в пиксельных шрифтах --------------------------------
# Пиксельные шрифты знают латиницу, кириллицу и знаки препинания — и всё. Рамок
# и столбиков в них нет. Но шрифты можно смешивать: буквы остаются пиксельными,
# а каждый недостающий знак рисуется тем системным шрифтом, где он есть.

GLYPH_FALLBACKS = (
    "Consolas",
    "Cascadia Mono",
    "Lucida Console",
    "DejaVu Sans Mono",
    "Courier New",
    "Segoe UI Symbol",
)

# Для каждого знака — красивый вариант и запасной из чистого ASCII на случай,
# если ни один шрифт в системе его не знает.
GLYPHS = {
    "full": ("\u2588", "#"),      # полная клетка столбика
    "half": ("\u2584", ":"),      # половинка снизу
    "base": ("\u2500", "_"),      # линия основания
    "corner_tl": ("\u250c", "+"),
    "corner_tr": ("\u2510", "+"),
    "corner_bl": ("\u2514", "+"),
    "corner_br": ("\u2518", "+"),
    "line_h": ("\u2500", "-"),
    "line_v": ("\u2502", "|"),
    "dot": ("\u00b7", "."),
    "arrow": ("\u203a", ">"),
}

_glyph_cache: dict[str, str] = {}
_family_cache: dict[tuple[str, int], bool] = {}


def _family_has(family: str, code: int) -> bool:
    """Есть ли знак в шрифте. QRawFont не врёт, в отличие от QFontMetrics."""
    key = (family, code)
    if key not in _family_cache:
        from PySide6.QtGui import QRawFont

        font = QFont(family)
        font.setPixelSize(14)
        try:
            _family_cache[key] = QRawFont.fromFont(font).supportsCharacter(code)
        except Exception:
            _family_cache[key] = False
    return _family_cache[key]


def glyph_family(char: str, base: str) -> str:
    """Каким шрифтом рисовать этот знак: своим или одним из запасных."""
    if not char:
        return base
    code = ord(char[0])
    if code < 128 or _family_has(base, code):
        return base
    for family in GLYPH_FALLBACKS:
        if _family_has(family, code):
            return family
    return base


def glyph(name: str) -> str:
    """Знак для рисунка: красивый, если его знает хоть один шрифт в системе."""
    if name not in _glyph_cache:
        nice, plain = GLYPHS.get(name, ("", ""))
        code = ord(nice) if nice else 0
        known = bool(nice) and any(
            _family_has(family, code) for family in GLYPH_FALLBACKS
        )
        _glyph_cache[name] = nice if known else plain
    return _glyph_cache[name]


def mix(color: str, base: str, alpha: float) -> str:
    """Смешивает цвет с фоном и отдаёт обычный #rrggbb.

    В отличие от tint, годится и для QColor: тот понимает только настоящие
    цвета, а строку rgba(...) молча превращает в чёрный.
    """
    def parts(value: str) -> tuple[int, int, int]:
        value = (value or "").lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    try:
        front, back = parts(color), parts(base)
    except (ValueError, IndexError):
        return base
    alpha = max(0.0, min(1.0, alpha))
    return "#%02x%02x%02x" % tuple(
        round(back[i] + (front[i] - back[i]) * alpha) for i in range(3)
    )


def tint(color: str, alpha: float) -> str:
    """Полупрозрачная версия цвета для подложек «пилюль» и рамок.

    Возвращает rgba(...) — работает и на тёмной, и на светлой теме, потому что
    подмешивается именно фон, а не заранее посчитанный оттенок.
    """
    value = (color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "transparent"
    return "rgba(%d, %d, %d, %d)" % (red, green, blue, max(0, min(255, round(alpha * 255))))


def palette(theme: str) -> dict[str, str]:
    """Цвета темы. Незнакомое имя — тёплая тёмная: она была всегда."""
    return dict(PALETTES.get(theme, DARK))


def luminance(color: str) -> float:
    """Светлота цвета от 0 до 1 — по ней отличаем светлую тему от тёмной."""
    value = (color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return 0.0
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def is_light(theme: str) -> bool:
    """Светлая ли тема. Спрашиваем у фона, а не у названия: тем стало много."""
    return luminance(palette(theme)["bg"]) > 0.5


def check_icon() -> str:
    """Путь к картинке-галочке для чекбоксов (создаётся один раз рядом с данными)."""
    from ..appicon import write_check
    from ..config import data_dir

    path = data_dir() / "check.png"
    try:
        if not path.exists():
            write_check(path)
    except Exception:
        return ""
    # В таблице стилей Qt путь пишется через прямые слэши.
    return str(path).replace("\\", "/")


def pattern_image(theme: str) -> str:
    """Плитка фонового узора для пиксельного стиля (создаётся один раз)."""
    from ..appicon import write_pattern
    from ..config import data_dir

    colors = palette(theme)
    path = data_dir() / ("stripes-%s.png" % theme)
    try:
        if not path.exists():
            write_pattern(
            path, colors["bg"], colors["text"], 14 if is_light(theme) else 11
        )
    except Exception:
        return ""
    return str(path).replace("\\", "/")


def _scaled_css(css: str) -> str:
    """Умножает все размеры в пикселях на масштаб интерфейса.

    Так один множитель меняет и отступы, и шрифты, и толщину линий — вместо
    второго комплекта размеров на каждый случай.
    """
    if abs(_scale - 1.0) < 0.001:
        return css
    return re.sub(r"(\d+)px", lambda found: "%dpx" % px(int(found.group(1)), 1), css)


def stylesheet(theme: str, style: str | None = None) -> str:
    if style is not None:
        set_style(style)
    c = palette(theme)
    set_colors(c)
    c["ui"] = pixel_family() if is_pixel() else ui_family()
    c["mono"] = pixel_family() if is_pixel() else mono_family()
    c["accent_family"] = accent_family()
    c["section_size"] = 12 if is_pixel() else 11
    c["section_spacing"] = 1.0 if is_pixel() else 1.5
    c["r_input"] = radius("input")
    c["r_button"] = radius("button")
    c["r_small"] = radius("small")
    c["r_nav"] = radius("nav")
    # В мягком стиле шрифт крупнее: системный шрифт мельче пиксельного при
    # одинаковом размере, и без прибавки интерфейс выглядел жиденьким.
    c["font_size"] = 14 if is_pixel() else 15
    c["item_gap"] = 7 + line_extra()
    pattern = pattern_image(theme) if is_pixel() else ""
    # Только сокращённая запись background замащивает картинку: с отдельным
    # background-image Qt рисует плитку один раз в углу.
    c["pattern_rule"] = ('url("%s") repeat' % pattern) if pattern else ""
    c["letter_spacing"] = "letter-spacing: 0.4px;" if is_pixel() else ""
    icon = check_icon()
    c["check_rule"] = ('image: url("%s");' % icon) if icon else ""
    return _scaled_css("""
* {
    outline: none;
}
QWidget {
    background: %(bg)s;
    color: %(text)s;
    font-family: "%(ui)s";
    font-size: %(font_size)dpx;
    %(letter_spacing)s
}
QMainWindow, QDialog {
    background: %(bg)s;
}

/* Подписи не должны закрашивать собой фон — иначе поверх узора появляются
   прямоугольные заплатки. */
QLabel { background: transparent; }

/* Холст с фоновым узором и прозрачные контейнеры поверх него. */
/* Узор рисует каждая панель у себя: иначе непрозрачные контейнеры и
   разделитель закрывают собой холст. */
QWidget#canvas, QWidget#appHeader, QWidget#bodyArea, QWidget#centerArea,
QWidget#sidebarPanel, QWidget#detailPanel, QSplitter {
    background: %(bg)s %(pattern_rule)s;
}
QWidget#productsBox { background: transparent; }
QScrollArea#productsScroll { background: transparent; border: none; }
QScrollArea#productsScroll > QWidget > QWidget { background: transparent; }

/* --- Полосы прокрутки: тонкие, без стрелок --- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: %(border)s;
    border-radius: %(r_small)dpx;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover { background: %(text_faint)s; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: %(r_small)dpx; min-width: 40px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --- Поля ввода --- */
QLineEdit, QTextEdit, QPlainTextEdit, QDateEdit, QComboBox, QSpinBox, QTimeEdit {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(r_input)dpx;
    padding: 8px 11px;
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QDateEdit:focus,
QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 1px solid %(accent)s;
}
QLineEdit::placeholder { color: %(text_faint)s; }
QLineEdit:disabled, QDateEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QTimeEdit:disabled, QPlainTextEdit:disabled {
    background: %(surface_alt)s;
    color: %(text_faint)s;
    border-color: %(border_soft)s;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: %(surface_alt)s;
    border: 1px solid %(border)s;
    selection-background-color: %(accent_soft)s;
    selection-color: %(text)s;
    padding: 4px;
}
QDateEdit::up-button, QDateEdit::down-button,
QSpinBox::up-button, QSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button { width: 14px; border: none; }

/* --- Кнопки --- */
QPushButton {
    background: %(surface_alt)s;
    border: 1px solid %(border)s;
    border-radius: %(r_button)dpx;
    padding: 8px 15px;
    color: %(text)s;
}
QPushButton:hover { background: %(surface_hover)s; border-color: %(text_faint)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(text_faint)s; background: %(surface)s; }
QPushButton[accent="true"] {
    background: %(accent)s;
    border: 1px solid %(accent)s;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton[accent="true"]:hover { background: %(accent)s; border-color: %(text)s; }
QPushButton[flat="true"] {
    background: transparent;
    border: none;
    color: %(text_dim)s;
    padding: 5px 8px;
}
QPushButton[flat="true"]:hover { color: %(text)s; background: %(surface_alt)s; }
QPushButton[flat="true"][active="true"] {
    color: %(text)s;
    background: %(surface_alt)s;
    font-weight: 600;
}
QPushButton[danger="true"] { color: %(danger)s; }
/* Крошечные кнопки у подпунктов: только знак, без рамки. */
QPushButton[tiny="true"] {
    background: transparent;
    border: none;
    color: %(text_faint)s;
    padding: 0 4px;
    min-width: 16px;
}
QPushButton[tiny="true"]:hover { color: %(text)s; background: %(surface_alt)s; }

/* Поле, которое выглядит как текст: правка названия подпункта на месте. */
QLineEdit[seamless="true"] {
    background: transparent;
    border: none;
    border-bottom: 1px solid transparent;
    border-radius: 0;
    padding: 1px 0;
}
QLineEdit[seamless="true"]:hover { border-bottom: 1px solid %(border)s; }
QLineEdit[seamless="true"]:focus { border-bottom: 1px solid %(accent)s; }

/* --- Боковые фильтры --- */
QPushButton[nav="true"] {
    background: transparent;
    border: none;
    border-radius: %(r_nav)dpx;
    padding: 8px 10px;
    text-align: left;
    color: %(text_dim)s;
}
QPushButton[nav="true"]:hover { background: %(surface_alt)s; color: %(text)s; }
QPushButton[nav="true"][active="true"] {
    background: %(surface_alt)s;
    color: %(text)s;
    font-weight: 600;
}

/* --- Списки --- */
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item { border: none; margin: 0 0 %(item_gap)dpx 0; }
QListWidget::item:selected { background: transparent; }

/* --- Прочее --- */
QLabel[dim="true"] { color: %(text_dim)s; }
QLabel[faint="true"] { color: %(text_faint)s; }
QLabel[mono="true"] { font-family: "%(mono)s"; color: %(text_dim)s; }
QLabel[section="true"] {
    font-family: "%(accent_family)s";
    font-size: %(section_size)dpx;
    color: %(text_faint)s;
    letter-spacing: %(section_spacing)spx;
}
QFrame[hline="true"] { background: %(border_soft)s; max-height: 1px; border: none; }
/* Полоска под шапкой — сплошная акцентная линия во всю ширину. */
QFrame[headline="true"] {
    background: %(accent)s;
    max-height: 1px;
    border: none;
}
QFrame[vline="true"] { background: %(border_soft)s; max-width: 1px; border: none; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid %(border)s;
    border-radius: %(r_small)dpx;
    background: %(surface)s;
}
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked {
    background: %(accent)s;
    border-color: %(accent)s;
    %(check_rule)s
}
QCheckBox:disabled { color: %(text_faint)s; }

/* --- Календарь в полях с датой --- */
QCalendarWidget QWidget { alternate-background-color: %(surface)s; }
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: %(surface_alt)s;
    border-bottom: 1px solid %(border)s;
}
QCalendarWidget QToolButton {
    background: transparent;
    border: none;
    border-radius: %(r_small)dpx;
    color: %(text)s;
    padding: 6px 10px;
    margin: 3px;
}
QCalendarWidget QToolButton:hover { background: %(surface_hover)s; }
QCalendarWidget QAbstractItemView:enabled {
    background: %(surface)s;
    color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
    outline: none;
}
QCalendarWidget QAbstractItemView:disabled { color: %(text_faint)s; }
QCalendarWidget QSpinBox {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(r_small)dpx;
}

QSplitter::handle { background: %(border_soft)s; }
QSplitter::handle:horizontal { width: 1px; }

QToolTip {
    background: %(surface_alt)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    padding: 5px 7px;
}

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    color: %(text_dim)s;
    padding: 8px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; }

QMenu {
    background: %(surface_alt)s;
    border: 1px solid %(border)s;
    padding: 5px;
}
QMenu::item { padding: 7px 22px 7px 14px; border-radius: %(r_small)dpx; }
QMenu::item:selected { background: %(surface_hover)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 6px; }
""" % c)
