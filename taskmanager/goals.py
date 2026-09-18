"""Цели на квартал: то, ради чего делаются задачи.

Задача живёт неделю, цель — квартал. Их две-три на квартал, и смотреть на них
нужно не в списке дел, а сверху: поэтому у целей своя таблица, свой раздел в
боковом меню и своё место над списком задач.

У цели есть комментарий — как идут дела — и контрольные результаты: короткие
пункты, по которым видно, что цель не стоит на месте.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

STATUS_ACTIVE = "active"
STATUS_DONE = "done"

QUARTER_MONTHS = 3


def quarter_of(day: Optional[date] = None) -> str:
    """Квартал, в который попадает день: «2026-Q3»."""
    day = day or date.today()
    return "%d-Q%d" % (day.year, (day.month - 1) // QUARTER_MONTHS + 1)


def quarter_bounds(quarter: str) -> tuple[date, date]:
    """Первый и последний день квартала. Кривая строка — текущий квартал."""
    try:
        year, number = quarter.split("-Q")
        year, number = int(year), int(number)
        if not 1 <= number <= 4:
            raise ValueError(quarter)
    except (ValueError, AttributeError):
        return quarter_bounds(quarter_of())
    first_month = (number - 1) * QUARTER_MONTHS + 1
    start = date(year, first_month, 1)
    if number == 4:
        return start, date(year, 12, 31)
    return start, date(year, first_month + QUARTER_MONTHS, 1) - timedelta(days=1)


def quarter_title(quarter: str) -> str:
    """Человеческое название квартала: «III квартал 2026»."""
    romans = {1: "I", 2: "II", 3: "III", 4: "IV"}
    try:
        year, number = quarter.split("-Q")
        return "%s квартал %s" % (romans.get(int(number), number), year)
    except (ValueError, AttributeError):
        return quarter


def shift_quarter(quarter: str, step: int) -> str:
    """Соседний квартал: шаг вперёд или назад."""
    try:
        year, number = quarter.split("-Q")
        total = int(year) * 4 + (int(number) - 1) + step
    except (ValueError, AttributeError):
        return quarter_of()
    return "%d-Q%d" % (total // 4, total % 4 + 1)


@dataclass
class GoalResult:
    """Контрольный результат цели — как подпункт у задачи."""

    id: Optional[int] = None
    goal_id: Optional[int] = None
    title: str = ""
    done: bool = False
    position: int = 0
    created_at: Optional[datetime] = None
    done_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row) -> "GoalResult":
        return cls(
            id=row["id"],
            goal_id=row["goal_id"],
            title=row["title"] or "",
            done=bool(row["done"]),
            position=row["position"] or 0,
            created_at=_parse_dt(row["created_at"]),
            done_at=_parse_dt(row["done_at"]),
        )


@dataclass
class Goal:
    """Цель на квартал."""

    id: Optional[int] = None
    title: str = ""
    comment: str = ""
    quarter: str = field(default_factory=quarter_of)
    status: str = STATUS_ACTIVE
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    done_at: Optional[datetime] = None

    @property
    def is_done(self) -> bool:
        return self.status == STATUS_DONE

    @classmethod
    def from_row(cls, row) -> "Goal":
        return cls(
            id=row["id"],
            title=row["title"] or "",
            comment=row["comment"] or "",
            quarter=row["quarter"] or quarter_of(),
            status=row["status"] or STATUS_ACTIVE,
            position=row["position"] or 0,
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            done_at=_parse_dt(row["done_at"]),
        )


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
