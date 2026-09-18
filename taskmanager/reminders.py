"""Напоминания: то, что нужно не сделать, а не забыть.

Задача — работа, по которой отчитываются. Напоминание — «написать Ивану в
четверг», «забрать пропуск», «позвонить в 15:40». Работой это не считается и в
недельный отчёт не попадает: иначе отчёт превратился бы в список бытовых дел.

У напоминания есть время, а не срок: смысл в том, чтобы оно всплыло вовремя.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass
class Reminder:
    """Напоминание на конкретный момент времени."""

    id: Optional[int] = None
    title: str = ""
    notes: str = ""
    at: Optional[datetime] = None
    done: bool = False
    # Ссылка на событие в Google-календаре, если напоминание туда отправляли.
    event_id: str = ""
    created_at: Optional[datetime] = None
    done_at: Optional[datetime] = None

    @property
    def when(self) -> Optional[date]:
        return self.at.date() if self.at else None

    @property
    def is_past(self) -> bool:
        return bool(self.at and self.at <= datetime.now())

    def in_minutes(self, now: Optional[datetime] = None) -> Optional[int]:
        """Через сколько минут наступит. Отрицательное — уже прошло."""
        if not self.at:
            return None
        delta = self.at - (now or datetime.now())
        return int(delta.total_seconds() // 60)

    @classmethod
    def from_row(cls, row) -> "Reminder":
        return cls(
            id=row["id"],
            title=row["title"] or "",
            notes=row["notes"] or "",
            at=_parse_dt(row["at_time"]),
            done=bool(row["done"]),
            event_id=row["event_id"] or "",
            created_at=_parse_dt(row["created_at"]),
            done_at=_parse_dt(row["done_at"]),
        )


def describe_when(moment: Optional[datetime], now: Optional[datetime] = None) -> str:
    """Человеческая подпись времени: «сегодня в 15:40», «через 20 минут»."""
    if moment is None:
        return "без времени"
    now = now or datetime.now()
    minutes = int((moment - now).total_seconds() // 60)

    if 0 <= minutes < 60:
        return "через %d мин" % minutes if minutes else "сейчас"
    if -60 < minutes < 0:
        return "%d мин назад" % -minutes

    day_shift = (moment.date() - now.date()).days
    clock = moment.strftime("%H:%M")
    if day_shift == 0:
        return "сегодня в %s" % clock
    if day_shift == 1:
        return "завтра в %s" % clock
    if day_shift == -1:
        return "вчера в %s" % clock
    return "%s в %s" % (moment.strftime("%d.%m"), clock)


def next_slot(now: Optional[datetime] = None) -> datetime:
    """Разумное время по умолчанию: ближайшие полчаса вперёд."""
    now = now or datetime.now()
    base = now.replace(second=0, microsecond=0) + timedelta(minutes=30)
    minute = 0 if base.minute < 30 else 30
    return base.replace(minute=minute)


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
