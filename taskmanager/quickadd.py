"""Разбор строки быстрого ввода.

Пример: ``Починить отчёт по выгрузке !! @завтра #отчёты PROJ-142``
превращается в задачу с высоким приоритетом, сроком на завтра, тегом
«отчёты» и привязанной Jira-задачей PROJ-142.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .models import (
    JIRA_CREATED,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_NOTABLE,
    Task,
)

JIRA_KEY_RE = re.compile(r"\b([A-ZА-Я][A-ZА-Я0-9]{1,14}-\d+)\b")

_PRIORITY_WORDS = {
    "низкий": PRIORITY_LOW,
    "low": PRIORITY_LOW,
    "обычный": PRIORITY_NORMAL,
    "normal": PRIORITY_NORMAL,
    "заметный": PRIORITY_NOTABLE,
    "notable": PRIORITY_NOTABLE,
    "высокий": PRIORITY_HIGH,
    "high": PRIORITY_HIGH,
    "критично": PRIORITY_CRITICAL,
    "крит": PRIORITY_CRITICAL,
    "critical": PRIORITY_CRITICAL,
}

_WEEKDAYS = {
    "пн": 0, "понедельник": 0, "mon": 0,
    "вт": 1, "вторник": 1, "tue": 1,
    "ср": 2, "среда": 2, "wed": 2,
    "чт": 3, "четверг": 3, "thu": 3,
    "пт": 4, "пятница": 4, "fri": 4,
    "сб": 5, "суббота": 5, "sat": 5,
    "вс": 6, "воскресенье": 6, "sun": 6,
}

HELP_TEXT = (
    "Быстрый ввод: !! — высокий приоритет, !!! — критично, ! низкий;\n"
    "@сегодня @завтра @пт @25.12 @+3 — срок; #тег — метка;\n"
    "PROJ-142 — ключ Jira подхватится автоматически."
)


def parse_due(token: str, today: date | None = None) -> date | None:
    """Превращает «завтра», «пт», «25.12», «+3» в дату. None, если не разобрали."""
    today = today or date.today()
    token = token.strip().lower().lstrip("@")
    if not token:
        return None
    if token in ("сегодня", "today"):
        return today
    if token in ("завтра", "tomorrow"):
        return today + timedelta(days=1)
    if token in ("послезавтра",):
        return today + timedelta(days=2)
    if token in ("вчера", "yesterday"):
        return today - timedelta(days=1)
    if token in ("позавчера",):
        return today - timedelta(days=2)
    if token in ("кмес", "конецмесяца", "eom"):
        return today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if token in ("кнед", "конецнедели", "eow"):
        # Пятница текущей недели, а если она уже прошла — пятница следующей.
        delta = (4 - today.weekday()) % 7
        return today + timedelta(days=delta)
    if token in _WEEKDAYS:
        target = _WEEKDAYS[token]
        delta = (target - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    if token.startswith("+") and token[1:].rstrip("dд").isdigit():
        return today + timedelta(days=int(token[1:].rstrip("dд")))
    # Даты вида 25.12 / 25.12.2026 / 25-12 / 2026-12-25
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", token)
    if match:
        year, month, day = (int(g) for g in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?", token)
    if match:
        day, month, year_raw = match.group(1), match.group(2), match.group(3)
        year = today.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            result = date(year, int(month), int(day))
        except ValueError:
            return None
        # Без явного года «25.12» в прошлом означает следующий год.
        if not year_raw and result < today:
            try:
                result = result.replace(year=year + 1)
            except ValueError:
                return None
        return result
    return None


def parse(text: str, today: date | None = None) -> Task:
    """Собирает задачу из строки быстрого ввода."""
    today = today or date.today()
    task = Task(priority=PRIORITY_NORMAL)
    rest: list[str] = []

    for token in text.split():
        low = token.lower()

        if re.fullmatch(r"!{1,4}", token):
            # Восклицательных знаков — на одну ступень меньше, чем полосок:
            # «!» это самая спокойная задача, «!!!!» — то, что горит.
            task.priority = {
                1: PRIORITY_LOW,
                2: PRIORITY_NOTABLE,
                3: PRIORITY_HIGH,
                4: PRIORITY_CRITICAL,
            }[len(token)]
            continue
        if low.startswith("!") and low[1:] in _PRIORITY_WORDS:
            task.priority = _PRIORITY_WORDS[low[1:]]
            continue
        if token.startswith("@") and len(token) > 1:
            due = parse_due(token, today)
            if due:
                task.due_date = due
                continue
        if token.startswith(">") and len(token) > 1:
            start = parse_due(token[1:], today)
            if start:
                task.start_date = start
                continue
        if token.startswith("#") and len(token) > 1:
            tag = token[1:].strip(",.;")
            if tag and tag not in task.tags:
                task.tags.append(tag)
            continue
        match = JIRA_KEY_RE.fullmatch(token.strip(",.;()[]"))
        if match:
            task.jira_key = match.group(1)
            task.jira_state = JIRA_CREATED
            continue
        rest.append(token)

    task.title = " ".join(rest).strip()
    if not task.title:
        # Строка состояла только из модификаторов — оставим исходный текст.
        task.title = text.strip()
    return task


def find_jira_keys(text: str) -> list[str]:
    """Находит все ключи Jira в произвольном тексте."""
    seen: list[str] = []
    for key in JIRA_KEY_RE.findall(text or ""):
        if key not in seen:
            seen.append(key)
    return seen
