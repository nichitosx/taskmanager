"""Модели предметной области."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

# --- Приоритеты ---------------------------------------------------------------

# Пять ступеней: ровно столько полосок показывает строка задачи, и одна
# полоска — самая спокойная задача, пять — то, что горит.
PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_NOTABLE = 2
PRIORITY_HIGH = 3
PRIORITY_CRITICAL = 4

# Прежнее название: до появления пятой ступени «высоким» считался уровень 2.
PRIORITY_HIGH_OLD = PRIORITY_NOTABLE

PRIORITY_LABELS = {
    PRIORITY_LOW: "не особо важная",
    PRIORITY_NORMAL: "обычная",
    PRIORITY_NOTABLE: "заметная",
    PRIORITY_HIGH: "высокая",
    PRIORITY_CRITICAL: "критично",
}

# Сколько полосок закрашено: уровень 0 — одна, уровень 4 — все пять.
PRIORITY_LEVELS = len(PRIORITY_LABELS)

# --- Статусы ------------------------------------------------------------------

STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_ARCHIVED = "archived"

# --- Состояние привязки к Jira ------------------------------------------------

JIRA_UNKNOWN = "unknown"      # ещё не решено — попадёт в напоминания
JIRA_NOT_NEEDED = "not_needed"  # задача без Jira, это нормально
JIRA_CREATED = "created"      # issue заведена, ключ указан

JIRA_STATE_LABELS = {
    JIRA_UNKNOWN: "не решено",
    JIRA_NOT_NEEDED: "не нужна",
    JIRA_CREATED: "заведена",
}


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class Task:
    id: Optional[int] = None
    title: str = ""
    notes: str = ""
    status: str = STATUS_ACTIVE
    priority: int = PRIORITY_NORMAL
    due_date: Optional[date] = None
    start_date: Optional[date] = None
    product: str = ""
    # Правило повторения, см. recurrence.py: "", "daily", "weekly:2", "monthly:15".
    repeat: str = ""
    jira_key: str = ""
    jira_state: str = JIRA_UNKNOWN
    tags: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None

    # --- Производные признаки -------------------------------------------------

    @property
    def is_done(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def days_since_activity(self) -> int:
        moment = self.last_activity_at or self.updated_at or self.created_at
        if moment is None:
            return 0
        return (datetime.now() - moment).days

    @property
    def days_to_start(self) -> Optional[int]:
        if self.start_date is None:
            return None
        return (self.start_date - date.today()).days

    @property
    def is_planned(self) -> bool:
        """Задача ещё не началась: дата старта в будущем."""
        days = self.days_to_start
        return not self.is_done and days is not None and days > 0

    def starts_within(self, days: int) -> bool:
        """Старт задачи наступит не позже чем через ``days`` дней."""
        left = self.days_to_start
        return self.is_planned and left is not None and left <= days

    @property
    def days_to_due(self) -> Optional[int]:
        if self.due_date is None:
            return None
        return (self.due_date - date.today()).days

    @property
    def is_overdue(self) -> bool:
        days = self.days_to_due
        return not self.is_done and not self.is_planned and days is not None and days < 0

    def is_stale(self, stale_days: int) -> bool:
        if self.is_done or self.is_planned:
            return False
        return self.days_since_activity >= stale_days

    def needs_jira(self) -> bool:
        """Нужно ли ещё решить вопрос с Jira по этой задаче."""
        if self.jira_state == JIRA_CREATED and self.jira_key:
            return False
        return self.jira_state != JIRA_NOT_NEEDED

    @classmethod
    def from_row(cls, row) -> "Task":
        tags = [t for t in (row["tags"] or "").split(",") if t]
        return cls(
            id=row["id"],
            title=row["title"],
            notes=row["notes"] or "",
            status=row["status"],
            priority=row["priority"],
            due_date=_parse_date(row["due_date"]),
            start_date=_parse_date(row["start_date"]) if "start_date" in row.keys() else None,
            product=(row["product"] or "") if "product" in row.keys() else "",
            repeat=(row["repeat_rule"] or "") if "repeat_rule" in row.keys() else "",
            jira_key=row["jira_key"] or "",
            jira_state=row["jira_state"] or JIRA_UNKNOWN,
            tags=tags,
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            done_at=_parse_dt(row["done_at"]),
            last_activity_at=_parse_dt(row["last_activity_at"]),
        )


@dataclass
class Subtask:
    """Подпункт задачи: маленький шаг внутри большой работы."""

    id: Optional[int] = None
    task_id: Optional[int] = None
    title: str = ""
    done: bool = False
    position: int = 0
    created_at: Optional[datetime] = None
    done_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row) -> "Subtask":
        return cls(
            id=row["id"],
            task_id=row["task_id"],
            title=row["title"] or "",
            done=bool(row["done"]),
            position=row["position"] or 0,
            created_at=_parse_dt(row["created_at"]),
            done_at=_parse_dt(row["done_at"]),
        )


@dataclass
class WorkLog:
    """Отметка о работе по задаче за конкретный день."""

    id: Optional[int] = None
    task_id: Optional[int] = None
    log_date: Optional[date] = None
    comment: str = ""
    created_at: Optional[datetime] = None
    task_title: str = ""
    task_jira_key: str = ""
    task_jira_state: str = JIRA_UNKNOWN

    @classmethod
    def from_row(cls, row) -> "WorkLog":
        keys = row.keys()
        return cls(
            id=row["id"],
            task_id=row["task_id"],
            log_date=_parse_date(row["log_date"]),
            comment=row["comment"] or "",
            created_at=_parse_dt(row["created_at"]),
            task_title=row["task_title"] if "task_title" in keys else "",
            task_jira_key=(row["task_jira_key"] or "") if "task_jira_key" in keys else "",
            task_jira_state=(row["task_jira_state"] or JIRA_UNKNOWN) if "task_jira_state" in keys else JIRA_UNKNOWN,
        )


@dataclass
class DailyReport:
    log_date: date
    note: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    logs: list[WorkLog] = field(default_factory=list)
