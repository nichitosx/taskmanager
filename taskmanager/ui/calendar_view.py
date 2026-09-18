"""Календарь месяца: где какие задачи по срокам.

Списки отвечают на вопрос «чем заняться сейчас», а календарь — на вопрос «как
распределена работа по дням». Видно скопления сроков, пустые дни и то, что
подкрадывается через неделю.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QScrollArea,
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
from ..integrations import ics
from ..reports import MONTH_NAMES, WEEKDAY_NAMES, fmt_date_long
from ..storage import Storage
from . import theme
from .widgets import Card, elide_text, hline, manage_window, section_label

WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# MONTH_NAMES из отчётов стоят в родительном падеже («12 сентября»), а над
# сеткой месяца нужен именительный: «Сентябрь 2026».
MONTH_NOMINATIVE = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class DayCell(Card):
    """Клетка календаря: число, счётчик задач и первые названия."""

    picked = Signal(object)
    add_here = Signal(object)   # двойной клик по дню — завести дело на него

    def __init__(
        self,
        day: date,
        tasks: list[Task],
        colors: dict[str, str],
        current_month: bool,
        reminders: list | None = None,
        tall: bool = False,
        events: list | None = None,
        parent=None,
    ) -> None:
        super().__init__(colors, parent)
        self.day = day
        self.tasks = tasks
        self.reminders = reminders or []
        self.events = events or []
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # В недельном виде клеток всего семь — им можно отдать всю высоту.
        self.setMinimumHeight(240 if tall else 74)
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

        total = len(tasks) + len(self.reminders) + len(self.events)
        if total:
            count = QLabel(str(total))
            count.setFont(theme.accent_font(8))
            colour = colors["danger"] if overdue else colors["accent"]
            count.setStyleSheet("color: %s; background: transparent;" % colour)
            head.addWidget(count)
        layout.addLayout(head)

        # Названия подрезаем под ширину клетки — она меняется вместе с окном.
        self._lines: list[tuple[QLabel, str]] = []
        shown = 8 if tall else 2
        # Напоминания идут первыми: у них есть время, они привязаны к минуте.
        # Встречи идут первыми: они занимают время, всё остальное подстраивается.
        entries = [
            (("%s %s" % (e.clock(), e.title)).strip(), colors["success"])
            for e in self.events
        ]
        entries += [
            (("%s %s" % (r.at.strftime("%H:%M") if r.at else "", r.title)).strip(),
             colors["info"])
            for r in self.reminders
        ]
        entries += [(t.title, colors["text_dim"] if current_month else colors["text_faint"])
                    for t in tasks]

        for text, colour in entries[:shown]:
            line = QLabel()
            line.setFont(theme.mono_font(7))
            line.setStyleSheet("color: %s; background: transparent;" % colour)
            line.setToolTip(text)
            line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            line.setMinimumWidth(1)
            layout.addWidget(line)
            self._lines.append((line, text))

        if len(entries) > shown:
            more = QLabel("+%d" % (len(entries) - shown))
            more.setFont(theme.mono_font(7))
            more.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
            layout.addWidget(more)
        layout.addStretch(1)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.add_here.emit(self.day)
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        available = max(30, self.width() - 18)
        for label, title in getattr(self, "_lines", []):
            label.setText(elide_text(label.fontMetrics(), title, available))
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.picked.emit(self.day)
        super().mousePressEvent(event)


VIEW_WEEK = "week"
VIEW_MONTH = "month"


class TimeBlock(QFrame):
    """Запись на сетке недели: встреча, напоминание или задача со сроком."""

    picked = Signal(object)

    def __init__(self, text: str, colour: str, colors: dict[str, str],
                 tooltip: str = "", payload=None, parent=None) -> None:
        super().__init__(parent)
        self.payload = payload
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setStyleSheet(
            "background: %s; border-left: 3px solid %s; border-radius: %dpx;"
            % (theme.tint(colour, 0.22), colour, theme.radius("small"))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 4, 3)
        layout.setSpacing(0)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setFont(theme.mono_font(7))
        self.label.setStyleSheet("color: %s; background: transparent;" % colors["text"])
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.picked.emit(self.payload)
        super().mousePressEvent(event)


class WeekTimeGrid(QWidget):
    """Семь дней по горизонтали, часы по вертикали.

    Так видно не только «что назначено», но и «когда свободно»: пустое место
    между блоками — это и есть время, в которое можно взяться за задачу.
    """

    HOUR = 46          # высота одного часа
    GUTTER = 52        # ширина колонки с часами
    GAP = 3            # зазор между блоком и краем колонки

    picked_day = Signal(object)          # кликнули по колонке дня
    picked_slot = Signal(object, int)    # день и час — двойной клик по пустому месту
    picked_entry = Signal(object)        # кликнули по записи

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.days: list[date] = []
        self.entries: dict = {}
        self.selected: date | None = None
        self.first_hour = 8
        self.last_hour = 20
        self.setMouseTracking(True)

    # --- Данные ---------------------------------------------------------------

    def set_week(self, days: list, entries: dict, selected=None) -> None:
        """Записи: по дню список (начало, конец, текст, цвет, подсказка, что это)."""
        self.days = list(days)
        self.entries = entries or {}
        self.selected = selected
        self._fit_hours()
        self._rebuild()

    def _fit_hours(self) -> None:
        """Рабочий день по умолчанию, но края раздвигаем под реальные встречи."""
        first, last = 8, 20
        for items in self.entries.values():
            for start, end, *_ in items:
                if start is None:
                    continue
                first = min(first, start.hour)
                last = max(last, (end or start).hour + 1)
        self.first_hour = max(0, first)
        self.last_hour = min(24, max(last, self.first_hour + 4))
        self.setMinimumHeight((self.last_hour - self.first_hour) * self.HOUR + 8)

    def _rebuild(self) -> None:
        for block in self.findChildren(TimeBlock):
            block.setParent(None)
            block.deleteLater()
        self._blocks: list[tuple] = []
        for index, day in enumerate(self.days):
            for entry in self.entries.get(day, []):
                start, end, text, colour, tooltip, payload = entry
                if start is None:
                    continue
                block = TimeBlock(text, colour, self.colors, tooltip, payload, self)
                block.picked.connect(self.picked_entry.emit)
                block.show()
                self._blocks.append((index, start, end, block))
        self._place_blocks()

    # --- Раскладка ------------------------------------------------------------

    def column_width(self) -> float:
        if not self.days:
            return 0.0
        return max(1.0, (self.width() - self.GUTTER) / len(self.days))

    def _y_of(self, moment) -> int:
        minutes = (moment.hour - self.first_hour) * 60 + moment.minute
        return int(minutes * self.HOUR / 60)

    def _place_blocks(self) -> None:
        width = self.column_width()
        for index, start, end, block in getattr(self, "_blocks", []):
            top = self._y_of(start)
            bottom = self._y_of(end) if end and end > start else top + self.HOUR // 2
            height = max(18, bottom - top)
            left = int(self.GUTTER + index * width) + self.GAP
            block.setGeometry(
                left, top + 1, max(20, int(width) - self.GAP * 2), height - 2
            )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._place_blocks()

    # --- Отрисовка ------------------------------------------------------------

    @staticmethod
    def _shade(color: str, alpha: int) -> QColor:
        """Полупрозрачный цвет для заливки.

        theme.tint отдаёт строку rgba(...) для таблиц стилей, а QColor такую
        строку не понимает и молча становится чёрным — поэтому альфу ставим сами.
        """
        shade = QColor(color)
        shade.setAlpha(alpha)
        return shade

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["bg"]))
        width = self.column_width()
        today = date.today()

        # Колонка выбранного дня и сегодняшнего — подсвечены.
        for index, day in enumerate(self.days):
            left = int(self.GUTTER + index * width)
            if day == today:
                painter.fillRect(
                    left, 0, int(width), self.height(),
                    self._shade(c["accent"], 26),
                )
            elif day == self.selected:
                painter.fillRect(
                    left, 0, int(width), self.height(), QColor(c["surface"])
                )

        painter.setFont(theme.mono_font(7))
        for hour in range(self.first_hour, self.last_hour + 1):
            y = (hour - self.first_hour) * self.HOUR
            painter.setPen(QColor(c["border_soft"]))
            painter.drawLine(self.GUTTER, y, self.width(), y)
            painter.setPen(QColor(c["text_faint"]))
            painter.drawText(6, y + 12, "%02d:00" % hour)

        painter.setPen(QColor(c["border_soft"]))
        for index in range(len(self.days) + 1):
            x = int(self.GUTTER + index * width)
            painter.drawLine(x, 0, x, self.height())

        # Линия «сейчас» — только если сегодняшний день на экране.
        if today in self.days and self.first_hour <= datetime.now().hour < self.last_hour:
            y = self._y_of(datetime.now())
            painter.setPen(QPen(QColor(c["accent"]), 2))
            painter.drawLine(self.GUTTER, y, self.width(), y)
        painter.end()

    # --- Мышь -----------------------------------------------------------------

    def _day_at(self, x: float):
        width = self.column_width()
        if not width or x < self.GUTTER:
            return None
        index = int((x - self.GUTTER) // width)
        return self.days[index] if 0 <= index < len(self.days) else None

    def _hour_at(self, y: float) -> int:
        return int(self.first_hour + max(0, y) // self.HOUR)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        day = self._day_at(event.position().x())
        if day is not None:
            self.picked_day.emit(day)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        day = self._day_at(event.position().x())
        if day is not None:
            self.picked_slot.emit(day, self._hour_at(event.position().y()))
        super().mouseDoubleClickEvent(event)


class CalendarDialog(QDialog):
    """Календарь дел: неделя крупно или месяц целиком.

    По умолчанию неделя — так же, как в привычных календарях: видно не общую
    россыпь сроков, а то, чем занят ближайший рабочий отрезок. Месяц остаётся
    под рукой для взгляда сверху.
    """

    open_task = Signal(int)
    add_task = Signal(object)        # завести задачу на этот день
    add_reminder = Signal(object)    # завести напоминание на этот день

    def __init__(self, storage: Storage, settings: Settings, parent=None,
                 events: list | None = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        # Встречи из внешнего календаря: их читает главное окно и передаёт сюда.
        self.events = list(events or [])
        self.colors = theme.palette(settings.get("theme", "dark"))
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self.view = settings.get("calendar_view", VIEW_WEEK)
        if self.view not in (VIEW_WEEK, VIEW_MONTH):
            self.view = VIEW_WEEK
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
        self.week_button = _button("Неделя", "flat")
        self.week_button.clicked.connect(lambda: self._set_view(VIEW_WEEK))
        head.addWidget(self.week_button)
        self.month_button = _button("Месяц", "flat")
        self.month_button.clicked.connect(lambda: self._set_view(VIEW_MONTH))
        head.addWidget(self.month_button)

        today_button = _button("Сегодня", "flat")
        today_button.clicked.connect(self._go_today)
        head.addWidget(today_button)
        self.prev_button = _button("←", "flat")
        self.prev_button.clicked.connect(lambda: self._shift(-1))
        head.addWidget(self.prev_button)
        self.next_button = _button("→", "flat")
        self.next_button.clicked.connect(lambda: self._shift(1))
        head.addWidget(self.next_button)
        layout.addLayout(head)

        # Выгрузка не обновляется сама — говорим об этом, пока не поздно.
        self.stale_note = QLabel("")
        self.stale_note.setWordWrap(True)
        self.stale_note.setFont(theme.mono_font(8))
        self.stale_note.setStyleSheet(
            "color: %s; background: transparent;" % self.colors["warning"]
        )
        self.stale_note.hide()
        layout.addWidget(self.stale_note)

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

        # Недельный вид: шапка с днями, полоса «весь день» и сетка часов.
        self.week_host = QWidget()
        week_layout = QVBoxLayout(self.week_host)
        week_layout.setContentsMargins(0, 0, 0, 0)
        week_layout.setSpacing(0)

        self.week_head = QWidget()
        self.week_head_row = QHBoxLayout(self.week_head)
        self.week_head_row.setContentsMargins(0, 0, 0, 6)
        self.week_head_row.setSpacing(0)
        week_layout.addWidget(self.week_head)

        self.all_day_row = QWidget()
        self.all_day_layout = QHBoxLayout(self.all_day_row)
        self.all_day_layout.setContentsMargins(0, 0, 0, 6)
        self.all_day_layout.setSpacing(0)
        week_layout.addWidget(self.all_day_row)

        self.week_scroll = QScrollArea()
        self.week_scroll.setWidgetResizable(True)
        self.week_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.week_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.week_grid = WeekTimeGrid(self.colors)
        self.week_grid.picked_day.connect(self._pick_day)
        self.week_grid.picked_slot.connect(self._add_on_slot)
        self.week_grid.picked_entry.connect(self._open_entry)
        self.week_scroll.setWidget(self.week_grid)
        week_layout.addWidget(self.week_scroll, 1)

        left.addWidget(self.week_host, 1)

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

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        add_task_button = _button("+ Задача", "flat")
        add_task_button.clicked.connect(lambda: self.add_task.emit(self.selected))
        add_row.addWidget(add_task_button)
        add_reminder_button = _button("+ Напоминание", "flat")
        add_reminder_button.clicked.connect(lambda: self.add_reminder.emit(self.selected))
        add_row.addWidget(add_reminder_button)
        add_row.addStretch(1)
        right.addLayout(add_row)

        hint = QLabel(
            "Двойной клик по задаче открывает её карточку, двойной клик по дню "
            "заводит на него дело."
        )
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

    def _reminders_by_day(self) -> dict:
        by_day: dict = {}
        for reminder in self.storage.list_reminders(include_done=True, limit=500):
            if reminder.when is None or reminder.done:
                continue
            by_day.setdefault(reminder.when, []).append(reminder)
        for items in by_day.values():
            items.sort(key=lambda r: r.at or r.created_at)
        return by_day

    def _events_by_day(self) -> dict:
        by_day: dict = {}
        for event in self.events:
            if event.when is None:
                continue
            by_day.setdefault(event.when, []).append(event)
        return by_day

    def _week_entries(self, days: list) -> tuple[dict, dict]:
        """Записи недели: со временем — на сетку, без времени — в полосу сверху."""
        tasks = self._tasks_by_day()
        reminders = self._reminders_by_day()
        meetings = self._events_by_day()

        timed: dict = {day: [] for day in days}
        all_day: dict = {day: [] for day in days}

        for day in days:
            for event in meetings.get(day, []):
                text = "%s %s" % (event.clock(), event.title)
                tip = "Встреча%s" % (" · %s" % event.location if event.location else "")
                if event.all_day or event.at is None:
                    all_day[day].append((event.title, self.colors["success"], tip, None))
                else:
                    timed[day].append((
                        event.at, event.until, text, self.colors["success"], tip, None
                    ))

            for reminder in reminders.get(day, []):
                if reminder.at is None:
                    continue
                timed[day].append((
                    reminder.at,
                    None,
                    "%s %s" % (reminder.at.strftime("%H:%M"), reminder.title),
                    self.colors["info"],
                    "Напоминание",
                    ("reminder", reminder.id),
                ))

            # У задач есть срок, но нет часа — им место в полосе «весь день».
            for task in tasks.get(day, []):
                all_day[day].append((
                    task.title,
                    self.colors["accent"] if task.is_overdue else self.colors["warning"],
                    "Задача · срок",
                    ("task", task.id),
                ))

        for items in timed.values():
            items.sort(key=lambda entry: entry[0])
        return timed, all_day

    def _fill_week_head(self, days: list, all_day: dict) -> None:
        """Числа дней сверху и полоса задач на весь день под ними."""
        for row in (self.week_head_row, self.all_day_layout):
            while row.count():
                item = row.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()

        gutter = QWidget()
        gutter.setFixedWidth(WeekTimeGrid.GUTTER)
        self.week_head_row.addWidget(gutter)
        gutter_two = QWidget()
        gutter_two.setFixedWidth(WeekTimeGrid.GUTTER)
        self.all_day_layout.addWidget(gutter_two)

        today = date.today()
        for day in days:
            head = QWidget()
            head.setCursor(Qt.CursorShape.PointingHandCursor)
            column = QVBoxLayout(head)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(1)

            name = QLabel(WEEKDAY_SHORT[day.weekday()])
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setProperty("section", "true")
            column.addWidget(name)

            number = QLabel(str(day.day))
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFont(theme.ui_font(14, bold=day == today))
            number.setStyleSheet(
                "color: %s; background: transparent;"
                % (self.colors["accent"] if day == today
                   else (self.colors["text"] if day == self.selected
                         else self.colors["text_dim"]))
            )
            column.addWidget(number)
            head.mousePressEvent = (  # type: ignore[assignment]
                lambda _event, picked=day: self._pick_day(picked)
            )
            self.week_head_row.addWidget(head, 1)

            strip = QWidget()
            strip_layout = QVBoxLayout(strip)
            strip_layout.setContentsMargins(2, 0, 2, 0)
            strip_layout.setSpacing(2)
            for title, colour, tip, payload in all_day.get(day, [])[:3]:
                block = TimeBlock(title, colour, self.colors, tip, payload)
                block.setFixedHeight(18)
                block.picked.connect(self._open_entry)
                strip_layout.addWidget(block)
            extra = len(all_day.get(day, [])) - 3
            if extra > 0:
                more = QLabel("+%d" % extra)
                more.setFont(theme.mono_font(7))
                more.setStyleSheet(
                    "color: %s; background: transparent;" % self.colors["text_faint"]
                )
                strip_layout.addWidget(more)
            self.all_day_layout.addWidget(strip, 1)

    def _add_on_slot(self, day, hour: int) -> None:
        """Двойной клик по пустому месту — напоминание на это время."""
        self.add_reminder.emit(datetime.combine(day, time(hour=min(23, hour))))

    def _open_entry(self, payload) -> None:
        if not payload:
            return
        kind, identifier = payload
        if kind == "task":
            self.open_task.emit(int(identifier))
            self.accept()

    def _week_start(self) -> date:
        return self.selected - timedelta(days=self.selected.weekday())

    def _set_view(self, view: str) -> None:
        self.view = view
        self.settings.set("calendar_view", view)
        self.settings.save()
        self.refresh()

    def _shift(self, step: int) -> None:
        """Шаг вперёд или назад: неделя в недельном виде, месяц в месячном."""
        if self.view == VIEW_WEEK:
            self.selected = self.selected + timedelta(days=7 * step)
            self.month = self.selected.replace(day=1)
            self.refresh()
            return
        self._shift_month(step)

    def _shift_month(self, months: int) -> None:
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

    def _sync_view_buttons(self) -> None:
        for button, view in ((self.week_button, VIEW_WEEK),
                             (self.month_button, VIEW_MONTH)):
            button.setProperty("accent", "true" if self.view == view else "false")
            button.style().unpolish(button)
            button.style().polish(button)
        self.prev_button.setToolTip(
            "Прошлая неделя" if self.view == VIEW_WEEK else "Прошлый месяц"
        )
        self.next_button.setToolTip(
            "Следующая неделя" if self.view == VIEW_WEEK else "Следующий месяц"
        )

    def _sync_stale_note(self) -> None:
        note = ics.staleness_note(self.settings.get("calendar.ics_url", ""))
        self.stale_note.setText(note)
        self.stale_note.setVisible(bool(note))

    def refresh(self) -> None:
        self._sync_stale_note()
        for cell in self.grid_host.findChildren(DayCell):
            self.grid.removeWidget(cell)
            # Родителя снимаем сразу: deleteLater отложит удаление до следующего
            # круга событий, и при переключении вида клетки на миг удвоились бы.
            cell.setParent(None)
            cell.deleteLater()
        for row in range(1, 8):
            self.grid.setRowStretch(row, 0)

        by_day = self._tasks_by_day()
        reminders = self._reminders_by_day()
        meetings = self._events_by_day()
        week_view = self.view == VIEW_WEEK

        if week_view:
            first = self._week_start()
            weeks = 1
            last = first + timedelta(days=6)
            self.title.setText(
                "%d—%d %s %d"
                % (first.day, last.day,
                   MONTH_NAMES[last.month - 1], last.year)
                if first.month == last.month
                else "%d %s — %d %s %d"
                % (first.day, MONTH_NAMES[first.month - 1],
                   last.day, MONTH_NAMES[last.month - 1], last.year)
            )
        else:
            first = self.month - timedelta(days=self.month.weekday())
            weeks = 6 if calendar.monthrange(
                self.month.year, self.month.month
            )[1] > 28 else 5
            self.title.setText(
                "%s %d"
                % (MONTH_NOMINATIVE[self.month.month - 1].capitalize(), self.month.year)
            )

        self.grid_host.setVisible(not week_view)
        self.week_host.setVisible(week_view)
        if week_view:
            days = [first + timedelta(days=shift) for shift in range(7)]
            timed, all_day = self._week_entries(days)
            self._fill_week_head(days, all_day)
            self.week_grid.set_week(days, timed, self.selected)
            self._sync_view_buttons()
            self._show_day(self.selected)
            return

        for week in range(weeks):
            for weekday in range(7):
                day = first + timedelta(days=week * 7 + weekday)
                cell = DayCell(
                    day,
                    by_day.get(day, []),
                    self.colors,
                    week_view or day.month == self.month.month,
                    reminders.get(day, []),
                    tall=week_view,
                    events=meetings.get(day, []),
                )
                cell.picked.connect(self._pick_day)
                cell.add_here.connect(self.add_task.emit)
                self.grid.addWidget(cell, week + 1, weekday)
            self.grid.setRowStretch(week + 1, 1)

        self._sync_view_buttons()
        self._show_day(self.selected)

    def _pick_day(self, day: date) -> None:
        self.selected = day
        if self.view == VIEW_MONTH and day.month != self.month.month:
            self.month = day.replace(day=1)
            self.refresh()
        else:
            self._show_day(day)

    def _show_day(self, day: date) -> None:
        self.day_title.setText(fmt_date_long(day).capitalize())
        self.day_list.clear()
        tasks = self._tasks_by_day().get(day, [])
        reminders = self._reminders_by_day().get(day, [])
        if not tasks and not reminders and not self._events_by_day().get(day):
            item = QListWidgetItem("На этот день ничего не назначено")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.day_list.addItem(item)
            return

        for event in self._events_by_day().get(day, []):
            item = QListWidgetItem("%s  %s" % (event.clock(), event.title))
            item.setToolTip("Встреча из календаря%s"
                            % (" · %s" % event.location if event.location else ""))
            self.day_list.addItem(item)

        for reminder in reminders:
            clock = reminder.at.strftime("%H:%M") if reminder.at else "--:--"
            item = QListWidgetItem("%s  %s" % (clock, reminder.title))
            item.setToolTip("Напоминание")
            self.day_list.addItem(item)

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
