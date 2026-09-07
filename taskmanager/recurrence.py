"""Повторяющиеся задачи: «каждый понедельник», «каждое 15-е число» и подобное.

Правило хранится строкой в самой задаче, чтобы не заводить отдельную таблицу:

``""``            — не повторять
``daily``         — каждый день
``days:<n>``      — раз в n дней
``weekly:<0-6>``  — каждую неделю в этот день (0 — понедельник)
``monthly:<1-31>``— каждый месяц этого числа (если числа нет — последний день)

Следующее вхождение создаётся, когда текущее отмечают выполненным: так история
работы остаётся привязанной к конкретному разу, а не размазывается по одной
вечной задаче.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

NONE = ""
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
EVERY_DAYS = "days"

WEEKDAY_SHORT = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]


def parse(rule: str) -> tuple[str, int]:
    """Разбирает правило в пару (тип, число). Мусор превращается в «не повторять»."""
    rule = (rule or "").strip().lower()
    if not rule:
        return NONE, 0
    if rule == DAILY:
        return DAILY, 1
    if ":" not in rule:
        return NONE, 0
    kind, _, value = rule.partition(":")
    if not value.lstrip("-").isdigit():
        return NONE, 0
    number = int(value)
    if kind == WEEKLY and 0 <= number <= 6:
        return WEEKLY, number
    if kind == MONTHLY and 1 <= number <= 31:
        return MONTHLY, number
    if kind == EVERY_DAYS and number >= 1:
        return EVERY_DAYS, number
    return NONE, 0


def is_repeating(rule: str) -> bool:
    return parse(rule)[0] != NONE


def make(kind: str, number: int = 0) -> str:
    if kind == DAILY:
        return DAILY
    if kind in (WEEKLY, MONTHLY, EVERY_DAYS):
        return "%s:%d" % (kind, number)
    return NONE


def describe(rule: str) -> str:
    """Человеческая подпись правила: «каждое 15-е число»."""
    kind, number = parse(rule)
    if kind == DAILY:
        return "каждый день"
    if kind == EVERY_DAYS:
        return "раз в %d дн." % number
    if kind == WEEKLY:
        return "каждую %s" % WEEKDAY_SHORT[number]
    if kind == MONTHLY:
        return "каждое %d-е число" % number
    return ""


def _clamp_day(year: int, month: int, day: int) -> date:
    """Ставит число месяца, укорачивая до последнего дня короткого месяца."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def next_date(rule: str, previous: date, after: date | None = None) -> date | None:
    """Следующая дата после ``previous`` (и не раньше ``after``).

    ``after`` нужен, чтобы догнать пропущенные повторы: если задачу закрыли через
    месяц, следующая должна быть в будущем, а не во вчера.
    """
    kind, number = parse(rule)
    if kind == NONE:
        return None
    after = after or date.today()

    moment = previous
    for _ in range(400):  # предохранитель от бесконечного цикла
        if kind == DAILY:
            moment = moment + timedelta(days=1)
        elif kind == EVERY_DAYS:
            moment = moment + timedelta(days=number)
        elif kind == WEEKLY:
            step = (number - moment.weekday() - 1) % 7 + 1
            moment = moment + timedelta(days=step)
        elif kind == MONTHLY:
            year, month = moment.year, moment.month
            month += 1
            if month > 12:
                month, year = 1, year + 1
            moment = _clamp_day(year, month, number)
        if moment > after:
            return moment
    return moment


def next_occurrence(task, after: date | None = None):
    """Копия задачи со сдвинутыми датами. None, если задача не повторяется.

    Сдвигаем и срок, и дату начала — расстояние между ними сохраняется.
    """
    from copy import deepcopy

    if not is_repeating(task.repeat):
        return None
    anchor = task.due_date or task.start_date or date.today()
    following = next_date(task.repeat, anchor, after)
    if following is None:
        return None

    nxt = deepcopy(task)
    nxt.id = None
    nxt.status = "active"
    nxt.done_at = None
    nxt.created_at = None
    nxt.updated_at = None
    nxt.last_activity_at = None
    shift = following - anchor
    nxt.due_date = task.due_date + shift if task.due_date else following
    nxt.start_date = task.start_date + shift if task.start_date else None
    return nxt
