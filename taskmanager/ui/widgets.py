"""Мелкие визуальные элементы: строка задачи, «пилюли», заголовки секций."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Property,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
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


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("section", "true")
    return label


def hline() -> QFrame:
    line = QFrame()
    line.setProperty("hline", "true")
    line.setFixedHeight(1)
    return line


class CheckCircle(QAbstractButton):
    """Круглая отметка «выполнено».

    Рисуется вручную: системный QCheckBox даже со стилями выглядит инородно —
    квадратная галочка не ложится в остальной интерфейс. При наведении внутри
    круга проступает бледная галочка, чтобы было понятно, что сюда можно нажать.
    """

    SIZE = 20
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
        box = QRectF(1.5, 1.5, self.SIZE - 3, self.SIZE - 3)

        def draw_shape() -> None:
            if pixel:
                painter.drawRect(box)
            else:
                painter.drawEllipse(box)

        # Контур рисуем всегда, заливка «вырастает» из центра по ходу анимации.
        painter.setBrush(QColor(c["surface"]))
        painter.setPen(QPen(QColor(c["accent"] if self._hover else c["border"]), 1.3))
        draw_shape()

        grown = max(0.0, min(1.0, self._fill))
        if grown > 0.01:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["success"]))
            inset = (1.0 - grown) * (self.SIZE - 3) / 2.0
            box = QRectF(
                1.5 + inset, 1.5 + inset, self.SIZE - 3 - inset * 2, self.SIZE - 3 - inset * 2
            )
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
            path.moveTo(6.0, 10.2)
            path.lineTo(8.8, 13.2)
            path.lineTo(14.2, 6.8)
            pen = QPen(tick, 2.2 if pixel else 1.9)
            cap = Qt.PenCapStyle.SquareCap if pixel else Qt.PenCapStyle.RoundCap
            join = Qt.PenJoinStyle.MiterJoin if pixel else Qt.PenJoinStyle.RoundJoin
            pen.setCapStyle(cap)
            pen.setJoinStyle(join)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


PILL_HEIGHT = 20


class Pill(QLabel):
    """Компактная метка: срок, ключ Jira, приоритет, продукт, простой.

    Высота фиксированная, текст выравнивается по центру: у моноширинных шрифтов
    запас под нижние выносные элементы разный, и без этого надпись съезжает вниз.
    """

    def __init__(self, text: str, color: str, strong: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.mono_font(8))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(PILL_HEIGHT)
        self.setStyleSheet(
            "color: %s; background: %s; border: 1px solid %s;"
            "border-radius: %dpx; padding: 0 7px;"
            % (
                color,
                theme.tint(color, 0.20 if strong else 0.12),
                theme.tint(color, 0.34),
                theme.radius("pill"),
            )
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class ProductPill(QWidget):
    """Метка продукта: цветная точка плюс название."""

    def __init__(self, name: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(PILL_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 0, 8, 0)
        layout.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(
            "background: %s; border-radius: %dpx;" % (color, 0 if theme.is_pixel() else 3)
        )
        layout.addWidget(dot)

        label = QLabel(name)
        label.setFont(theme.mono_font(8))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: %s; background: transparent;" % color)
        layout.addWidget(label)

        self.setStyleSheet(
            "background: %s; border: 1px solid %s; border-radius: %dpx;"
            % (theme.tint(color, 0.12), theme.tint(color, 0.30), theme.radius("pill"))
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


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


class TaskRow(QFrame):
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self.colors = colors
        self.stale_days = stale_days
        self.product_color = product_color
        self.show_jira = show_jira
        self.setObjectName("taskRow")
        self._build()
        self._apply_style()

    # --- Построение -----------------------------------------------------------

    def _build(self) -> None:
        c = self.colors
        task = self.task

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 14, 0)
        root.setSpacing(0)

        # Полоска приоритета: заметна только у важного, чтобы не рябило.
        self.bar = QFrame()
        self.bar.setFixedWidth(3)
        bar_color = "transparent"
        if not task.is_done:
            if task.is_overdue:
                bar_color = c["danger"]
            elif task.priority >= 2:
                bar_color = c[theme.PRIORITY_COLOR_KEYS[task.priority]]
        corner = theme.radius("card")
        self.bar.setStyleSheet(
            "background: %s; border-top-left-radius: %dpx;"
            "border-bottom-left-radius: %dpx;" % (bar_color, corner, corner)
        )
        root.addWidget(self.bar)

        inner = QHBoxLayout()
        inner.setContentsMargins(13, 11, 0, 11)
        inner.setSpacing(12)
        root.addLayout(inner, 1)

        self.check = CheckCircle(task.is_done, c)
        self.check.toggled.connect(lambda state: self.toggled.emit(task.id, state))
        inner.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(7)
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
            meta = QHBoxLayout()
            meta.setContentsMargins(0, 0, 0, 0)
            meta.setSpacing(6)
            text_col.addLayout(meta)
            for pill in pills:
                meta.addWidget(pill)
            meta.addStretch(1)

    def _meta_pills(self) -> list[QWidget]:
        c = self.colors
        task = self.task
        pills: list[QWidget] = []

        if task.product:
            pills.append(ProductPill(task.product, self.product_color or c["info"]))

        if task.is_planned:
            pills.append(Pill(start_text(task), c["info"]))

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
            border, background = theme.tint(c["danger"], 0.45), c["surface"]
        else:
            # В пиксельном стиле рамка заметнее: карточка должна читаться коробкой.
            border = c["border"] if theme.is_pixel() else c["border_soft"]
            background = c["surface"]
        self.setStyleSheet(
            "#taskRow { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            "#taskRow:hover { background: %s; border-color: %s; }"
            % (
                background,
                border,
                theme.radius("card"),
                c["surface_hover"],
                c["border"] if not selected else c["accent"],
            )
        )

    def set_selected(self, selected: bool) -> None:
        self._apply_style(selected)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self.task.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.task.id)
        super().mouseDoubleClickEvent(event)


class NavItem(QFrame):
    """Пункт бокового меню: название слева, счётчик справа."""

    clicked = Signal()

    def __init__(self, title: str, colors: dict[str, str], accent: str = "", parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.accent = accent
        self.setObjectName("navItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 7, 10, 7)
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


class JiraIssueRow(QFrame):
    """Строка задачи, прочитанной из Jira: ключ, название, статус, срок.

    Это не наша задача, а зеркало чужой: отметить выполненной её нельзя, зато
    можно открыть в браузере или взять к себе в список.
    """

    activated = Signal(str)   # ключ — открыть в браузере
    take = Signal(str)        # ключ — завести локальную задачу

    def __init__(self, issue, colors: dict[str, str], already: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.issue = issue
        self.colors = colors
        self.setObjectName("jiraRow")
        self.setStyleSheet(
            "#jiraRow { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            "#jiraRow:hover { background: %s; }"
            % (colors["surface"], colors["border_soft"], theme.radius("card"),
               colors["surface_hover"])
        )
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
