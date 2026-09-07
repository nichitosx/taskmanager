"""Планировщик напоминаний: отчёт в конце дня и недельный отчёт.

Работает на таймере внутри приложения: раз в минуту проверяет, не пора ли
напомнить. Если программа была выключена в нужный момент, напоминание сработает
при первом же запуске в этот день — момент не теряется.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from .config import Settings
from .reports import week_bounds
from .storage import Storage

CHECK_INTERVAL_MS = 60_000

META_EOD = "last_eod_prompt"
META_WEEKLY = "last_weekly_prompt"
META_MISSED = "last_missed_prompt"
META_STARTS = "announced_starts"

# Сколько отметок о показанных плановых задачах храним, чтобы meta не пухла.
STARTS_MEMORY = 200


def _parse_time(value: str, default: time) -> time:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return default


class Scheduler(QObject):
    """Следит за временем и подаёт сигналы главному окну."""

    eod_due = Signal()                 # пора заполнить отчёт за сегодня
    weekly_due = Signal(object)        # пора собрать недельный отчёт (дата понедельника)
    missed_report = Signal(object)     # за прошлый рабочий день отчёта нет
    starts_soon = Signal(object)       # плановые задачи, которые скоро начнутся

    def __init__(self, storage: Storage, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)

    def start(self) -> None:
        self.timer.start()
        # Первая проверка сразу после запуска — вдруг время уже прошло.
        QTimer.singleShot(2500, self.check)

    def stop(self) -> None:
        self.timer.stop()

    # --- Проверки -------------------------------------------------------------

    def check(self) -> None:
        now = datetime.now()
        self._check_eod(now)
        self._check_weekly(now)
        self._check_missed(now)
        self._check_starts(now)

    def _check_eod(self, now: datetime) -> None:
        if not self.settings.get("eod.enabled", True):
            return
        weekdays = self.settings.get("eod.weekdays", [0, 1, 2, 3, 4]) or []
        if now.weekday() not in weekdays:
            return
        target = _parse_time(self.settings.get("eod.time", "17:30"), time(17, 30))
        if now.time() < target:
            return
        today = now.date().isoformat()
        if self.storage.get_meta(META_EOD) == today:
            return
        if self.storage.has_saved_report(now.date()):
            return
        self.storage.set_meta(META_EOD, today)
        self.eod_due.emit()

    def _check_weekly(self, now: datetime) -> None:
        if not self.settings.get("weekly.enabled", True):
            return
        weekday = self.settings.get_int("weekly.weekday", 4)
        if now.weekday() != weekday:
            return
        target = _parse_time(self.settings.get("weekly.time", "09:30"), time(9, 30))
        if now.time() < target:
            return
        start, _ = week_bounds(now.date())
        if self.storage.get_meta(META_WEEKLY) == start.isoformat():
            return
        self.storage.set_meta(META_WEEKLY, start.isoformat())
        self.weekly_due.emit(start)

    def _check_missed(self, now: datetime) -> None:
        """Мягкое напоминание утром, если вчерашний отчёт остался незаполненным."""
        if not self.settings.get("eod.enabled", True):
            return
        if now.hour < 8 or now.hour >= 12:
            return
        previous = self._previous_workday(now.date())
        if previous is None:
            return
        if self.storage.get_meta(META_MISSED) == previous.isoformat():
            return
        if self.storage.has_saved_report(previous):
            return
        self.storage.set_meta(META_MISSED, previous.isoformat())
        self.missed_report.emit(previous)

    def _check_starts(self, now: datetime) -> None:
        """Предупреждение о плановых задачах, до старта которых осталось немного.

        Про каждую задачу говорим один раз: помним пару «id + дата старта», так
        что повторное напоминание придёт, только если дату сдвинули.
        """
        if not self.settings.get("planning.notify_enabled", True):
            return
        if now.hour < 8 or now.hour >= 21:
            return
        days = self.settings.get_int("planning.notify_days", 7)
        upcoming = self.storage.upcoming_starts(days)
        if not upcoming:
            return
        known = self._announced()
        fresh = [t for t in upcoming if self._mark(t) not in known]
        if not fresh:
            return
        self._remember(known | {self._mark(t) for t in fresh})
        self.starts_soon.emit(fresh)

    @staticmethod
    def _mark(task) -> str:
        return "%s:%s" % (task.id, task.start_date.isoformat() if task.start_date else "")

    def _announced(self) -> set[str]:
        raw = self.storage.get_meta(META_STARTS, "")
        return {part for part in raw.split(",") if part}

    def _remember(self, marks: set[str]) -> None:
        self.storage.set_meta(META_STARTS, ",".join(sorted(marks)[-STARTS_MEMORY:]))

    def _previous_workday(self, today: date) -> date | None:
        weekdays = self.settings.get("eod.weekdays", [0, 1, 2, 3, 4]) or []
        day = today - timedelta(days=1)
        for _ in range(7):
            if day.weekday() in weekdays:
                return day
            day -= timedelta(days=1)
        return None

    # --- Ручной сброс ---------------------------------------------------------

    def mark_eod_handled(self, day: date | None = None) -> None:
        self.storage.set_meta(META_EOD, (day or date.today()).isoformat())
