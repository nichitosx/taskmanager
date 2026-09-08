"""Горизонты планирования: сегодня, на неделе, в этом месяце, плановые.

Один и тот же набор правил используют и боковые фильтры, и счётчики — чтобы
цифра рядом со списком всегда совпадала с тем, что в нём видно.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from .models import Task

HORIZON_TODAY = "today"
HORIZON_WEEK = "week"
HORIZON_MONTH = "month"
HORIZON_PLANNED = "planned"

HORIZON_LABELS = {
    HORIZON_TODAY: "Сегодня",
    HORIZON_WEEK: "На неделе",
    HORIZON_MONTH: "В этом месяце",
    HORIZON_PLANNED: "Плановые",
}

HORIZON_HINTS = {
    HORIZON_TODAY: "Всё со сроком, чем можно заняться сегодня: срочное сверху.",
    HORIZON_WEEK: "Всё, что нужно закрыть до воскресенья.",
    HORIZON_MONTH: "Задачи со сроком до конца месяца.",
    HORIZON_PLANNED: "Работа ещё не началась — старт впереди.",
}


def week_end(today: date | None = None) -> date:
    """Воскресенье текущей недели."""
    today = today or date.today()
    return today + timedelta(days=6 - today.weekday())


def week_deadline(today: date | None = None) -> date:
    """Пятница текущей недели — разумный срок для задачи «на неделе».

    В субботу и воскресенье пятница уже позади, поэтому берём конец недели.
    """
    today = today or date.today()
    friday = today + timedelta(days=4 - today.weekday())
    return friday if friday >= today else week_end(today)


def month_end(today: date | None = None) -> date:
    """Последний день текущего месяца."""
    today = today or date.today()
    return today.replace(day=calendar.monthrange(today.year, today.month)[1])


def default_due(horizon: str, today: date | None = None) -> date | None:
    """Срок, который подставляется новой задаче в этом списке.

    Логика простая: раз задачу заводят, стоя в списке «На неделе», значит она
    должна быть сделана на этой неделе.
    """
    today = today or date.today()
    if horizon == HORIZON_TODAY:
        return today
    if horizon == HORIZON_WEEK:
        return week_deadline(today)
    if horizon == HORIZON_MONTH:
        return month_end(today)
    return None


def horizon_bound(horizon: str, today: date | None = None) -> date | None:
    """До какой даты смотрит горизонт. None — у «плановых» границы нет."""
    today = today or date.today()
    if horizon == HORIZON_TODAY:
        return today
    if horizon == HORIZON_WEEK:
        return week_end(today)
    if horizon == HORIZON_MONTH:
        return month_end(today)
    return None


def in_horizon(task: Task, horizon: str, today: date | None = None) -> bool:
    """Попадает ли задача в горизонт."""
    today = today or date.today()
    if task.is_done:
        return False

    if horizon == HORIZON_PLANNED:
        return task.is_planned

    bound = horizon_bound(horizon, today)
    if bound is None:
        return False
    # Задача, которая ещё не стартовала, в рабочие горизонты не попадает —
    # кроме случая, когда старт наступает внутри самого горизонта.
    if task.is_planned:
        return task.start_date is not None and task.start_date <= bound
    if task.due_date is None:
        # Без срока задача никуда по времени не относится: её место — в общем
        # списке, иначе горизонты превратятся в свалку.
        return False
    if horizon == HORIZON_TODAY:
        # «Сегодня» — это то, чем можно заниматься сегодня: просроченное,
        # сегодняшнее и всё, у чего срок ещё впереди. Сегодняшний день входит
        # в число дней до любого будущего срока.
        return True
    return task.due_date <= bound


def filter_tasks(tasks: list[Task], horizon: str, today: date | None = None) -> list[Task]:
    return [t for t in tasks if in_horizon(t, horizon, today)]


def horizon_counts(tasks: list[Task], today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    return {
        key: sum(1 for t in tasks if in_horizon(t, key, today)) for key in HORIZON_LABELS
    }


def order_key(task: Task, today: date | None = None) -> tuple:
    """Ключ сортировки списка задач.

    Сначала важность: критичное всегда выше обычного. Внутри одной важности —
    срочность: просроченное, потом сегодняшнее, потом по возрастанию срока, а
    задачи без срока в самом конце. Плановые уезжают ниже всех: работать по ним
    ещё рано.
    """
    today = today or date.today()
    days_left = (task.due_date - today).days if task.due_date else None
    return (
        1 if task.is_planned else 0,      # плановые — в конец
        -task.priority,                   # важность: критичное выше
        0 if days_left is not None else 1,  # без срока — после сроковых
        days_left if days_left is not None else 0,  # ближайший срок выше
        task.title.lower(),
    )


def sort_tasks(tasks: list[Task], today: date | None = None) -> list[Task]:
    return sorted(tasks, key=lambda task: order_key(task, today))


def start_text(task: Task) -> str:
    """Человеческая подпись про старт плановой задачи."""
    days = task.days_to_start
    if days is None or task.start_date is None:
        return ""
    if days <= 0:
        return "в работе"
    if days == 1:
        return "старт завтра"
    if days <= 7:
        return "старт через %d дн." % days
    return "старт %s" % task.start_date.strftime("%d.%m")
