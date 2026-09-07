"""Формирование отчётов: за день и за неделю, плюс экспорт в Markdown-файлы."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .models import (
    PRIORITY_LABELS,
    STATUS_DONE,
    DailyReport,
    Task,
    WorkLog,
)
from .storage import Storage

WEEKDAY_NAMES = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]

MONTH_NAMES = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def fmt_date_long(value: date) -> str:
    return "%d %s %d, %s" % (
        value.day,
        MONTH_NAMES[value.month - 1],
        value.year,
        WEEKDAY_NAMES[value.weekday()],
    )


def week_bounds(any_day: Optional[date] = None) -> tuple[date, date]:
    """Понедельник и воскресенье недели, в которую попадает день."""
    any_day = any_day or date.today()
    start = any_day - timedelta(days=any_day.weekday())
    return start, start + timedelta(days=6)


def previous_week_bounds(any_day: Optional[date] = None) -> tuple[date, date]:
    start, _ = week_bounds(any_day)
    prev_start = start - timedelta(days=7)
    return prev_start, prev_start + timedelta(days=6)


# --- Ежедневный отчёт ---------------------------------------------------------


def render_daily(report: DailyReport, storage: Storage) -> str:
    """Markdown-текст отчёта за день."""
    lines: list[str] = []
    lines.append("# Отчёт за %s" % fmt_date_long(report.log_date))
    lines.append("")

    if report.note.strip():
        lines.append(report.note.strip())
        lines.append("")

    by_task: dict[Optional[int], list[WorkLog]] = {}
    for log in report.logs:
        by_task.setdefault(log.task_id, []).append(log)

    task_logs = {k: v for k, v in by_task.items() if k is not None}
    if task_logs:
        lines.append("## Задачи")
        for task_id, logs in task_logs.items():
            task = storage.get_task(task_id)
            title = task.title if task else (logs[0].task_title or "Задача удалена")
            key = task.jira_key if task and task.jira_key else logs[0].task_jira_key
            head = "- **%s**" % title
            if key:
                head += " (`%s`)" % key
            lines.append(head)
            for log in logs:
                if log.comment.strip():
                    lines.append("  - %s" % log.comment.strip())
        lines.append("")

    free_logs = by_task.get(None, [])
    if free_logs:
        lines.append("## Прочее")
        for log in free_logs:
            if log.comment.strip():
                lines.append("- %s" % log.comment.strip())
        lines.append("")

    done_today = [
        t
        for t in storage.list_tasks(include_done=True)
        if t.status == STATUS_DONE and t.done_at and t.done_at.date() == report.log_date
    ]
    if done_today:
        lines.append("## Завершено сегодня")
        for task in done_today:
            suffix = " (`%s`)" % task.jira_key if task.jira_key else ""
            lines.append("- %s%s" % (task.title, suffix))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# --- Недельный отчёт ----------------------------------------------------------


def collect_week(storage: Storage, start: date, end: date) -> dict:
    """Собирает сырые данные за неделю — из них строится и текст, и списки Jira."""
    logs = storage.logs_in_range(start, end)

    per_day: dict[date, list[WorkLog]] = {}
    for log in logs:
        if log.log_date:
            per_day.setdefault(log.log_date, []).append(log)

    notes: dict[date, str] = {}
    day = start
    while day <= end:
        report = storage.get_daily_report(day)
        if report and report.note.strip():
            notes[day] = report.note.strip()
        day += timedelta(days=1)

    touched_ids = {log.task_id for log in logs if log.task_id is not None}
    touched: list[Task] = []
    for task_id in touched_ids:
        task = storage.get_task(task_id)
        if task:
            touched.append(task)

    all_tasks = storage.list_tasks(include_done=True)
    completed = [
        t for t in all_tasks
        if t.status == STATUS_DONE and t.done_at and start <= t.done_at.date() <= end
    ]

    # Задачи, по которым была работа, но вопрос с Jira ещё не закрыт.
    jira_todo = [t for t in touched if t.needs_jira()]
    # Плюс задачи, завершённые или заведённые за эту неделю без issue —
    # их тоже легко потерять из виду.
    created_this_week = [
        t for t in all_tasks
        if t.created_at and start <= t.created_at.date() <= end and t.needs_jira()
    ]
    for task in completed + created_this_week:
        if task.needs_jira() and all(t.id != task.id for t in jira_todo):
            jira_todo.append(task)

    return {
        "start": start,
        "end": end,
        "per_day": per_day,
        "notes": notes,
        "touched": sorted(touched, key=lambda t: (-t.priority, t.title)),
        "completed": completed,
        "jira_todo": sorted(jira_todo, key=lambda t: (-t.priority, t.title)),
        "logs": logs,
    }


GROUPING_BY_DAYS = "days"
GROUPING_BY_TASKS = "tasks"

GROUPING_LABELS = {
    GROUPING_BY_DAYS: "по дням",
    GROUPING_BY_TASKS: "по задачам",
}


def _empty_workdays(data: dict) -> list[date]:
    """Рабочие дни недели, за которые нет ни отметок, ни комментария."""
    days: list[date] = []
    day = data["start"]
    while day <= data["end"]:
        if day.weekday() < 5 and not data["per_day"].get(day) and not data["notes"].get(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def _render_days_body(data: dict) -> list[str]:
    """Хроника недели: что происходило в каждый день."""
    lines = ["## Как прошла неделя"]
    day = data["start"]
    while day <= data["end"]:
        day_logs = data["per_day"].get(day, [])
        note = data["notes"].get(day, "")
        if not day_logs and not note:
            day += timedelta(days=1)
            continue
        lines.append("")
        lines.append("### %s, %s" % (WEEKDAY_NAMES[day.weekday()].capitalize(), fmt_date(day)))
        if note:
            lines.append(note)
        for log in day_logs:
            title = log.task_title or "Без задачи"
            key = " (`%s`)" % log.task_jira_key if log.task_jira_key else ""
            comment = log.comment.strip()
            if log.task_id is None:
                lines.append("- %s" % (comment or "—"))
            else:
                lines.append("- **%s**%s — %s" % (title, key, comment or "работа по задаче"))
        day += timedelta(days=1)
    lines.append("")

    if data["touched"]:
        lines.append("## Задачи, по которым была работа")
        for task in data["touched"]:
            key = " `%s`" % task.jira_key if task.jira_key else ""
            status = " · завершена" if task.status == STATUS_DONE else ""
            days = len({log.log_date for log in data["logs"] if log.task_id == task.id})
            lines.append(
                "- **%s**%s — дней в работе: %d%s" % (task.title, key, days, status)
            )
        lines.append("")
    return lines


def _render_tasks_body(data: dict) -> list[str]:
    """Разрез по задачам: что сделано по каждой за неделю."""
    lines = ["## Работа по задачам"]

    for task in data["touched"]:
        task_logs = [log for log in data["logs"] if log.task_id == task.id]
        key = " (`%s`)" % task.jira_key if task.jira_key else ""
        lines.append("")
        lines.append("### %s%s" % (task.title, key))

        meta = ["дней в работе: %d" % len({log.log_date for log in task_logs})]
        if task.product:
            meta.append("продукт: %s" % task.product)
        meta.append("приоритет: %s" % PRIORITY_LABELS.get(task.priority, "обычный"))
        if task.due_date:
            meta.append("срок %s" % fmt_date(task.due_date))
        if task.status == STATUS_DONE:
            meta.append("завершена")
        lines.append(" · ".join(meta))

        for log in task_logs:
            comment = log.comment.strip() or "работа по задаче"
            # Год уже есть в заголовке отчёта — внутри задачи хватит дня и месяца.
            lines.append(
                "- %s, %s — %s"
                % (WEEKDAY_NAMES[log.log_date.weekday()][:2], log.log_date.strftime("%d.%m"), comment)
            )
    if not data["touched"]:
        lines.append("")
        lines.append("За неделю не отмечено ни одной задачи.")
    lines.append("")

    free_logs = [log for log in data["logs"] if log.task_id is None]
    if free_logs:
        lines.append("## Вне задач")
        for log in free_logs:
            lines.append("- %s — %s" % (fmt_date(log.log_date), log.comment.strip() or "—"))
        lines.append("")

    # Свободные комментарии за дни в этом разрезе иначе потерялись бы.
    if data["notes"]:
        lines.append("## Комментарии по дням")
        for day in sorted(data["notes"]):
            lines.append(
                "- **%s, %s** — %s"
                % (WEEKDAY_NAMES[day.weekday()].capitalize(), fmt_date(day), data["notes"][day])
            )
        lines.append("")
    return lines


def render_weekly(
    storage: Storage,
    start: date,
    end: date,
    stale_days: int = 5,
    grouping: str = GROUPING_BY_DAYS,
) -> str:
    """Markdown-текст отчёта за неделю.

    ``grouping`` выбирает разрез основной части: ``days`` — хроника по дням,
    ``tasks`` — сводка по каждой задаче. Итоговые разделы (Jira, просрочки,
    простои) одинаковы в обоих случаях.
    """
    data = collect_week(storage, start, end)
    lines: list[str] = []
    lines.append("# Отчёт за неделю %s — %s" % (fmt_date(start), fmt_date(end)))
    lines.append("")

    logs = data["logs"]
    lines.append(
        "Записей о работе: %d · задач в работе: %d · завершено: %d"
        % (len(logs), len(data["touched"]), len(data["completed"]))
    )
    lines.append("")

    if grouping == GROUPING_BY_TASKS:
        lines.extend(_render_tasks_body(data))
    else:
        lines.extend(_render_days_body(data))

    if data["completed"]:
        lines.append("## Завершено за неделю")
        for task in data["completed"]:
            key = " `%s`" % task.jira_key if task.jira_key else ""
            lines.append("- %s%s" % (task.title, key))
        lines.append("")

    # --- Главное: что нужно завести в Jira
    lines.append("## Нужно завести в Jira")
    if data["jira_todo"]:
        for task in data["jira_todo"]:
            due = ", срок %s" % fmt_date(task.due_date) if task.due_date else ""
            lines.append(
                "- [ ] **%s** (приоритет: %s%s)"
                % (task.title, PRIORITY_LABELS.get(task.priority, "обычный"), due)
            )
    else:
        lines.append("Всё закрыто: по каждой задаче недели либо есть issue, либо она не нужна.")
    lines.append("")

    # --- Хвосты
    active = [t for t in storage.list_tasks(include_done=False)]
    overdue = [t for t in active if t.is_overdue]
    stale = [t for t in active if t.is_stale(stale_days) and t not in overdue]
    if overdue:
        lines.append("## Просрочено")
        for task in overdue:
            lines.append(
                "- **%s** — срок был %s (%d дн. назад)"
                % (task.title, fmt_date(task.due_date), -task.days_to_due)
            )
        lines.append("")
    if stale:
        lines.append("## Без движения %d+ дней" % stale_days)
        for task in stale:
            lines.append("- %s — %d дн. без изменений" % (task.title, task.days_since_activity))
        lines.append("")

    empty_days = _empty_workdays(data)
    if empty_days:
        lines.append(
            "_Дни без отчёта: %s_" % ", ".join(fmt_date(d) for d in empty_days)
        )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# --- Экспорт ------------------------------------------------------------------


def export_markdown(content: str, target_dir: Path, filename: str) -> Path:
    """Записывает отчёт в файл, создавая каталоги при необходимости."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def daily_filename(day: date) -> str:
    return "Отчёт %s.md" % day.isoformat()


def weekly_filename(start: date, end: date) -> str:
    return "Неделя %s — %s.md" % (start.isoformat(), end.isoformat())
