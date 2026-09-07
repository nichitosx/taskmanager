"""Оформление: палитра, шрифты и таблица стилей.

Минимализм: тёплый почти-чёрный фон, один акцентный цвет, тонкие линии вместо
рамок и теней, моноширинные подписи капслоком для служебного текста.
"""

from __future__ import annotations

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

PRIORITY_COLOR_KEYS = {
    0: "text_faint",
    1: "info",
    2: "warning",
    3: "danger",
}

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
    font = QFont(mono_family(), size)
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont(ui_family(), size)
    font.setBold(bold)
    return font


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
    return dict(LIGHT if theme == "light" else DARK)


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


def stylesheet(theme: str) -> str:
    c = palette(theme)
    c["ui"] = ui_family()
    c["mono"] = mono_family()
    icon = check_icon()
    c["check_rule"] = ('image: url("%s");' % icon) if icon else ""
    return """
* {
    outline: none;
}
QWidget {
    background: %(bg)s;
    color: %(text)s;
    font-family: "%(ui)s";
    font-size: 13px;
}
QMainWindow, QDialog {
    background: %(bg)s;
}

/* --- Полосы прокрутки: тонкие, без стрелок --- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: %(border)s;
    border-radius: 5px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover { background: %(text_faint)s; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 5px; min-width: 40px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --- Поля ввода --- */
QLineEdit, QTextEdit, QPlainTextEdit, QDateEdit, QComboBox, QSpinBox, QTimeEdit {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
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
    border-radius: 8px;
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

/* --- Боковые фильтры --- */
QPushButton[nav="true"] {
    background: transparent;
    border: none;
    border-radius: 6px;
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
QListWidget::item { border: none; margin: 0 0 7px 0; }
QListWidget::item:selected { background: transparent; }

/* --- Прочее --- */
QLabel[dim="true"] { color: %(text_dim)s; }
QLabel[faint="true"] { color: %(text_faint)s; }
QLabel[mono="true"] { font-family: "%(mono)s"; color: %(text_dim)s; }
QLabel[section="true"] {
    font-family: "%(mono)s";
    font-size: 10px;
    color: %(text_faint)s;
    letter-spacing: 1.5px;
}
QFrame[hline="true"] { background: %(border_soft)s; max-height: 1px; border: none; }
QFrame[vline="true"] { background: %(border_soft)s; max-width: 1px; border: none; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid %(border)s;
    border-radius: 5px;
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
    border-radius: 6px;
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
    border-radius: 6px;
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
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 4px; }
QMenu::item:selected { background: %(surface_hover)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 6px; }
""" % c
