"""Оформление: терминал. Палитры, шрифт и таблица стилей.

Программа выглядит как экран текстового режима: весь текст набран шрифтом IBM
VGA, панели очерчены двойной рамкой, выбранное показано инверсией — тёмным по
светлому, — а графики собраны из знаков █ ▄ ░. Тем семь: три светятся, как
настоящие мониторы, четыре спокойнее, без свечения.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QFont, QFontDatabase

# --- Палитры ------------------------------------------------------------------
# Тема задаётся десятком цветов, а не двумя десятками: «чернила» и их тусклые
# ступени, яркий цвет для выделенного, плашка-инверсия и один тревожный цвет.
# Остальные ключи, которые ждёт код (поверхности, мягкие подложки), выводятся
# из них — так темы не расходятся между собой.


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


def _terminal(
    ground: str, ink: str, bright: str, dim: str, faint: str, ghost: str,
    accent: str, slab_ink: str, alert: str, glow: bool, crt: bool,
) -> dict[str, str]:
    """Полная палитра темы из её основных цветов."""
    return {
        # Свои цвета терминала.
        "ground": ground,
        "ink": ink,
        "bright": bright,
        "dim": dim,
        "faint": faint,
        "ghost": ghost,
        "slab_ink": slab_ink,
        "alert": alert,
        "glow": "1" if glow else "",
        "crt": "1" if crt else "",
        # Ключи, которыми пользуется остальной код.
        "bg": ground,
        "surface": ground,
        "surface_alt": ghost,
        "surface_hover": ghost,
        "border": dim,
        "border_soft": faint,
        "text": ink,
        "text_dim": dim,
        "text_faint": mix(dim, faint, 0.35),
        "accent": accent,
        "accent_soft": ghost,
        "danger": alert,
        "danger_soft": mix(alert, ground, 0.18),
        "warning": bright,
        "warning_soft": mix(bright, ground, 0.14),
        "success": bright,
        "success_soft": mix(bright, ground, 0.12),
        "info": ink,
        "route": bright,
    }


AMBER = _terminal("#120A00", "#FFB000", "#FFE2A0", "#A06E00", "#5C3F00", "#2A1C00",
                  "#FFB000", "#120A00", "#FF5A2E", glow=True, crt=True)
PHOSPHOR = _terminal("#04110A", "#5BE38A", "#C8FFD8", "#2F9A57", "#1C5A33", "#0B2616",
                     "#5BE38A", "#04110A", "#FF6B5A", glow=True, crt=True)
WHITE = _terminal("#0F1113", "#D9DEE3", "#FFFFFF", "#8A939C", "#3C434A", "#1A1E22",
                  "#D9DEE3", "#0F1113", "#FF6B5A", glow=True, crt=True)
GRAPHITE = _terminal("#1C1B19", "#D8D2C4", "#F4EFE4", "#948D7F", "#4A463F", "#26241F",
                     "#C9A86A", "#1C1B19", "#E0775A", glow=False, crt=False)
NIGHT = _terminal("#0E1622", "#A9C4E2", "#E3EEF9", "#6E89A6", "#34465C", "#16212F",
                  "#E3B868", "#0E1622", "#F07A6A", glow=False, crt=False)
PAPER = _terminal("#EFE7D6", "#2E2618", "#120D05", "#76674F", "#C9BCA3", "#E4D9C3",
                  "#A4522A", "#FFF6E8", "#B3261E", glow=False, crt=False)
ROSE = _terminal("#201519", "#F4C2CF", "#FFE6EE", "#B98A99", "#5E4450", "#2C1D23",
                 "#F49AB4", "#201519", "#FF9A5C", glow=True, crt=False)

# Палитра по умолчанию — янтарный терминал. Старое имя оставлено для кода,
# которому нужна «какая-нибудь» полная палитра: набор ключей у всех тем один.
DARK = AMBER

# Порядок важен: в таком виде темы и показываются в настройках.
PALETTES = {
    "amber": AMBER,
    "phosphor": PHOSPHOR,
    "white": WHITE,
    "graphite": GRAPHITE,
    "night": NIGHT,
    "paper": PAPER,
    "rose": ROSE,
}

PALETTE_LABELS = {
    "amber": "Янтарь",
    "phosphor": "Люминофор",
    "white": "Белый фосфор",
    "graphite": "Графит",
    "night": "Ночная синь",
    "paper": "Бумага",
    "rose": "Нежный розовый",
}

# Темы прошлых версий: их имя могло остаться в настройках. Каждая уходит в
# ближайшую по духу из нынешних.
PALETTE_ALIASES = {
    "dark": "amber",
    "ember": "amber",
    "light": "paper",
    "green": "phosphor",
    "ice": "night",
    "mono": "white",
}

DEFAULT_THEME = "amber"

# Важность на экране — клетки █, а не радуга: ярче становится только самая
# высокая ступень, она «горит». Ключ — цвет закрашенных клеток.
PRIORITY_COLOR_KEYS = {
    0: "text_dim",
    1: "text",
    2: "text",
    3: "text",
    4: "danger",
}

# --- Стиль --------------------------------------------------------------------
# Стиль теперь один — «терминал». Имена старых стилей оставлены, чтобы код и
# настройки прошлых версий не спотыкались: любой из них открывается терминалом.
STYLE_SOFT = "soft"
STYLE_PIXEL = "pixel"

STYLE_LABELS = {
    STYLE_PIXEL: "Терминал",
}

# Скруглений нет ни у одного элемента: экран текстового режима сплошь прямоугольный.
RADII = {
    STYLE_PIXEL: {"card": 0, "input": 0, "button": 0, "pill": 0, "small": 0, "nav": 0},
}

# Ступенчатое скругление карточек прошлых версий.
PIXEL_CORNER = 6
PIXEL_STEP = 2

_style = STYLE_PIXEL


def set_style(name: str) -> None:
    """Стиль один; вызов оставлен ради совместимости со старым кодом."""
    global _style
    _style = STYLE_PIXEL


def current_style() -> str:
    return _style


def is_pixel() -> bool:
    return True


def radius(kind: str = "card") -> int:
    return 0


# --- Масштаб ------------------------------------------------------------------
# За ноутбуком хочется интерфейс помельче, за большим монитором — покрупнее.
# Масштабируются размеры шрифтов и все расстояния в таблице стилей: один
# множитель вместо второго комплекта размеров на каждый случай.

SCALE_STEPS = (60, 70, 80, 90, 100, 110, 125, 150)
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


_colors: dict[str, str] = dict(AMBER)


def set_colors(values: dict[str, str]) -> None:
    """Запоминает цвета применённой темы.

    Их спрашивают виджеты, которые рисуют себя сами и не получают палитру
    через конструктор, — например, фон с шумом.
    """
    global _colors
    _colors = dict(values)


def colors() -> dict[str, str]:
    return dict(_colors)


# --- Шрифт --------------------------------------------------------------------
# Весь интерфейс набран IBM VGA 8×16 — шрифтом текстового режима: он едет с
# программой, поэтому выглядит одинаково везде. Чётче всего он на 16 пикселях
# и на кратных им; заголовки — 24. Для заголовков можно выбрать свой шрифт.

TERMINAL_FAMILY = "PxPlus IBM VGA 8x16"
BASE_PX = 16
HEADING_PX = 24

# Шрифты для заголовков, которые могут оказаться в системе или в папке fonts.
PIXEL_CANDIDATES = [
    "Pixel Font Rus",
    "Minecraft Rus",
    "Minecraft",
    "Monocraft",
    "Departure Mono",
    "Press Start 2P",
]

# Если шрифта поставки почему-то нет — обычный моноширинный.
MONO_CANDIDATES = [
    TERMINAL_FAMILY,
    "Consolas",
    "Cascadia Mono",
    "Lucida Console",
    "DejaVu Sans Mono",
    "Courier New",
]

UI_CANDIDATES = MONO_CANDIDATES


def _pick(candidates: list[str], fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def mono_family() -> str:
    """Шрифт всего интерфейса — терминальный."""
    return _pick(MONO_CANDIDATES, "monospace")


def ui_family() -> str:
    return mono_family()


def body_family() -> str:
    return mono_family()


# Шрифт заголовков, выбранный в настройках (пусто — тот же терминальный).
_preferred_pixel = ""


def set_preferred_pixel(family: str) -> None:
    global _preferred_pixel
    _preferred_pixel = (family or "").strip()


def pixel_candidates() -> list[str]:
    """Что можно взять для заголовков: свои файлы, потом знакомые шрифты."""
    from ..fonts import loaded_families

    found: list[str] = []
    for family in loaded_families() + PIXEL_CANDIDATES:
        if family and family not in found:
            found.append(family)
    return found


def pixel_family() -> str:
    """Шрифт заголовков: выбранный в настройках, иначе терминальный."""
    if _preferred_pixel and _preferred_pixel in set(QFontDatabase.families()):
        return _preferred_pixel
    return mono_family()


def heading_family() -> str:
    return pixel_family()


def has_pixel_font() -> bool:
    return pixel_family() != mono_family()


def accent_family() -> str:
    """Подписи, счётчики и метки — тем же терминальным шрифтом."""
    return mono_family()


def _size_px(size: int) -> int:
    """Старые размеры в пунктах — в две ступени терминала: текст и заголовок."""
    return px(HEADING_PX if size >= 13 else BASE_PX, 8)


def _font(family: str, size_px: int, bold: bool = False) -> QFont:
    font = QFont(family)
    font.setPixelSize(size_px)
    font.setBold(bold)
    # Растровый шрифт без сглаживания чётче: пиксели не размазываются.
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def mono_font(size: int = 9, bold: bool = False, spacing: float = 0.0) -> QFont:
    """Текст интерфейса: метки, даты, тексты отчётов."""
    font = _font(mono_family(), _size_px(size), bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def accent_font(size: int = 9, bold: bool = False, spacing: float = 0.0) -> QFont:
    """Подписи и счётчики. Крупные размеры — шрифтом заголовков."""
    family = heading_family() if size >= 13 else accent_family()
    font = _font(family, _size_px(size), bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    return _font(heading_family() if size >= 13 else ui_family(), _size_px(size), bold)


def heading_font() -> QFont:
    return _font(heading_family(), px(HEADING_PX, 12))


def heading_css() -> str:
    return 'font-family: "%s"; font-size: %dpx; letter-spacing: 0;' % (
        heading_family(), px(HEADING_PX, 12))


def title_px() -> int:
    """Размер названия задачи в пикселях — ровно строка терминала."""
    return px(BASE_PX, 8)


def title_font(bold: bool = False) -> QFont:
    # Жирного начертания у растрового шрифта нет: Qt нарастил бы его сам и
    # испортил буквы. Важность видна по клеткам, а не по толщине.
    return _font(ui_family(), title_px())


def title_css(bold: bool = False) -> str:
    """Тот же шрифт для таблицы стилей самой метки."""
    return 'font-family: "%s"; font-size: %dpx; font-weight: 400; letter-spacing: 0;' % (
        ui_family(), title_px())


def small_font_px() -> int:
    """У терминала один размер строки: мелкие метки — те же 16 пикселей."""
    return px(BASE_PX, 8)


def small_font() -> QFont:
    return _font(accent_family(), small_font_px())


def small_font_css() -> str:
    """Тот же шрифт, но для таблицы стилей самого виджета."""
    return 'font-family: "%s"; font-size: %dpx; letter-spacing: 0;' % (
        accent_family(), small_font_px())


def label_css(size: int = BASE_PX) -> str:
    """Шрифт надписи для собственных стилей виджета."""
    return 'font-family: "%s"; font-size: %dpx; letter-spacing: 0;' % (
        accent_family(), px(size, 8))


# Прибавка к размеру шрифта прошлых версий; терминалу не нужна.
FONT_BUMP = 0


def nav_padding() -> tuple[int, int]:
    """Отступы пункта бокового меню: по горизонтали и по вертикали."""
    return (px(4), px(2))


def nav_spacing() -> int:
    """Пункты меню — строки терминала: стоят вплотную."""
    return 0


def section_gap() -> int:
    """Отступ между разделами бокового меню — одна пустая строка."""
    return px(12)


def line_height_percent() -> int:
    """Межстрочный интервал: 20 пикселей на 16-пиксельную строку."""
    return 125


def line_extra() -> int:
    """Воздух между строками внутри карточек, в пикселях."""
    return px(4, 0)


def multiline(text: str) -> str:
    """Многострочный текст с нужным межстрочным интервалом (как HTML)."""
    body = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
    return '<div style="line-height: %d%%">%s</div>' % (line_height_percent(), body)


def apply_text_spacing(edit) -> None:
    """Разводит строки в текстовом поле (отчёты, выгрузки)."""
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


# --- Знаки ---------------------------------------------------------------------
# В IBM VGA есть и рамки, и блоки, и стрелки. Но шрифт заголовков может быть
# любым, а в пиксельных шрифтах таких знаков обычно нет: недостающий знак
# рисуется тем шрифтом, где он есть.

GLYPH_FALLBACKS = (
    TERMINAL_FAMILY,
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
    "full": ("█", "#"),      # полная клетка столбика
    "half": ("▄", ":"),      # половинка снизу
    "base": ("─", "_"),      # линия основания
    "corner_tl": ("┌", "+"),
    "corner_tr": ("┐", "+"),
    "corner_bl": ("└", "+"),
    "corner_br": ("┘", "+"),
    "line_h": ("─", "-"),
    "line_v": ("│", "|"),
    "dot": ("·", "."),
    "arrow": ("›", ">"),
    "shade": ("░", "."),     # пустая клетка шкалы
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


def tint(color: str, alpha: float) -> str:
    """Полупрозрачная версия цвета для подложек и рамок — строка rgba(...)."""
    value = (color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "transparent"
    return "rgba(%d, %d, %d, %d)" % (red, green, blue, max(0, min(255, round(alpha * 255))))


def qcolor(value: str):
    """QColor из «#rrggbb» или «rgba(r, g, b, a)».

    QColor сам понимает только первое, а строку rgba(...) молча делает чёрной.
    """
    from PySide6.QtGui import QColor

    text = (value or "").strip()
    if text.startswith("rgba(") and text.endswith(")"):
        try:
            red, green, blue, alpha = (int(float(part)) for part in text[5:-1].split(","))
        except ValueError:
            return QColor(0, 0, 0, 0)
        return QColor(red, green, blue, alpha)
    if text == "transparent":
        return QColor(0, 0, 0, 0)
    return QColor(text)


def theme_name(theme: str) -> str:
    """Имя темы из нынешних: старые и незнакомые уходят в ближайшую."""
    theme = PALETTE_ALIASES.get(theme, theme)
    return theme if theme in PALETTES else DEFAULT_THEME


def palette(theme: str) -> dict[str, str]:
    """Цвета темы. Незнакомое имя — янтарь."""
    return dict(PALETTES[theme_name(theme)])


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
    """Светлая ли тема. Спрашиваем у фона, а не у названия."""
    return luminance(palette(theme)["bg"]) > 0.5


def has_glow(theme: str) -> bool:
    """Светятся ли буквы: у мониторов — да, у спокойных тем — нет."""
    return bool(palette(theme)["glow"])


def has_scanlines(theme: str) -> bool:
    """Полосы развёртки — только у тем-мониторов."""
    return bool(palette(theme)["crt"])


def check_icon(theme: str = DEFAULT_THEME) -> str:
    """Путь к галочке для чекбоксов: тёмная галочка на плашке цвета темы."""
    from ..appicon import write_check
    from ..config import data_dir

    name = theme_name(theme)
    path = data_dir() / ("check-%s.png" % name)
    try:
        if not path.exists():
            write_check(path, palette(name)["slab_ink"])
    except Exception:
        return ""
    # В таблице стилей Qt путь пишется через прямые слэши.
    return str(path).replace("\\", "/")


def pattern_image(theme: str) -> str:
    """Плитка фона прошлых версий. Терминалу не нужна: шум рисует холст."""
    return ""


def _scaled_css(css: str) -> str:
    """Умножает все размеры в пикселях на масштаб интерфейса."""
    if abs(_scale - 1.0) < 0.001:
        return css
    return re.sub(r"(\d+)px", lambda found: "%dpx" % px(int(found.group(1)), 1), css)


def stylesheet(theme: str, style: str | None = None) -> str:
    c = palette(theme)
    set_colors(c)
    c["font"] = mono_family()
    c["heading"] = heading_family()
    c["font_size"] = BASE_PX
    icon = check_icon(theme)
    c["check_rule"] = ('image: url("%s");' % icon) if icon else ""
    return _scaled_css("""
* {
    outline: none;
}
QWidget {
    background: %(bg)s;
    color: %(text)s;
    font-family: "%(font)s";
    font-size: %(font_size)dpx;
}
QMainWindow, QDialog {
    background: %(bg)s;
}

/* Подписи не закрашивают фон: под ними может быть шум холста. */
QLabel { background: transparent; }

QWidget#productsBox { background: transparent; }
QScrollArea#productsScroll { background: transparent; border: none; }
QScrollArea#productsScroll > QWidget > QWidget { background: transparent; }

/* --- Полосы прокрутки: в нитку, без стрелок --- */
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: %(faint)s; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: %(dim)s; }
QScrollBar:horizontal { background: transparent; height: 6px; }
QScrollBar::handle:horizontal { background: %(faint)s; min-width: 40px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --- Поля ввода: тёмная подложка и рамка, в фокусе рамка светлеет --- */
QLineEdit, QTextEdit, QPlainTextEdit, QDateEdit, QComboBox, QSpinBox, QTimeEdit {
    background: %(ghost)s;
    color: %(text)s;
    border: 2px solid %(dim)s;
    padding: 4px 8px;
    selection-background-color: %(accent)s;
    selection-color: %(slab_ink)s;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QDateEdit:focus,
QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 2px solid %(bright)s;
}
QLineEdit::placeholder { color: %(text_faint)s; }
QLineEdit:disabled, QDateEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QTimeEdit:disabled, QPlainTextEdit:disabled {
    background: %(bg)s;
    color: %(faint)s;
    border-color: %(faint)s;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: %(bg)s;
    border: 2px solid %(dim)s;
    selection-background-color: %(accent)s;
    selection-color: %(slab_ink)s;
    padding: 2px;
}
QDateEdit::up-button, QDateEdit::down-button,
QSpinBox::up-button, QSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button { width: 14px; border: none; }

/* --- Кнопки: рамка, при наведении — инверсия, главная — сплошной плашкой --- */
QPushButton {
    background: transparent;
    border: 2px solid %(dim)s;
    padding: 3px 10px;
    color: %(text)s;
}
QPushButton:hover, QPushButton:focus { border-color: %(bright)s; color: %(bright)s; }
QPushButton:pressed { background: %(accent)s; color: %(slab_ink)s; border-color: %(accent)s; }
QPushButton:disabled { color: %(faint)s; border-color: %(faint)s; }
QPushButton[accent="true"] {
    background: %(accent)s;
    border: 2px solid %(accent)s;
    color: %(slab_ink)s;
}
QPushButton[accent="true"]:hover, QPushButton[accent="true"]:focus {
    background: %(bright)s;
    border-color: %(bright)s;
    color: %(slab_ink)s;
}
QPushButton[flat="true"] {
    background: transparent;
    border: 2px solid transparent;
    color: %(text)s;
    padding: 2px 6px;
}
QPushButton[flat="true"]:hover, QPushButton[flat="true"]:focus {
    background: %(accent)s;
    color: %(slab_ink)s;
    border-color: %(accent)s;
}
QPushButton[flat="true"][active="true"] {
    background: %(accent)s;
    color: %(slab_ink)s;
    border-color: %(accent)s;
}
QPushButton[danger="true"] { color: %(danger)s; border-color: %(danger)s; }
/* Крошечные кнопки у подпунктов: только знак, без рамки. */
QPushButton[tiny="true"] {
    background: transparent;
    border: none;
    color: %(text_dim)s;
    padding: 0 4px;
    min-width: 16px;
}
QPushButton[tiny="true"]:hover { color: %(bright)s; background: transparent; }

/* Строка ввода внизу окна: голый текст после приглашения. */
QLineEdit[prompt="true"] {
    background: transparent;
    border: none;
    color: %(bright)s;
    padding: 6px 0;
}
QLineEdit[prompt="true"]:focus { border: none; }
QPushButton[menu="true"] { padding: 0 8px; }

/* Поле, которое выглядит как текст: правка названия подпункта на месте. */
QLineEdit[seamless="true"] {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 0;
}
QLineEdit[seamless="true"]:hover { border-bottom: 2px solid %(faint)s; }
QLineEdit[seamless="true"]:focus { border-bottom: 2px solid %(bright)s; }

/* --- Списки --- */
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item { border: none; margin: 0; }
QListWidget::item:selected { background: transparent; }

/* --- Прочее --- */
QLabel[dim="true"] { color: %(text_dim)s; }
QLabel[faint="true"] { color: %(text_faint)s; }
QLabel[mono="true"] { color: %(text_dim)s; }
QLabel[section="true"] { color: %(text_dim)s; }
QLabel[heading="true"] { font-family: "%(heading)s"; font-size: 24px; color: %(bright)s; }
QFrame[hline="true"] { background: %(faint)s; min-height: 2px; max-height: 2px; border: none; }
QFrame[headline="true"] { background: transparent; max-height: 0px; border: none; }
QFrame[vline="true"] { background: %(faint)s; max-width: 2px; border: none; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 2px solid %(dim)s;
    background: %(ghost)s;
}
QCheckBox::indicator:hover { border-color: %(bright)s; }
QCheckBox::indicator:checked {
    background: %(accent)s;
    border-color: %(accent)s;
    %(check_rule)s
}
QCheckBox:disabled { color: %(faint)s; }
QRadioButton { spacing: 8px; }

/* --- Календарь в полях с датой --- */
QCalendarWidget QWidget { alternate-background-color: %(bg)s; }
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: %(bg)s;
    border-bottom: 2px solid %(faint)s;
}
QCalendarWidget QToolButton {
    background: transparent;
    border: none;
    color: %(bright)s;
    padding: 4px 8px;
    margin: 2px;
}
QCalendarWidget QToolButton:hover { background: %(accent)s; color: %(slab_ink)s; }
QCalendarWidget QAbstractItemView:enabled {
    background: %(bg)s;
    color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: %(slab_ink)s;
    outline: none;
}
QCalendarWidget QAbstractItemView:disabled { color: %(faint)s; }
QCalendarWidget QSpinBox {
    background: %(bg)s;
    border: 2px solid %(dim)s;
}

QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 12px; }

QToolTip {
    background: %(bg)s;
    color: %(text)s;
    border: 2px solid %(dim)s;
    padding: 4px 6px;
}

QTabWidget::pane { border: none; border-top: 2px solid %(faint)s; }
QTabBar::tab {
    background: transparent;
    color: %(text)s;
    padding: 3px 12px;
    margin-right: 4px;
}
QTabBar::tab:hover { color: %(bright)s; }
QTabBar::tab:selected { background: %(accent)s; color: %(slab_ink)s; }

QMenu {
    background: %(bg)s;
    border: 4px double %(dim)s;
    padding: 4px;
}
QMenu::item { padding: 3px 20px 3px 12px; }
QMenu::item:selected { background: %(accent)s; color: %(slab_ink)s; }
QMenu::separator { height: 2px; background: %(faint)s; margin: 4px 6px; }

QStatusBar {
    background: %(bg)s;
    color: %(text_dim)s;
    border-top: 2px solid %(faint)s;
}
QStatusBar QLabel { color: %(text_dim)s; }

QProgressBar {
    background: %(ghost)s;
    border: 2px solid %(dim)s;
    color: %(text)s;
    text-align: center;
}
QProgressBar::chunk { background: %(accent)s; }

QGroupBox {
    border: 4px double %(dim)s;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: %(bright)s;
    background: %(bg)s;
}
""" % c)
