"""Мелкие визуальные элементы: строка задачи, «пилюли», заголовки секций."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..horizons import start_text
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

    def __init__(self, checked: bool, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Отметить выполненной")
        self._hover = False

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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(1.5, 1.5, self.SIZE - 3, self.SIZE - 3)

        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["success"]))
            painter.drawEllipse(circle)
            tick = QColor("#FFFFFF")
        else:
            painter.setBrush(QColor(c["surface"]))
            painter.setPen(QPen(QColor(c["accent"] if self._hover else c["border"]), 1.3))
            painter.drawEllipse(circle)
            tick = QColor(c["text_faint"]) if self._hover else None

        if tick is not None:
            path = QPainterPath()
            path.moveTo(6.0, 10.2)
            path.lineTo(8.8, 13.2)
            path.lineTo(14.2, 6.8)
            pen = QPen(tick, 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


class Pill(QLabel):
    """Компактная метка: срок, ключ Jira, приоритет, продукт, простой."""

    def __init__(self, text: str, color: str, strong: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.mono_font(8))
        self.setStyleSheet(
            "color: %s; background: %s; border: 1px solid %s;"
            "border-radius: 9px; padding: 2px 7px;"
            % (color, theme.tint(color, 0.20 if strong else 0.12), theme.tint(color, 0.34))
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class ProductPill(QWidget):
    """Метка продукта: цветная точка плюс название."""

    def __init__(self, name: str, color: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 8, 2)
        layout.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet("background: %s; border-radius: 3px;" % color)
        layout.addWidget(dot)

        label = QLabel(name)
        label.setFont(theme.mono_font(8))
        label.setStyleSheet("color: %s; background: transparent;" % color)
        layout.addWidget(label)

        self.setStyleSheet(
            "background: %s; border: 1px solid %s; border-radius: 9px;"
            % (theme.tint(color, 0.12), theme.tint(color, 0.30))
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self.colors = colors
        self.stale_days = stale_days
        self.product_color = product_color
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
        self.bar.setStyleSheet(
            "background: %s; border-top-left-radius: 10px;"
            "border-bottom-left-radius: 10px;" % bar_color
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
            border, background = c["border_soft"], c["surface"]
        self.setStyleSheet(
            "#taskRow { background: %s; border: 1px solid %s; border-radius: 10px; }"
            "#taskRow:hover { background: %s; border-color: %s; }"
            % (background, border, c["surface_hover"], c["border"] if not selected else c["accent"])
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
        self.count.setFont(theme.mono_font(8))
        layout.addWidget(self.count)

        self.set_active(False)

    def set_count(self, value: int) -> None:
        self.count.setText(str(value) if value else "")

    def set_active(self, active: bool) -> None:
        c = self.colors
        background = c["surface_alt"] if active else "transparent"
        text = c["text"] if active else c["text_dim"]
        self.setStyleSheet(
            "#navItem { background: %s; border-radius: 7px; }"
            "#navItem:hover { background: %s; }" % (background, c["surface_alt"])
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
