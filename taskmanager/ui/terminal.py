"""Элементы терминального экрана: фон с шумом, панели в двойной рамке, бегущая
строка, меню, строка ввода и полоса F-клавиш.

Всё, что здесь нарисовано знаками, набрано тем же шрифтом IBM VGA, что и
текст: рамки, отточия, блоки шкал. Поэтому экран держит сетку, как настоящий
текстовый режим, и не расползается от смены шрифта.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProxyStyle,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from . import theme


def _qcolor(value: str, alpha: float = 1.0) -> QColor:
    color = theme.qcolor(value)
    if alpha < 1.0:
        color.setAlphaF(color.alphaF() * alpha)
    return color


def cell_width(font=None) -> int:
    """Ширина одной клетки текстового экрана."""
    return QFontMetrics(font or theme.mono_font()).horizontalAdvance("0")


# --- Фон -------------------------------------------------------------------------

# Уровни шума: доля непрозрачности знаков фона.
NOISE_LEVELS = {"off": 0.0, "quiet": 0.10, "loud": 0.20}
NOISE_LABELS = {"off": "выключен", "quiet": "тихий", "loud": "заметный"}
SCANLINE_MODES = {"theme": "как у темы", "on": "включены", "off": "выключены"}

# Из чего набран шум и с какой частотой встречается каждый знак.
_NOISE_MIX = (
    (0.80, " "),
    (0.88, "\u00b7"),
    (0.92, ":"),
    (0.96, "\u2591"),
    (0.975, "\u2592"),
    (0.99, "0"),
    (1.01, "1"),
)


def noise_lines(seed: int, rows: int, columns: int) -> list[str]:
    """Строки шума. Одинаковые при каждом запуске: фон не скачет от обновлений."""
    rng = random.Random(seed)
    lines = []
    for _ in range(rows):
        chars = []
        for _ in range(columns):
            value = rng.random()
            for limit, char in _NOISE_MIX:
                if value < limit:
                    chars.append(char)
                    break
        lines.append("".join(chars))
    return lines


class TerminalCanvas(QWidget):
    """Подложка окна: цвет экрана и мерцающий шум из знаков.

    Шум — два слоя, которые медленно перетекают друг в друга. Каждый слой
    рисуется в картинку один раз, а в движении меняется только прозрачность:
    так фон живой, но почти ничего не стоит. Перерисовываются лишь просветы
    между панелями — под панелями шума всё равно не видно.
    """

    PERIOD = 6.0       # секунд на полный цикл мерцания
    FRAME_MS = 250

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("canvas")
        self.colors = colors
        self._level = NOISE_LEVELS["quiet"]
        self._motion = True
        self._layers: list[QPixmap] = []
        self._layers_key = None
        self._panels: list[QWidget] = []
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setAutoFillBackground(False)

    # --- Настройка -------------------------------------------------------------

    def configure(self, colors: dict[str, str], noise: str, motion: bool) -> None:
        self.colors = colors
        self._level = NOISE_LEVELS.get(noise, NOISE_LEVELS["quiet"])
        self._motion = bool(motion)
        self._layers_key = None
        self._sync_timer()
        self.update()

    def add_panel(self, widget: QWidget) -> None:
        """Панель закрывает шум: её область при мерцании не перерисовываем."""
        self._panels.append(widget)

    def noise_level(self) -> float:
        return self._level

    def is_moving(self) -> bool:
        return self._timer.isActive()

    # --- Движение --------------------------------------------------------------

    def _sync_timer(self) -> None:
        if self._motion and self._level > 0 and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Свёрнутое в трей окно не должно тратить ни такта.
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if not self.window().isVisible() or self.window().isMinimized():
            return
        from PySide6.QtGui import QRegion

        region = QRegion(self.rect())
        for panel in self._panels:
            if panel.isVisible():
                top_left = panel.mapTo(self, panel.rect().topLeft())
                region -= QRegion(QRect(top_left, panel.size()))
        self.update(region)

    def phase(self) -> float:
        """Доля первого слоя от 0 до 1; второй слой — дополнение до единицы."""
        if not self._motion:
            return 1.0
        elapsed = time.monotonic() - self._started
        return 0.5 + 0.5 * math.cos(2 * math.pi * elapsed / self.PERIOD)

    # --- Рисование --------------------------------------------------------------

    def _ensure_layers(self) -> None:
        font = theme.mono_font()
        metrics = QFontMetrics(font)
        step = metrics.height() + theme.line_extra()
        cell = max(1, metrics.horizontalAdvance("0"))
        size = self.size()
        key = (size.width(), size.height(), font.pixelSize(), self.colors.get("dim"))
        if key == self._layers_key and self._layers:
            return
        self._layers_key = key
        rows = size.height() // max(1, step) + 1
        columns = size.width() // cell + 1
        self._layers = []
        for seed in (7, 91):
            pixmap = QPixmap(max(1, size.width()), max(1, size.height()))
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setFont(font)
            painter.setPen(_qcolor(self.colors["dim"]))
            for row, line in enumerate(noise_lines(seed, rows, columns)):
                painter.drawText(0, row * step + metrics.ascent(), line)
            painter.end()
            self._layers.append(pixmap)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(event.rect(), _qcolor(self.colors["bg"]))
        if self._level > 0 and self.width() > 0 and self.height() > 0:
            self._ensure_layers()
            share = self.phase()
            for pixmap, weight in zip(self._layers, (share, 1.0 - share)):
                if weight <= 0.01:
                    continue
                painter.setOpacity(self._level * weight)
                painter.drawPixmap(event.rect(), pixmap, event.rect())
        painter.end()


class ScanlineOverlay(QWidget):
    """Полосы развёртки и затемнение к краям — поверх всего окна.

    Мышь сквозь них проходит: это стекло монитора, а не часть интерфейса.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile = QPixmap(4, 3)
        tile.fill(Qt.GlobalColor.transparent)
        tile_painter = QPainter(tile)
        tile_painter.fillRect(0, 0, 4, 1, QColor(0, 0, 0, 56))
        tile_painter.end()
        self._lines = QBrush(tile)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        from PySide6.QtCore import QEvent

        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
            self.raise_()
        return False

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(event.rect(), self._lines)
        rect = QRectF(self.rect())
        gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.62)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.70, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 96))
        painter.fillRect(event.rect(), QBrush(gradient))
        painter.end()


# --- Панель в двойной рамке --------------------------------------------------------


class TitledPanel(QFrame):
    """Панель в двойной рамке с заголовком на верхней линии: «[ Сегодня ]».

    Внутри — обычная вертикальная раскладка ``box``. Фон сплошной: шум экрана
    остаётся снаружи и не мешает читать.
    """

    BORDER = 4          # толщина двойной рамки: линия, просвет, линия
    PAD_X = 12
    PAD_TOP = 14
    PAD_BOTTOM = 12

    clicked = Signal()

    def __init__(self, title: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._title = title
        self._clickable = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.box = QVBoxLayout(self)
        self.box.setSpacing(theme.px(6))
        self._apply_margins()

    def _title_height(self) -> int:
        return QFontMetrics(theme.mono_font()).height()

    def _border_top(self) -> int:
        """Где проходит верхняя рамка: посередине строки заголовка."""
        return max(0, self._title_height() // 2 - theme.px(self.BORDER) // 2)

    def _apply_margins(self) -> None:
        border = theme.px(self.BORDER)
        top = self._border_top() + border + theme.px(self.PAD_TOP)
        side = border + theme.px(self.PAD_X)
        self.box.setContentsMargins(side, top, side, border + theme.px(self.PAD_BOTTOM))

    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        if title != self._title:
            self._title = title
            self.update()

    def set_clickable(self, tooltip: str = "") -> None:
        self._clickable = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        painter = QPainter(self)
        top = self._border_top()
        border = theme.px(self.BORDER)
        line = max(1, border // 4)
        frame = QRect(0, top, self.width(), self.height() - top)
        painter.fillRect(frame, _qcolor(c["bg"]))

        color = _qcolor(c["dim"])
        for inset in (0, border - line):
            rect = frame.adjusted(inset, inset, -inset, -inset)
            painter.fillRect(rect.x(), rect.y(), rect.width(), line, color)
            painter.fillRect(rect.x(), rect.bottom() - line + 1, rect.width(), line, color)
            painter.fillRect(rect.x(), rect.y(), line, rect.height(), color)
            painter.fillRect(rect.right() - line + 1, rect.y(), line, rect.height(), color)

        if self._title:
            font = theme.mono_font()
            painter.setFont(font)
            metrics = QFontMetrics(font)
            text = "[ %s ]" % self._title
            width = metrics.horizontalAdvance(text)
            available = self.width() - theme.px(14) * 2 - theme.px(12)
            if width > available > 0:
                text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available)
                width = metrics.horizontalAdvance(text)
            left = theme.px(14)
            pad = theme.px(6)
            painter.fillRect(
                QRect(left, 0, width + pad * 2, metrics.height()), _qcolor(c["bg"])
            )
            painter.setPen(_qcolor(c["bright"]))
            painter.drawText(left + pad, metrics.ascent(), text)
        painter.end()


# --- Знаки во всю ширину -----------------------------------------------------------


class FillGlyph(QWidget):
    """Знак, повторённый на всю ширину: «═════», отточие «......»."""

    def __init__(self, char: str, color: str, opacity: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self.char = char
        self.color = color
        self.opacity = opacity
        self.setFont(theme.mono_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def set_color(self, color: str) -> None:
        if color != self.color:
            self.color = color
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self.char) * 3, metrics.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(0, self.fontMetrics().height())

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        metrics = self.fontMetrics()
        step = max(1, metrics.horizontalAdvance(self.char))
        count = self.width() // step
        if count <= 0:
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(_qcolor(self.color, self.opacity))
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        painter.drawText(0, baseline, self.char * count)
        painter.end()


class BlockBar(QWidget):
    """Шкала из клеток во всю ширину: «████████░░░░░░»."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._share = 0.0
        self._color = colors["accent"]
        self.setFont(theme.mono_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_share(self, share: float, color: str = "") -> None:
        self._share = max(0.0, min(1.0, share))
        self._color = color or self.colors["accent"]
        self.update()

    def cells(self) -> tuple[int, int]:
        """Сколько клеток всего и сколько из них закрашено."""
        total = max(1, self.width() // max(1, cell_width(self.font())))
        filled = round(total * self._share)
        if self._share > 0 and filled == 0:
            filled = 1  # работа была — хоть одна клетка, иначе её не видно
        return total, filled

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(cell_width(self.font()) * 16, self.fontMetrics().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(cell_width(self.font()) * 4, self.fontMetrics().height())

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        total, filled = self.cells()
        metrics = self.fontMetrics()
        painter = QPainter(self)
        painter.setFont(self.font())
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        painter.setPen(_qcolor(self._color))
        painter.drawText(0, baseline, "\u2588" * filled)
        painter.setPen(_qcolor(self.colors["faint"]))
        painter.drawText(cell_width(self.font()) * filled, baseline, "\u2591" * (total - filled))
        painter.end()


class LeaderRow(QWidget):
    """Строка «ключ ........ значение» — поле карточки в одну строку."""

    def __init__(self, key: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(6))

        self.key = QLabel(key)
        self.key.setFont(theme.mono_font())
        self.key.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
        self.key.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.key)

        self.leader = FillGlyph(".", colors["faint"])
        layout.addWidget(self.leader, 1)

        self.value = ElidedLabel("")
        self.value.setFont(theme.mono_font())
        layout.addWidget(self.value)
        self.set_value("")

    def set_value(self, text: str, color: str = "") -> None:
        self.value.setText(text)
        self.value.setStyleSheet(
            "color: %s; background: transparent;" % (color or self.colors["text"])
        )
        self.value.setToolTip(text if len(text) > 24 else "")


class ElidedLabel(QLabel):
    """Надпись в одну строку, которая обрезается по ширине, а не раздвигает ряд.

    ``text()`` возвращает весь текст: обрезка — только на экране.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        from .widgets import elide_text

        painter = QPainter(self)
        painter.setFont(self.font())
        rect = self.contentsRect()
        text = elide_text(self.fontMetrics(), self.text(), rect.width())
        style_color = self.palette().color(self.foregroundRole())
        painter.setPen(style_color)
        metrics = self.fontMetrics()
        baseline = rect.y() + (rect.height() - metrics.height()) // 2 + metrics.ascent()
        x = rect.x()
        if self.alignment() & Qt.AlignmentFlag.AlignRight:
            x = rect.right() - metrics.horizontalAdvance(text) + 1
        painter.drawText(x, baseline, text)
        if self.font().strikeOut():
            pass  # зачёркивание рисует сам шрифт
        painter.end()


# --- Шапка ----------------------------------------------------------------------------


class Ticker(QWidget):
    """Бегущая строка телеметрии: что синхронизировано, что отмечено, что дальше."""

    STEP = 2           # пикселей за кадр
    FRAME_MS = 75

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._text = ""
        self._offset = 0
        self._motion = True
        self.setFont(theme.mono_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(theme.px(40))
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._advance)

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.update()

    def text(self) -> str:
        return self._text

    def set_motion(self, motion: bool) -> None:
        self._motion = bool(motion)
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        if self._motion and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        if not self.window().isVisible() or self.window().isMinimized():
            return
        self._offset += theme.px(self.STEP)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(theme.px(200), self.fontMetrics().height() + theme.px(4))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        painter = QPainter(self)
        metrics = self.fontMetrics()
        line = theme.px(2)
        painter.fillRect(0, self.height() - line, self.width(), line, _qcolor(c["faint"]))
        if self._text:
            painter.setFont(self.font())
            painter.setPen(_qcolor(c["dim"], 0.8))
            painter.setClipRect(0, 0, self.width(), self.height() - line)
            span = metrics.horizontalAdvance(self._text)
            shift = (self._offset % span) if span else 0
            x = -shift
            baseline = metrics.ascent()
            while x < self.width():
                painter.drawText(x, baseline, self._text)
                x += span
        painter.end()


class MenuStrip(QWidget):
    """Меню по центру: «═══╡ Отчёт за день │ Неделя │ … ╞═══»."""

    def __init__(self, colors: dict[str, str], items: list[tuple[str, object]],
                 parent=None) -> None:
        from PySide6.QtWidgets import QPushButton

        super().__init__(parent)
        self.colors = colors
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(4))

        def glyph(char: str, color: str) -> QLabel:
            label = QLabel(char)
            label.setFont(theme.mono_font())
            label.setStyleSheet("color: %s; background: transparent;" % color)
            return label

        layout.addWidget(FillGlyph("\u2550", colors["faint"]), 1)
        layout.addWidget(glyph("\u2561", colors["dim"]))
        self.buttons = []
        for index, (title, action) in enumerate(items):
            if index:
                layout.addWidget(glyph("\u2502", colors["faint"]))
            button = QPushButton(title)
            button.setProperty("flat", "true")
            button.setProperty("menu", "true")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action)
            self.buttons.append(button)
            layout.addWidget(button)
        layout.addWidget(glyph("\u255e", colors["dim"]))
        layout.addWidget(FillGlyph("\u2550", colors["faint"]), 1)


# --- Строка ввода и F-клавиши ----------------------------------------------------------


class BlockCursorStyle(QProxyStyle):
    """Курсор строки ввода — во всю клетку, как в командной строке."""

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802 (Qt naming)
        if metric == QStyle.PixelMetric.PM_TextCursorWidth:
            return cell_width()
        return super().pixelMetric(metric, option, widget)


_cursor_style: BlockCursorStyle | None = None


def block_cursor_style() -> BlockCursorStyle:
    """Один стиль на всё приложение, и принадлежит он приложению.

    Виджет стилем не владеет: если стиль удалить раньше поля ввода, программа
    падает на выходе. Приложение же переживает все свои окна.
    """
    global _cursor_style
    if _cursor_style is None:
        from PySide6.QtWidgets import QApplication

        _cursor_style = BlockCursorStyle()
        _cursor_style.setParent(QApplication.instance())
    return _cursor_style


class PromptLine(QWidget):
    """Нижняя строка «C:\\TASKS\\ВСЕ> _»: сюда пишется новая задача."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setObjectName("promptLine")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.px(16), theme.px(4), theme.px(16), theme.px(4))
        layout.setSpacing(0)

        self.path = QLabel("C:\\TASKS>")
        self.path.setFont(theme.mono_font())
        self.path.setStyleSheet("color: %s; background: transparent;" % colors["text"])
        layout.addWidget(self.path)

        self.input = QLineEdit()
        self.input.setProperty("prompt", "true")
        self.input.setFont(theme.mono_font())
        self.input.setStyle(block_cursor_style())
        layout.addWidget(self.input, 1)

        self.status = QLabel("")
        self.status.setFont(theme.mono_font())
        self.status.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
        layout.addWidget(self.status)

    def set_path(self, path: str) -> None:
        self.path.setText("C:\\TASKS%s> " % (("\\" + path) if path else ""))

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), _qcolor(self.colors["bg"]))
        line = theme.px(2)
        painter.fillRect(0, 0, self.width(), line, _qcolor(self.colors["faint"]))
        painter.end()


def prompt_path(title: str) -> str:
    """Название раздела — в имя папки: «Из Jira: в работе» → «JIRA\\В_РАБОТЕ»."""
    text = (title or "").upper().replace("ИЗ JIRA:", "JIRA\\").replace(":", "")
    parts = [part.strip().replace(" ", "_") for part in text.split("\\")]
    return "\\".join(part for part in parts if part)


class FKeyBar(QWidget):
    """Полоса F-клавиш внизу: номер и плашка с действием, по ней можно щёлкнуть."""

    def __init__(self, colors: dict[str, str], keys: list[tuple[str, object]],
                 parent=None) -> None:
        from PySide6.QtWidgets import QGridLayout

        super().__init__(parent)
        self.colors = colors
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        grid = QGridLayout(self)
        grid.setContentsMargins(theme.px(16), theme.px(4), theme.px(16), theme.px(8))
        grid.setHorizontalSpacing(theme.px(6))
        grid.setVerticalSpacing(0)
        self.keys: list[FKey] = []
        for index, (label, action) in enumerate(keys):
            key = FKey(index + 1, label, colors)
            key.clicked.connect(action)
            grid.addWidget(key, 0, index)
            grid.setColumnStretch(index, 1)
            self.keys.append(key)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), _qcolor(self.colors["bg"]))
        painter.end()


class FKey(QWidget):
    """Одна клавиша: «1» и плашка «Справка»."""

    clicked = Signal()

    def __init__(self, number: int, label: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.number = number
        self.label = label
        self.colors = colors
        self._hover = False
        self.setFont(theme.mono_font())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("F%d — %s" % (number, label))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance("%d%s" % (self.number, self.label)) + theme.px(8),
                     max(theme.px(24), metrics.height() + theme.px(4)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(cell_width(self.font()) * 3, self.sizeHint().height())

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        metrics = self.fontMetrics()
        painter = QPainter(self)
        painter.setFont(self.font())
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        number = str(self.number)
        painter.setPen(_qcolor(c["text"]))
        painter.drawText(0, baseline, number)
        left = metrics.horizontalAdvance(number) + theme.px(2)
        slab = QRect(left, (self.height() - metrics.height()) // 2 - theme.px(2),
                     self.width() - left, metrics.height() + theme.px(4))
        painter.fillRect(slab, _qcolor(c["bright"] if self._hover else c["dim"]))
        painter.setPen(_qcolor(c["slab_ink"]))
        painter.setClipRect(slab)
        painter.drawText(left + theme.px(4), baseline, self.label)
        painter.end()


# --- Таблица задач ----------------------------------------------------------------------

# Колонки строки задачи в клетках: отметка, значок, ключ, название (всё
# оставшееся), продукт, срок, важность. Между колонками — одна клетка.
TABLE_COLUMNS = (
    ("check", 3),
    ("mark", 1),
    ("key", 8),
    ("title", 0),
    ("product", 10),
    ("due", 11),
    ("prio", 5),
)
TABLE_HEADERS = {
    "check": "",
    "mark": "",
    "key": "ключ",
    "title": "задача",
    "product": "продукт",
    "due": "срок",
    "prio": "важн",
}
# Меньше скольких клеток под название оставлять нельзя: тогда прячем продукт.
TITLE_MIN_CELLS = 16
ROW_PAD = 3


def column_widths(total: int, cell: int) -> dict[str, int]:
    """Ширина каждой колонки в пикселях при такой ширине строки.

    Узкая таблица сначала жертвует продуктом: название задачи важнее.
    """
    cell = max(1, cell)
    gap = cell
    widths = {name: size * cell for name, size in TABLE_COLUMNS}
    fixed = sum(width for name, width in widths.items() if name != "title")
    gaps = gap * (len(TABLE_COLUMNS) - 1)
    title = total - fixed - gaps
    if title < TITLE_MIN_CELLS * cell:
        title += widths["product"] + gap
        widths["product"] = 0
    widths["title"] = max(cell * 4, title)
    return widths


class TableHeader(QWidget):
    """Шапка таблицы задач: подписи колонок и черта под ними."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._width = 0
        self.setFont(theme.mono_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_row_width(self, width: int) -> None:
        """Ширина строк списка — по ней выравниваются колонки."""
        if width != self._width:
            self._width = width
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(theme.px(300), self.fontMetrics().height() + theme.px(8))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        cell = cell_width(self.font())
        width = self._width or self.width()
        widths = column_widths(width - theme.px(12), cell)
        metrics = self.fontMetrics()
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(_qcolor(c["text_dim"]))
        x = theme.px(6)
        for name, _size in TABLE_COLUMNS:
            column = widths[name]
            if column <= 0:
                continue
            caption = TABLE_HEADERS[name]
            if caption:
                painter.drawText(x, metrics.ascent(), caption)
            x += column + cell
        line = theme.px(2)
        painter.fillRect(0, self.height() - line, width, line, _qcolor(c["faint"]))
        painter.end()
