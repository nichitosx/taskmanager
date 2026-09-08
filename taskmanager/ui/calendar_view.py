"""Календарь месяца: где какие задачи по срокам.

Списки отвечают на вопрос «чем заняться сейчас», а календарь — на вопрос «как
распределена работа по дням». Видно скопления сроков, пустые дни и то, что
подкрадывается через неделю.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..models import Task
from ..reports import MONTH_NAMES, WEEKDAY_NAMES, fmt_date_long
from ..storage import Storage
from . import theme
from .widgets import Card, elide_text, hline, manage_window, section_label

WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class DayCell(Card):
    """Клетка календаря: число, счётчик задач и первые названия."""

    picked = Signal(object)

    def __init__(
        self,
        day: date,
        tasks: list[Task],
        colors: dict[str, str],
        current_month: bool,
        parent=None,
    ) -> None:
        super().__init__(colors, parent)
        self.day = day
        self.tasks = tasks
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(74)
        # Клетки одинаковой ширины: иначе длинное название задачи растягивает
        # свой столбец, а пустые дни ужимаются в полоску.
        self.setMinimumWidth(70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        today = date.today()
        overdue = [t for t in tasks if t.due_date and t.due_date < today and not t.is_done]
        if day == today:
            self.set_card_colors(
                bg=theme.tint(colors["accent"], 0.16), border=colors["accent"]
            )
        elif not current_month:
            self.set_card_colors(bg=colors["bg"], border=colors["border_soft"])
        elif overdue:
            self.set_card_colors(border=theme.tint(colors["danger"], 0.5))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 6)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)

        number = QLabel(str(day.day))
        number.setFont(theme.accent_font(9, bold=day == today))
        shade = colors["text"] if current_month else colors["text_faint"]
        number.setStyleSheet("color: %s; background: transparent;" % shade)
        head.addWidget(number)
        head.addStretch(1)

        if tasks:
            count = QLabel(str(len(tasks)))
            count.setFont(theme.accent_font(8))
            colour = colors["danger"] if overdue else colors["accent"]
            count.setStyleSheet("color: %s; background: transparent;" % colour)
            head.addWidget(count)
        layout.addLayout(head)

        # Названия подрезаем под ширину клетки — она меняется вместе с окном.
        self._lines: list[tuple[QLabel, str]] = []
        for task in tasks[:2]:
            line = QLabel()
            line.setFont(theme.mono_font(7))
            line.setStyleSheet(
                "color: %s; background: transparent;"
                % (colors["text_dim"] if current_month else colors["text_faint"])
            )
            line.setToolTip(task.title)
            line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            line.setMinimumWidth(1)
            layout.addWidget(line)
            self._lines.append((line, task.title))

        if len(tasks) > 2:
            more = QLabel("+%d" % (len(tasks) - 2))
            more.setFont(theme.mono_font(7))
            more.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
            layout.addWidget(more)
        layout.addStretch(1)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        available = max(30, self.width() - 18)
        for label, title in getattr(self, "_lines", []):
            label.setText(elide_text(label.fontMetrics(), title, available))
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.picked.emit(self.day)
        super().mousePressEvent(event)


class CalendarDialog(QDialog):
    """Месяц целиком: сроки задач по дням."""

    open_task = Signal(int)

    def __init__(self, storage: Storage, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.colors = theme.palette(settings.get("theme", "dark"))
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self.setWindowTitle("Календарь")
        self._build()
        self.refresh()
        manage_window(self, settings, "calendar", 900, 660)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setFont(theme.ui_font(13, bold=True))
        head.addWidget(self.title)
        head.addStretch(1)
        today_button = _button("Сегодня", "flat")
        today_button.clicked.connect(self._go_today)
        head.addWidget(today_button)
        previous = _button("← месяц", "flat")
        previous.clicked.connect(lambda: self._shift(-1))
        head.addWidget(previous)
        following = _button("месяц →", "flat")
        following.clicked.connect(lambda: self._shift(1))
        head.addWidget(following)
        layout.addLayout(head)
        layout.addWidget(hline())

        body = QHBoxLayout()
        body.setSpacing(14)
        layout.addLayout(body, 1)

        left_host = QWidget()
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        body.addWidget(left_host, 3)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        # Колонки одинаковой ширины: иначе выходные ужимаются, а подписи дней
        # недели перестают попадать в свои столбцы.
        for column in range(7):
            self.grid.setColumnStretch(column, 1)
        for column, name in enumerate(WEEKDAY_SHORT):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("section", "true")
            self.grid.addWidget(label, 0, column)
        left.addWidget(self.grid_host, 1)

        right_host = QWidget()
        right_host.setMinimumWidth(220)
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        body.addWidget(right_host, 2)

        self.day_title = QLabel()
        self.day_title.setWordWrap(True)
        self.day_title.setFont(theme.ui_font(11, bold=True))
        right.addWidget(self.day_title)

        self.day_list = QListWidget()
        self.day_list.setFont(theme.mono_font(9))
        self.day_list.itemDoubleClicked.connect(self._open_selected)
        right.addWidget(self.day_list, 1)

        hint = QLabel("Двойной клик по задаче открывает её карточку.")
        hint.setProperty("faint", "true")
        hint.setWordWrap(True)
        right.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = _button("Закрыть", "accent")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    # --- Данные ---------------------------------------------------------------

    def _tasks_by_day(self) -> dict[date, list[Task]]:
        tasks = self.storage.list_tasks(include_done=True)
        by_day: dict[date, list[Task]] = {}
        for task in tasks:
            if task.due_date is None or task.is_done:
                continue
            by_day.setdefault(task.due_date, []).append(task)
        for items in by_day.values():
            items.sort(key=lambda t: (-t.priority, t.title.lower()))
        return by_day

    def _shift(self, months: int) -> None:
        year, month = self.month.year, self.month.month + months
        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1
        self.month = date(year, month, 1)
        self.refresh()

    def _go_today(self) -> None:
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self.refresh()

    def refresh(self) -> None:
        self.title.setText(
            "%s %d" % (MONTH_NAMES[self.month.month - 1].capitalize(), self.month.year)
        )
        for cell in self.grid_host.findChildren(DayCell):
            self.grid.removeWidget(cell)
            cell.deleteLater()

        by_day = self._tasks_by_day()
        first = self.month - timedelta(days=self.month.weekday())
        weeks = 6 if calendar.monthrange(self.month.year, self.month.month)[1] > 28 else 5

        for week in range(weeks):
            for weekday in range(7):
                day = first + timedelta(days=week * 7 + weekday)
                cell = DayCell(
                    day, by_day.get(day, []), self.colors, day.month == self.month.month
                )
                cell.picked.connect(self._pick_day)
                self.grid.addWidget(cell, week + 1, weekday)
            self.grid.setRowStretch(week + 1, 1)

        self._show_day(self.selected)

    def _pick_day(self, day: date) -> None:
        self.selected = day
        if day.month != self.month.month:
            self.month = day.replace(day=1)
            self.refresh()
        else:
            self._show_day(day)

    def _show_day(self, day: date) -> None:
        self.day_title.setText(fmt_date_long(day).capitalize())
        self.day_list.clear()
        tasks = self._tasks_by_day().get(day, [])
        if not tasks:
            item = QListWidgetItem("На этот день задач нет")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.day_list.addItem(item)
            return
        for task in tasks:
            mark = "!" * max(0, task.priority - 1)
            title = "%s %s" % (mark.ljust(2), task.title) if mark else "   " + task.title
            item = QListWidgetItem(title.strip())
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            if task.product:
                item.setToolTip("%s · %s" % (task.product, task.title))
            self.day_list.addItem(item)

    def _open_selected(self, item: QListWidgetItem) -> None:
        task_id = item.data(Qt.ItemDataRole.UserRole)
        if task_id is not None:
            self.open_task.emit(int(task_id))
            self.accept()
