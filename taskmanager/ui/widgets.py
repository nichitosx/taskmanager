"""Мелкие визуальные элементы: строка задачи, «пилюли», заголовки секций."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Property,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QScrollArea,
    QLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..horizons import start_text
from ..recurrence import describe as describe_repeat
from ..models import (
    JIRA_NOT_NEEDED,
    PRIORITY_LABELS,
    Task,
)
from . import theme


class FlowLayout(QLayout):
    """Ряд, который переносит не поместившиеся элементы на следующую строку.

    Метки задачи (срок, приоритет, продукт, теги) в узком окне переставали
    помещаться в одну строку и обрезались; теперь они просто переходят ниже.
    """

    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # --- Обязательный минимум QLayout ----------------------------------------

    def addItem(self, item) -> None:  # noqa: N802 (Qt naming)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt naming)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt naming)
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt naming)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    # --- Раскладка ------------------------------------------------------------

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def pixel_corner_path(rect: QRectF, radius: int = 6, step: int = 2) -> QPainterPath:
    """Прямоугольник со ступенчатыми углами — скругление в духе пиксель-арта.

    Обычный border-radius даёт гладкую сглаженную дугу, которая в пиксельном
    оформлении выглядит чужеродно. Здесь угол набирается из квадратных шагов.
    """
    path = QPainterPath()
    left, top = rect.x(), rect.y()
    right, bottom = rect.x() + rect.width(), rect.y() + rect.height()
    steps = max(1, int(radius / step))
    size = radius / steps

    def staircase(x: float, y: float, dx: float, dy: float) -> None:
        """Лесенка длиной radius: чередуем шаг по горизонтали и по вертикали."""
        for index in range(steps):
            path.lineTo(x + dx * size * (index + 1), y + dy * size * index)
            path.lineTo(x + dx * size * (index + 1), y + dy * size * (index + 1))

    path.moveTo(left + radius, top)
    path.lineTo(right - radius, top)
    staircase(right - radius, top, 1, 1)          # правый верхний
    path.lineTo(right, bottom - radius)
    staircase(right, bottom - radius, -1, 1)      # правый нижний
    path.lineTo(left + radius, bottom)
    staircase(left + radius, bottom, -1, -1)      # левый нижний
    path.lineTo(left, top + radius)
    staircase(left, top + radius, 1, -1)          # левый верхний
    path.closeSubpath()
    return path


def card_path(rect: QRectF) -> QPainterPath:
    """Контур карточки: гладкий в мягком стиле, ступенчатый в пиксельном."""
    if theme.is_pixel():
        return pixel_corner_path(rect, theme.PIXEL_CORNER, theme.PIXEL_STEP)
    path = QPainterPath()
    path.addRoundedRect(rect, theme.radius("card"), theme.radius("card"))
    return path


class Card(QFrame):
    """Карточка, которая рисует себя сама.

    Своя отрисовка нужна ради пиксельных углов, а заодно даёт единый вид
    наведения и выделения без возни с таблицами стилей.
    """

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._bg = colors["surface"]
        self._border = colors["border_soft"]
        self._hover_bg = colors["surface_hover"]
        self._bar = ""
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_card_colors(self, bg: str = "", border: str = "", hover_bg: str = "") -> None:
        self._bg = bg or self._bg
        self._border = border or self._border
        self._hover_bg = hover_bg or self._hover_bg
        self.update()

    def set_bar(self, color: str) -> None:
        """Цветная полоска у левого края (приоритет задачи)."""
        self._bar = color
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        pixel = theme.is_pixel()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not pixel)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = card_path(rect)

        painter.fillPath(path, QColor(self._hover_bg if self._hover else self._bg))
        if self._bar:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(rect.x(), rect.y(), 3.0, rect.height()), QColor(self._bar))
            painter.restore()
        painter.strokePath(path, QPen(QColor(self._border), 1))
        painter.end()


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("section", "true")
    return label


def hline() -> QFrame:
    line = QFrame()
    line.setProperty("hline", "true")
    line.setFixedHeight(1)
    return line


def headline() -> QFrame:
    """Разделитель под шапкой — с акцентным началом, чтобы окно не было серым."""
    line = QFrame()
    line.setProperty("headline", "true")
    line.setFixedHeight(1)
    return line


class CheckCircle(QAbstractButton):
    """Круглая отметка «выполнено».

    Рисуется вручную: системный QCheckBox даже со стилями выглядит инородно —
    квадратная галочка не ложится в остальной интерфейс. При наведении внутри
    круга проступает бледная галочка, чтобы было понятно, что сюда можно нажать.
    """

    # Крупный бледный круг спорил с текстом задачи, поэтому отметка компактная.
    SIZE = 16
    ANIMATION_MS = 170

    def __init__(self, checked: bool, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Отметить выполненной")
        self._hover = False
        # 0 — пусто, 1 — залито: промежуточные значения рисует анимация.
        self._fill = 1.0 if checked else 0.0
        self._animation: QPropertyAnimation | None = None
        self.toggled.connect(self._animate)

    def _get_fill(self) -> float:
        return self._fill

    def _set_fill(self, value: float) -> None:
        self._fill = max(0.0, min(1.0, float(value)))
        self.update()

    fill = Property(float, _get_fill, _set_fill)

    def set_checked_silently(self, checked: bool) -> None:
        """Меняет отметку без сигнала и без анимации — для отката действия."""
        # Анимацию от прошлого клика обязательно останавливаем: иначе она
        # доиграет и снова закрасит кружок, который мы только что сбросили.
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._fill = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked: bool) -> None:
        animation = QPropertyAnimation(self, b"fill", self)
        animation.setDuration(self.ANIMATION_MS)
        animation.setStartValue(self._fill)
        animation.setEndValue(1.0 if checked else 0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._animation = animation

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        pixel = theme.is_pixel()
        painter = QPainter(self)
        # В пиксельном стиле сглаживание выключено намеренно: ступеньки на краях
        # и есть та самая «пиксельность».
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not pixel)
        # Рисуем в системе координат 16×16 — размер меняется одной константой.
        painter.scale(self.SIZE / 16.0, self.SIZE / 16.0)
        box = QRectF(1.4, 1.4, 13.2, 13.2)

        def draw_shape() -> None:
            if pixel:
                painter.drawRect(box)
            else:
                painter.drawEllipse(box)

        # Контур рисуем всегда, заливка «вырастает» из центра по ходу анимации.
        ring = QColor(c["accent"])
        if not self._hover:
            ring = QColor(c["text_faint"])
            ring.setAlphaF(0.55)  # видно, но не спорит с названием задачи
        painter.setBrush(QColor(c["surface"]))
        painter.setPen(QPen(ring, 1.3))
        draw_shape()

        grown = max(0.0, min(1.0, self._fill))
        if grown > 0.01:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["success"]))
            inset = (1.0 - grown) * 6.6
            box = QRectF(1.4 + inset, 1.4 + inset, 13.2 - inset * 2, 13.2 - inset * 2)
            draw_shape()

        if grown > 0.35:
            tick = QColor("#FFFFFF")
            tick.setAlphaF(min(1.0, (grown - 0.35) / 0.5))
        elif self._hover:
            tick = QColor(c["text_faint"])
        else:
            tick = None

        if tick is not None:
            path = QPainterPath()
            path.moveTo(4.6, 8.1)
            path.lineTo(6.9, 10.5)
            path.lineTo(11.4, 5.3)
            pen = QPen(tick, 1.9 if pixel else 1.7)
            cap = Qt.PenCapStyle.SquareCap if pixel else Qt.PenCapStyle.RoundCap
            join = Qt.PenJoinStyle.MiterJoin if pixel else Qt.PenJoinStyle.RoundJoin
            pen.setCapStyle(cap)
            pen.setJoinStyle(join)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


PILL_HEIGHT = 20

# Отступ от текста до рамки метки — одинаковый у всех меток, включая продукт.
PILL_PADDING = 6


def elide_text(metrics, text: str, width: int) -> str:
    """Обрезает текст под ширину.

    Стандартное многоточие есть не во всяком пиксельном шрифте, поэтому если
    его нет — дописываем две точки, они рисуются любым шрифтом.
    """
    if metrics.horizontalAdvance(text) <= width:
        return text
    # Многоточие в пиксельных шрифтах либо отсутствует, либо рисуется странно —
    # там честнее две точки.
    suffix = ".." if theme.is_pixel() else "…"
    while text and metrics.horizontalAdvance(text + suffix) > width:
        text = text[:-1]
    return text.rstrip() + suffix


def text_width(widget, text: str) -> int:
    """Ширина текста у уже стилизованного виджета.

    QLabel не учитывает отступы из таблицы стилей в подсказке размера, а сама
    таблица может подменить шрифт и межбуквенный интервал — поэтому меряем после
    ensurePolished и берём большее из двух измерений.
    """
    widget.ensurePolished()
    metrics = widget.fontMetrics()
    return max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width())


class Pill(QLabel):
    """Компактная метка: срок, ключ Jira, приоритет, продукт, простой.

    Высота фиксированная, текст по центру: у моноширинных шрифтов запас под
    нижние выносные элементы разный, и без этого надпись съезжает вниз.
    """

    def __init__(
        self,
        text: str,
        color: str,
        strong: bool = False,
        left_padding: int = PILL_PADDING,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self.setFont(theme.small_font())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(PILL_HEIGHT)
        self.setStyleSheet(
            "color: %s; background: %s; border: 1px solid %s;"
            "border-radius: %dpx; padding-left: %dpx; padding-right: %dpx; %s"
            % (
                color,
                theme.tint(color, 0.20 if strong else 0.12),
                theme.tint(color, 0.34),
                theme.radius("pill"),
                left_padding,
                PILL_PADDING,
                theme.small_font_css(),
            )
        )
        self.setFixedWidth(text_width(self, text) + left_padding + PILL_PADDING + 4)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class ProductPill(Pill):
    """Метка продукта: та же «пилюля», но с цветным кружком слева.

    Кружок рисуется, а не кладётся в раскладку: так расстояние от него до текста
    одинаково у любого названия, а отступы совпадают с обычными метками.
    """

    DOT = 6
    DOT_GAP = 6

    def __init__(self, name: str, color: str, parent=None) -> None:
        self._dot_color = color
        super().__init__(
            name,
            color,
            left_padding=PILL_PADDING + self.DOT + self.DOT_GAP,
            parent=parent,
        )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not theme.is_pixel())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._dot_color))
        top = (self.height() - self.DOT) / 2.0
        box = QRectF(PILL_PADDING + 1, top, self.DOT, self.DOT)
        if theme.is_pixel():
            painter.drawRect(box)
        else:
            painter.drawEllipse(box)
        painter.end()


def _due_text(task: Task) -> str:
    days = task.days_to_due
    if days is None:
        return ""
    if days < 0:
        return "просрочено на %d дн." % (-days)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return "до %s" % task.due_date.strftime("%d.%m")


class TaskRow(Card):
    """Строка списка задач.

    Слева — полоска цвета приоритета и круглая отметка, дальше заголовок и
    строка меток. Двойной клик открывает карточку задачи.
    """

    toggled = Signal(int, bool)
    activated = Signal(int)
    clicked = Signal(int)
    log_requested = Signal(int)

    def __init__(
        self,
        task: Task,
        colors: dict[str, str],
        stale_days: int,
        product_color: str = "",
        show_jira: bool = True,
        subtasks: tuple[int, int] = (0, 0),
        parent=None,
    ) -> None:
        super().__init__(colors, parent)
        self.task = task
        self.stale_days = stale_days
        self.product_color = product_color
        self.show_jira = show_jira
        self.subtasks = subtasks
        self._build()
        self._apply_style()

    # --- Построение -----------------------------------------------------------

    def _build(self) -> None:
        c = self.colors
        task = self.task

        # Полоска приоритета рисуется самой карточкой, здесь только отступ под неё.
        if not task.is_done:
            if task.is_overdue:
                self.set_bar(c["danger"])
            elif task.priority >= 2:
                self.set_bar(c[theme.PRIORITY_COLOR_KEYS[task.priority]])

        inner = QHBoxLayout(self)
        gap = theme.line_extra()
        inner.setContentsMargins(16, 11 + gap // 2, 14, 11 + gap // 2)
        inner.setSpacing(12)

        self.check = CheckCircle(task.is_done, c)
        self.check.toggled.connect(lambda state: self.toggled.emit(task.id, state))
        inner.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(7 + theme.line_extra())
        inner.addLayout(text_col, 1)

        self.title = QLabel(task.title)
        self.title.setWordWrap(True)
        title_font = theme.ui_font(11, bold=task.priority >= 2 and not task.is_done)
        title_font.setStrikeOut(task.is_done)
        self.title.setFont(title_font)
        if task.is_done:
            color = c["text_faint"]
        elif task.is_planned:
            color = c["text_dim"]  # работа ещё не началась — строка тише остальных
        else:
            color = c["text"]
        self.title.setStyleSheet("color: %s; background: transparent;" % color)
        text_col.addWidget(self.title)

        pills = self._meta_pills()
        if pills:
            meta = FlowLayout(spacing=6)
            text_col.addLayout(meta)
            for pill in pills:
                meta.addWidget(pill)

    def _meta_pills(self) -> list[QWidget]:
        c = self.colors
        task = self.task
        pills: list[QWidget] = []

        if task.product:
            pills.append(ProductPill(task.product, self.product_color or c["info"]))

        if task.is_planned:
            pills.append(Pill(start_text(task), c["info"]))

        done, total = self.subtasks
        if total:
            complete = done >= total
            pills.append(
                Pill(
                    "%d/%d" % (done, total),
                    c["success"] if complete else c["text_dim"],
                    strong=complete,
                )
            )

        repeat = describe_repeat(task.repeat)
        if repeat and not task.is_done:
            pills.append(Pill("↻ " + repeat, c["text_dim"]))

        if task.priority >= 2 and not task.is_done:
            key = theme.PRIORITY_COLOR_KEYS[task.priority]
            pills.append(Pill(PRIORITY_LABELS[task.priority].upper(), c[key], strong=True))

        due = _due_text(task)
        if due and not task.is_done:
            if task.is_overdue:
                pills.append(Pill(due, c["danger"], strong=True))
            elif (task.days_to_due or 0) <= 1:
                pills.append(Pill(due, c["accent"]))
            else:
                pills.append(Pill(due, c["text_dim"]))

        if self.show_jira:
            if task.jira_key:
                pills.append(Pill(task.jira_key, c["info"]))
            elif task.jira_state == JIRA_NOT_NEEDED:
                pills.append(Pill("без jira", c["text_faint"]))
            elif not task.is_done:
                pills.append(Pill("jira?", c["warning"]))

        if task.is_stale(self.stale_days):
            pills.append(Pill("тишина %d дн." % task.days_since_activity, c["text_faint"]))

        for tag in task.tags[:3]:
            pills.append(Pill("#" + tag, c["text_faint"]))

        return pills

    # --- Оформление и события -------------------------------------------------

    def _apply_style(self, selected: bool = False) -> None:
        c = self.colors
        if selected:
            border, background = c["accent"], c["surface_hover"]
        elif self.task.is_overdue:
            border, background = c["danger"], c["surface"]
        else:
            # В пиксельном стиле рамка заметнее: карточка должна читаться коробкой.
            border = c["border"] if theme.is_pixel() else c["border_soft"]
            background = c["surface"]
        self.set_card_colors(background, border, c["surface_hover"])

    def set_selected(self, selected: bool) -> None:
        self._apply_style(selected)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self.task.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.task.id)
        super().mouseDoubleClickEvent(event)


# Шпаргалка быстрой записи: пара «что написать» — «что получится».
QUICK_HELP = [
    ("!!", "высокий приоритет"),
    ("!!!", "критично"),
    ("@завтра  @пт  @25.12", "срок"),
    ("@кмес", "конец месяца"),
    (">15.10  >+14", "начать позже"),
    ("#тег", "метка"),
    ("PROJ-142", "ключ Jira"),
]


class HintPopup(QFrame):
    """Всплывающее окно со шпаргалкой — отдельным окошком, поверх интерфейса."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("hintPopup")
        self.setStyleSheet(
            "#hintPopup { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (colors["surface_alt"], colors["border"], theme.radius("card"))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 12)
        layout.setSpacing(8)

        caption = section_label("шпаргалка быстрой записи")
        layout.addWidget(caption)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(theme.line_extra() + 4)
        layout.addLayout(grid)

        for row, (token, meaning) in enumerate(QUICK_HELP):
            left = QLabel(token)
            left.setFont(theme.mono_font(8))
            left.setStyleSheet("color: %s; background: transparent;" % colors["accent"])
            grid.addWidget(left, row, 0)

            right = QLabel(meaning)
            right.setFont(theme.mono_font(8))
            right.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
            grid.addWidget(right, row, 1)

        note = QLabel("Всё это можно писать прямо в строке новой задачи.")
        note.setFont(theme.mono_font(8))
        note.setWordWrap(True)
        note.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(note)


class HintTrigger(QFrame):
    """Строка «шпаргалка ввода»: занимает одну строку, раскрывается по наведению."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setObjectName("hintTrigger")
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._popup: HintPopup | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(8)

        badge = QLabel("?")
        badge.setFont(theme.accent_font(9, bold=True))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(16, 16)
        badge.setStyleSheet(
            "color: %s; background: %s; border-radius: %dpx;"
            % (colors["accent"], theme.tint(colors["accent"], 0.16),
               0 if theme.is_pixel() else 8)
        )
        layout.addWidget(badge)

        title = QLabel("шпаргалка ввода")
        title.setFont(theme.mono_font(8))
        title.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(title)
        layout.addStretch(1)

        self._apply_style(False)

    def _apply_style(self, hover: bool) -> None:
        c = self.colors
        self.setStyleSheet(
            "#hintTrigger { background: %s; border-radius: %dpx; }"
            % (c["surface_alt"] if hover else "transparent", theme.radius("nav"))
        )

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._apply_style(True)
        self.show_popup()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._apply_style(False)
        self.hide_popup()
        super().leaveEvent(event)

    def show_popup(self) -> None:
        if self._popup is None:
            self._popup = HintPopup(self.colors, self)
        popup = self._popup
        popup.adjustSize()
        # Показываем справа от панели, выравнивая по нижнему краю строки.
        corner = self.mapToGlobal(self.rect().topRight())
        popup.move(corner.x() + 10, max(10, corner.y() - popup.height() + self.height()))
        popup.show()
        popup.raise_()

    def hide_popup(self) -> None:
        if self._popup is not None:
            self._popup.hide()


class SubtaskRow(QWidget):
    """Строка чек-листа: отметка, название с правкой на месте и удаление."""

    toggled = Signal(int, bool)
    renamed = Signal(int, str)
    removed = Signal(int)
    moved = Signal(int, int)

    def __init__(self, subtask, colors: dict[str, str], compact: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.subtask = subtask
        self.colors = colors
        self.compact = compact
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.check = CheckCircle(subtask.done, colors)
        self.check.setToolTip("Отметить подпункт")
        self.check.toggled.connect(lambda state: self.toggled.emit(subtask.id, state))
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title = QLineEdit(subtask.title)
        self.title.setProperty("seamless", "true")
        self.title.setFont(theme.ui_font(10))
        # Длинное название иначе показывается «с хвоста»: поле прокручено вправо.
        self.title.setCursorPosition(0)
        # Разрешаем полю сжиматься: иначе в узкой панели строка не помещается.
        self.title.setMinimumWidth(60)
        self.title.setToolTip(subtask.title)
        self.title.editingFinished.connect(self._rename)
        self._apply_done_style()
        layout.addWidget(self.title, 1)

        # В узкой боковой панели стрелки не помещаются — порядок меняют в карточке.
        for text, tip, step in ()  if compact else (("↑", "Выше", -1), ("↓", "Ниже", 1)):
            button = QPushButton(text)
            button.setProperty("tiny", "true")
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, s=step: self.moved.emit(subtask.id, s))
            layout.addWidget(button)

        remove = QPushButton("×")
        remove.setProperty("tiny", "true")
        remove.setToolTip("Удалить подпункт")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda: self.removed.emit(subtask.id))
        layout.addWidget(remove)

    def _apply_done_style(self) -> None:
        c = self.colors
        font = self.title.font()
        font.setStrikeOut(self.subtask.done)
        self.title.setFont(font)
        self.title.setStyleSheet(
            "color: %s; background: transparent;"
            % (c["text_faint"] if self.subtask.done else c["text"])
        )

    def _rename(self) -> None:
        text = self.title.text().strip()
        if text and text != self.subtask.title:
            self.subtask.title = text
            self.title.setToolTip(text)
            self.renamed.emit(self.subtask.id, text)
        elif not text:
            self.title.setText(self.subtask.title)


class SubtaskList(QWidget):
    """Чек-лист подпунктов задачи.

    Умеет работать и до того, как задача сохранена: тогда подпункты копятся в
    памяти, а после создания задачи переносятся в базу методом ``flush``.
    """

    changed = Signal()

    def __init__(self, storage, colors: dict[str, str], task_id=None,
                 compact: bool = False, scroll_height: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.colors = colors
        self.task_id = task_id
        self.compact = compact
        self._pending: list[str] = []
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(section_label("подпункты"))
        head.addStretch(1)
        self.progress = QLabel("")
        self.progress.setFont(theme.accent_font(8))
        self.progress.setStyleSheet(
            "color: %s; background: transparent;" % colors["text_faint"]
        )
        head.addWidget(self.progress)
        layout.addLayout(head)

        rows_host = QWidget()
        rows_host.setStyleSheet("background: transparent;")
        self.rows_box = QVBoxLayout(rows_host)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(theme.line_extra() + 3)

        self._area = None
        self._scroll_height = scroll_height
        if scroll_height:
            # Прокручиваем только строки: заголовок со счётчиком и поле ввода
            # должны оставаться на виду, сколько бы подпунктов ни было.
            self._area = QScrollArea()
            self._area.setWidgetResizable(True)
            self._area.setFrameShape(QFrame.Shape.NoFrame)
            self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._area.setStyleSheet("background: transparent;")
            self._area.setWidget(rows_host)
            layout.addWidget(self._area)
        else:
            layout.addWidget(rows_host)

        self.adder = QLineEdit()
        self.adder.setPlaceholderText("Добавить подпункт — Enter")
        self.adder.setFont(theme.ui_font(10))
        self.adder.returnPressed.connect(self._add)
        layout.addWidget(self.adder)

        self.reload()

    # --- Данные ---------------------------------------------------------------

    def set_task(self, task_id) -> None:
        self.task_id = task_id
        self._pending = []
        self.reload()

    def items(self) -> list:
        """Текущие подпункты: из базы либо ещё не сохранённые."""
        if self.task_id is None:
            from ..models import Subtask

            return [
                Subtask(id=-index - 1, title=title, position=index)
                for index, title in enumerate(self._pending)
            ]
        return self.storage.list_subtasks(self.task_id)

    def flush(self, task_id: int) -> None:
        """Переносит накопленные подпункты в только что созданную задачу."""
        for title in self._pending:
            self.storage.add_subtask(task_id, title)
        self._pending = []
        self.task_id = task_id
        self.reload()

    def reload(self) -> None:
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        items = self.items()
        done = sum(1 for item in items if item.done)
        self.progress.setText("%d из %d" % (done, len(items)) if items else "")

        for subtask in items:
            row = SubtaskRow(subtask, self.colors, self.compact)
            row.toggled.connect(self._toggle)
            row.renamed.connect(self._rename)
            row.removed.connect(self._remove)
            row.moved.connect(self._move)
            self.rows_box.addWidget(row)
        self._fit_area(len(items))

    def _fit_area(self, count: int) -> None:
        """Подгоняет высоту области под число строк, но не выше предела.

        Без явной высоты раскладка сжимает список до двух строк, а с фиксированной
        у короткого чек-листа оставалась бы пустота.
        """
        if self._area is None:
            return
        row_height = 26
        first = self.rows_box.itemAt(0)
        if first is not None and first.widget() is not None:
            row_height = max(row_height, first.widget().sizeHint().height())
        spacing = self.rows_box.spacing()
        wanted = count * row_height + max(0, count - 1) * spacing + 4
        self._area.setFixedHeight(max(28, min(self._scroll_height, wanted)))

    # --- Действия -------------------------------------------------------------

    def _add(self) -> None:
        title = self.adder.text().strip()
        if not title:
            return
        if self.task_id is None:
            self._pending.append(title)
        else:
            self.storage.add_subtask(self.task_id, title)
        self.adder.clear()
        self.reload()
        self.changed.emit()

    def _toggle(self, subtask_id: int, done: bool) -> None:
        if self.task_id is None:
            return  # у несохранённой задачи отмечать ещё нечего
        self.storage.set_subtask_done(subtask_id, done)
        self.reload()
        self.changed.emit()

    def _rename(self, subtask_id: int, title: str) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            if 0 <= index < len(self._pending):
                self._pending[index] = title
        else:
            self.storage.rename_subtask(subtask_id, title)
        self.changed.emit()

    def _remove(self, subtask_id: int) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            if 0 <= index < len(self._pending):
                self._pending.pop(index)
        else:
            self.storage.delete_subtask(subtask_id)
        self.reload()
        self.changed.emit()

    def _move(self, subtask_id: int, step: int) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            target = index + step
            if 0 <= index < len(self._pending) and 0 <= target < len(self._pending):
                self._pending[index], self._pending[target] = (
                    self._pending[target],
                    self._pending[index],
                )
        else:
            self.storage.move_subtask(subtask_id, step)
        self.reload()
        self.changed.emit()


class NavItem(QFrame):
    """Пункт бокового меню: название слева, счётчик справа."""

    clicked = Signal()

    def __init__(self, title: str, colors: dict[str, str], accent: str = "", parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.accent = accent
        self.setObjectName("navItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        horizontal, vertical = theme.nav_padding()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(horizontal + 1, vertical, horizontal, vertical)
        layout.setSpacing(8)

        self.title = QLabel(title)
        self.title.setFont(theme.ui_font(10))
        layout.addWidget(self.title)
        layout.addStretch(1)

        self.count = QLabel("")
        self.count.setFont(theme.accent_font(9))
        layout.addWidget(self.count)

        self.set_active(False)

    def set_count(self, value: int) -> None:
        self.count.setText(str(value) if value else "")

    def set_active(self, active: bool) -> None:
        c = self.colors
        background = c["surface_alt"] if active else "transparent"
        text = c["text"] if active else c["text_dim"]
        self.setStyleSheet(
            "#navItem { background: %s; border-radius: %dpx; }"
            "#navItem:hover { background: %s; }"
            % (background, theme.radius("nav"), c["surface_alt"])
        )
        font = theme.ui_font(10, bold=active)
        self.title.setFont(font)
        self.title.setStyleSheet("color: %s; background: transparent;" % text)
        self.count.setStyleSheet(
            "color: %s; background: transparent;"
            % ((self.accent or c["text_dim"]) if active else c["text_faint"])
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)


class StatChip(QWidget):
    """Счётчик в шапке: крупное число и подпись капслоком."""

    clicked = Signal()

    def __init__(self, caption: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.value = QLabel("0")
        self.value.setFont(theme.mono_font(13, bold=True))
        self.value.setStyleSheet("color: %s; background: transparent;" % colors["text"])
        layout.addWidget(self.value)

        self.caption = QLabel(caption.upper())
        self.caption.setFont(theme.mono_font(7, spacing=1.2))
        self.caption.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(self.caption)

        self.underline = QFrame()
        self.underline.setFixedHeight(2)
        self.underline.setStyleSheet("background: transparent; border-radius: 1px;")
        layout.addWidget(self.underline)

        self._color = colors["text"]

    def set_value(self, value: int, highlight: str = "") -> None:
        self.value.setText(str(value))
        self._color = highlight or self.colors["text"]
        color = self._color if value else self.colors["text_faint"]
        self.value.setStyleSheet("color: %s; background: transparent;" % color)

    def set_active(self, active: bool) -> None:
        """Подчёркиванием показываем, что список отфильтрован по этому счётчику."""
        self.underline.setStyleSheet(
            "background: %s; border-radius: 1px;" % (self._color if active else "transparent")
        )
        self.caption.setStyleSheet(
            "color: %s; background: transparent;"
            % (self.colors["text_dim"] if active else self.colors["text_faint"])
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)


class JiraIssueRow(Card):
    """Строка задачи, прочитанной из Jira: ключ, название, статус, срок.

    Это не наша задача, а зеркало чужой: отметить выполненной её нельзя, зато
    можно открыть в браузере или взять к себе в список.
    """

    activated = Signal(str)   # ключ — открыть в браузере
    take = Signal(str)        # ключ — завести локальную задачу

    def __init__(self, issue, colors: dict[str, str], already: bool = False, parent=None) -> None:
        super().__init__(colors, parent)
        self.issue = issue
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(7)

        title = QLabel(issue.summary or issue.key)
        title.setWordWrap(True)
        title.setFont(theme.ui_font(11))
        title.setStyleSheet("color: %s; background: transparent;" % colors["text"])
        layout.addWidget(title)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        meta.addWidget(Pill(issue.key, colors["info"]))
        if issue.status:
            meta.addWidget(Pill(issue.status.lower(), colors["text_dim"]))
        if issue.due_date:
            overdue = issue.due_date < date.today()
            meta.addWidget(
                Pill(
                    "срок %s" % issue.due_date.strftime("%d.%m"),
                    colors["danger"] if overdue else colors["text_dim"],
                    strong=overdue,
                )
            )
        if issue.priority:
            meta.addWidget(Pill(issue.priority.lower(), colors["text_faint"]))
        meta.addStretch(1)

        if already:
            mark = QLabel("уже в списке")
            mark.setFont(theme.mono_font(8))
            mark.setStyleSheet("color: %s; background: transparent;" % colors["success"])
            meta.addWidget(mark)
        else:
            button = QPushButton("Взять в работу")
            button.setProperty("flat", "true")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda: self.take.emit(issue.key))
            meta.addWidget(button)
        layout.addLayout(meta)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.issue.key)
        super().mouseDoubleClickEvent(event)


class DayProgress(QWidget):
    """Пиксельная шкала: сколько задач сегодня уже отмечено."""

    SEGMENTS = 8
    BLOCK = 7
    GAP = 3

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._filled = 0
        self._complete = False
        self.setFixedSize(
            self.SEGMENTS * self.BLOCK + (self.SEGMENTS - 1) * self.GAP, 12
        )

    def set_values(self, done: int, total: int, complete: bool = False) -> None:
        share = 0.0 if total <= 0 else min(1.0, done / total)
        # Хотя бы один сегмент, если работа была: иначе прогресс не видно.
        self._filled = self.SEGMENTS if complete else (
            max(1, round(share * self.SEGMENTS)) if done else 0
        )
        self._complete = complete
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        active = QColor(c["success"] if self._complete else c["accent"])
        empty = QColor(c["border"])
        for index in range(self.SEGMENTS):
            x = index * (self.BLOCK + self.GAP)
            painter.setBrush(active if index < self._filled else empty)
            painter.drawRect(x, 1, self.BLOCK, 10)
        painter.end()


class DayIndicator(QWidget):
    """Шапка: дата, время и то, как идёт работа за сегодня."""

    clicked = Signal()

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Открыть отчёт за день")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.date = QLabel()
        self.date.setFont(theme.mono_font(8))
        self.date.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(self.date)

        self.time = QLabel()
        self.time.setFont(theme.accent_font(12, bold=True))
        self.time.setStyleSheet("color: %s; background: transparent;" % colors["accent"])
        layout.addWidget(self.time)

        self.progress = DayProgress(colors)
        layout.addWidget(self.progress)

        self.caption = QLabel()
        self.caption.setFont(theme.mono_font(8))
        self.caption.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
        layout.addWidget(self.caption)

        # Подписи не должны сжиматься: в узкой шапке они обрезались бы.
        for label in (self.date, self.time, self.caption):
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.caption.setMinimumWidth(
            self.caption.fontMetrics().horizontalAdvance("отмечено 00 из 00") + 4
        )

    def set_clock(self, moment) -> None:
        weekday = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][moment.weekday()]
        self.date.setText("%s %s" % (weekday, moment.strftime("%d.%m")))
        self.time.setText(moment.strftime("%H:%M"))

    def set_day(self, done: int, total: int, report_saved: bool) -> None:
        self.progress.set_values(done, total, report_saved)
        if report_saved:
            self.caption.setText("отчёт готов")
            color = self.colors["success"]
        elif done:
            self.caption.setText("отмечено %d из %d" % (done, max(total, done)))
            color = self.colors["text_dim"]
        else:
            self.caption.setText("пока пусто")
            color = self.colors["text_faint"]
        self.caption.setStyleSheet("color: %s; background: transparent;" % color)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)
