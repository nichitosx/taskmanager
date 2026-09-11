"""Формирование отчётов: за день и за неделю, плюс экспорт в Markdown-файлы."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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


# --- Где кончается рабочая неделя ---------------------------------------------
# Отчёт сдаётся в пятницу днём, и всё сделанное после уже относится к следующей
# неделе — иначе пятничный вечер и выходные попадают в отчёт, который уже сдан.

DEFAULT_CUTOFF_DAY = 4        # пятница
DEFAULT_CUTOFF_TIME = "12:00"


def parse_cutoff_time(value: str, fallback: time = time(12, 0)) -> time:
    try:
        hours, minutes = str(value).split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return fallback


@dataclass
class WeekRule:
    """Правило, по которому день и час относят работу к той или иной неделе."""

    day: int = DEFAULT_CUTOFF_DAY
    at: time = time(12, 0)
    enabled: bool = True

    @classmethod
    def from_settings(cls, settings) -> "WeekRule":
        if settings is None:
            return cls()
        return cls(
            day=max(0, min(6, settings.get_int("week.cutoff_day", DEFAULT_CUTOFF_DAY))),
            at=parse_cutoff_time(settings.get("week.cutoff_time", DEFAULT_CUTOFF_TIME)),
            enabled=bool(settings.get("week.cutoff_enabled", True)),
        )

    def cutoff(self, week_start: date) -> datetime:
        """Момент, после которого работа идёт уже в следующий отчёт."""
        return datetime.combine(week_start + timedelta(days=self.day), self.at)

    def covers(self, moment: Optional[datetime], week_start: date) -> bool:
        """Относится ли момент к неделе, начинающейся с этой даты."""
        if moment is None:
            return False
        if not self.enabled:
            return week_start <= moment.date() <= week_start + timedelta(days=6)
        return self.cutoff(week_start - timedelta(days=7)) <= moment < self.cutoff(week_start)

    def describe(self) -> str:
        return "%s, %s" % (WEEKDAY_NAMES[self.day], self.at.strftime("%H:%M"))


# --- Ежедневный отчёт ---------------------------------------------------------


def render_daily(report: DailyReport, storage: Storage, with_jira: bool = True) -> str:
    """Markdown-текст отчёта за день. ``with_jira`` добавляет ключи задач."""
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
            if key and with_jira:
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
            suffix = " (`%s`)" % task.jira_key if (task.jira_key and with_jira) else ""
            lines.append("- %s%s" % (task.title, suffix))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# --- Недельный отчёт ----------------------------------------------------------


def collect_week(
    storage: Storage, start: date, end: date, rule: Optional[WeekRule] = None
) -> dict:
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
    rule = rule or WeekRule(enabled=False)
    # Выполненное относим к неделе по правилу: сделанное после пятничного
    # рубежа попадает уже в следующий отчёт.
    completed = [
        t for t in all_tasks
        if t.status == STATUS_DONE and rule.covers(t.done_at, start)
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

    # Прогресс по подпунктам — чтобы в отчёте было видно, насколько задача разобрана.
    subtasks = {task.id: storage.subtask_progress(task.id) for task in touched}

    return {
        "subtasks": subtasks,
        "rule": rule,
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
GROUPING_TABLE = "table"

GROUPING_LABELS = {
    GROUPING_BY_DAYS: "по дням",
    GROUPING_BY_TASKS: "по задачам",
    GROUPING_TABLE: "таблицей",
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


NOTHING_DONE = "ничего не отмечено"


@dataclass
class JiraFacts:
    """Что известно про задачи из самой Jira — названия и итоговые комментарии.

    Нужны отчёту: название задачи берётся таким, каким его видят коллеги в
    Jira, а «что сделано» можно взять из комментария, которым задачу закрыли.
    """

    titles: dict = None
    comments: dict = None
    done: list = None

    def __post_init__(self) -> None:
        self.titles = self.titles or {}
        self.comments = self.comments or {}
        self.done = self.done or []

    @classmethod
    def from_issues(cls, issues) -> "JiraFacts":
        titles, comments = {}, {}
        for issue in issues or []:
            key = (issue.key or "").upper()
            if not key:
                continue
            if issue.summary:
                titles[key] = issue.summary
            if issue.comment:
                comments[key] = issue.comment
        return cls(titles=titles, comments=comments, done=list(issues or []))

    def title(self, task) -> str:
        """Название из Jira, а если его нет — то, что записано у нас."""
        return self.titles.get((task.jira_key or "").upper(), "") or task.title

    def comment(self, task) -> str:
        return self.comments.get((task.jira_key or "").upper(), "")


def task_week_summary(data: dict, task, facts: Optional[JiraFacts] = None) -> str:
    """Одной строкой: что сделано по задаче за неделю."""
    comments = []
    for log in data["logs"]:
        if log.task_id != task.id:
            continue
        comment = log.comment.strip()
        if comment and comment not in comments:
            comments.append(comment)
    if comments:
        return "; ".join(comments)
    from_jira = facts.comment(task) if facts else ""
    return from_jira or NOTHING_DONE


def _cell(text: str) -> str:
    """Вертикальная черта внутри клетки развалила бы таблицу."""
    return " ".join(str(text or "").split()).replace("|", "/")


def _key_cell(key: str, jira_base: str, with_jira: bool) -> str:
    """Номер задачи ссылкой. Нет номера или Jira выключена — клетка пустая."""
    key = (key or "").strip()
    if not key or not with_jira:
        return ""
    base = (jira_base or "").strip().rstrip("/")
    if base:
        return "[%s](%s/browse/%s)" % (key, base, key)
    return key


def render_week_table(
    data: dict,
    jira_base: str = "",
    with_jira: bool = True,
    facts: Optional[JiraFacts] = None,
) -> list[str]:
    """Таблица «номер — задача — что сделано» для вставки в Confluence."""
    lines = [
        "| Номер | Задача | Что сделано за неделю |",
        "|---|---|---|",
    ]
    rows = list(data["touched"])
    seen = {(t.jira_key or "").upper() for t in rows if t.jira_key}

    for task in rows:
        lines.append(
            "| %s | %s | %s |"
            % (
                _cell(_key_cell(task.jira_key, jira_base, with_jira)),
                _cell(facts.title(task) if facts else task.title),
                _cell(task_week_summary(data, task, facts)),
            )
        )

    # То, что закрыто в Jira, но здесь не отмечалось: иначе работа пропадёт.
    for issue in (facts.done if facts else []):
        if (issue.key or "").upper() in seen:
            continue
        lines.append(
            "| %s | %s | %s |"
            % (
                _cell(_key_cell(issue.key, jira_base, with_jira)),
                _cell(issue.summary or issue.key),
                _cell(issue.comment or "закрыта в Jira"),
            )
        )

    if len(lines) == 2:
        lines.append("|  | — | за неделю отметок не было |")
    lines.append("")
    return lines


def _render_days_body(data: dict, with_jira: bool = True) -> list[str]:
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
            key = " (`%s`)" % log.task_jira_key if (log.task_jira_key and with_jira) else ""
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
            key = " `%s`" % task.jira_key if (task.jira_key and with_jira) else ""
            status = " · завершена" if task.status == STATUS_DONE else ""
            days = len({log.log_date for log in data["logs"] if log.task_id == task.id})
            lines.append(
                "- **%s**%s — дней в работе: %d%s" % (task.title, key, days, status)
            )
        lines.append("")
    return lines


def _render_tasks_body(data: dict, with_jira: bool = True) -> list[str]:
    """Разрез по задачам: что сделано по каждой за неделю."""
    lines = ["## Работа по задачам"]

    for task in data["touched"]:
        task_logs = [log for log in data["logs"] if log.task_id == task.id]
        key = " (`%s`)" % task.jira_key if (task.jira_key and with_jira) else ""
        lines.append("")
        lines.append("### %s%s" % (task.title, key))

        meta = ["дней в работе: %d" % len({log.log_date for log in task_logs})]
        done, total = data.get("subtasks", {}).get(task.id, (0, 0))
        if total:
            meta.append("подпункты: %d из %d" % (done, total))
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
    with_jira: bool = True,
    jira_base: str = "",
    rule: Optional[WeekRule] = None,
    facts: Optional[JiraFacts] = None,
) -> str:
    """Markdown-текст отчёта за неделю.

    ``grouping`` выбирает разрез основной части: ``days`` — хроника по дням,
    ``tasks`` — сводка по каждой задаче. Итоговые разделы (Jira, просрочки,
    простои) одинаковы в обоих случаях.
    """
    data = collect_week(storage, start, end, rule)
    lines: list[str] = []
    lines.append("# Отчёт за неделю %s — %s" % (fmt_date(start), fmt_date(end)))
    lines.append("")

    logs = data["logs"]
    lines.append(
        "Записей о работе: %d · задач в работе: %d · завершено: %d"
        % (len(logs), len(data["touched"]), len(data["completed"]))
    )
    lines.append("")

    if grouping == GROUPING_TABLE:
        # Таблицу отдаём одну, без хвостов: её вставляют на страницу как есть.
        lines.extend(render_week_table(data, jira_base, with_jira, facts))
        return "\n".join(lines).strip() + "\n"
    if grouping == GROUPING_BY_TASKS:
        lines.extend(_render_tasks_body(data, with_jira))
    else:
        lines.extend(_render_days_body(data, with_jira))

    if data["completed"]:
        lines.append("## Завершено за неделю")
        for task in data["completed"]:
            key = " `%s`" % task.jira_key if (task.jira_key and with_jira) else ""
            lines.append("- %s%s" % (task.title, key))
        lines.append("")

    # --- Главное: что нужно завести в Jira
    if with_jira:
        lines.append("## Нужно завести в Jira")
        if data["jira_todo"]:
            for task in data["jira_todo"]:
                due = ", срок %s" % fmt_date(task.due_date) if task.due_date else ""
                lines.append(
                    "- [ ] **%s** (приоритет: %s%s)"
                    % (task.title, PRIORITY_LABELS.get(task.priority, "обычный"), due)
                )
        else:
            lines.append(
                "Всё закрыто: по каждой задаче недели либо есть issue, либо она не нужна."
            )
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


# --- Выгрузка за все заполненные недели ---------------------------------------


def _shift_headings(lines: list[str]) -> list[str]:
    """Опускает заголовки на уровень ниже — блок вкладывается внутрь недели."""
    return ["#" + line if line.startswith("#") else line for line in lines]


def _period_task_summary(storage: Storage, weeks: list[date]) -> list[str]:
    """Сводка по задачам за весь период: сколько дней и недель заняла каждая."""
    days: dict[int, set[date]] = {}
    week_count: dict[int, set[date]] = {}
    free_days: set[date] = set()

    for week_start in weeks:
        for log in storage.logs_in_range(week_start, week_start + timedelta(days=6)):
            if log.task_id is None:
                free_days.add(log.log_date)
                continue
            days.setdefault(log.task_id, set()).add(log.log_date)
            week_count.setdefault(log.task_id, set()).add(week_start)

    rows = []
    for task_id, dates in days.items():
        task = storage.get_task(task_id)
        if task is None:
            continue
        rows.append((len(dates), len(week_count.get(task_id, set())), task))
    rows.sort(key=lambda item: (-item[0], item[2].title))

    lines = ["## Итого по задачам"]
    if not rows:
        lines.append("За период нет ни одной отметки о работе.")
        lines.append("")
        return lines

    for day_count, weeks_count, task in rows:
        key = " (`%s`)" % task.jira_key if task.jira_key else ""
        parts = ["дней: %d" % day_count, "недель: %d" % weeks_count]
        if task.product:
            parts.append(task.product)
        if task.status == STATUS_DONE:
            parts.append("завершена")
        lines.append("- **%s**%s — %s" % (task.title, key, " · ".join(parts)))
    if free_days:
        lines.append("- _Работа вне задач_ — дней: %d" % len(free_days))
    lines.append("")
    return lines


def render_all_weeks(
    storage: Storage,
    grouping: str = GROUPING_BY_TASKS,
    stale_days: int = 5,
    with_jira: bool = True,
    jira_base: str = "",
    rule: Optional[WeekRule] = None,
    facts: Optional[JiraFacts] = None,
) -> str:
    """Одна выгрузка по всем неделям, за которые что-то заполнено.

    Недели без отметок и комментариев пропускаются: в такой выгрузке они были бы
    просто пустыми заголовками.
    """
    weeks = sorted(storage.weeks_with_activity())
    if not weeks:
        return "# Выгрузка по неделям\n\nПока нет ни одной заполненной недели.\n"

    first, last = weeks[0], weeks[-1] + timedelta(days=6)
    lines = ["# Задачи по неделям: %s — %s" % (fmt_date(first), fmt_date(last)), ""]
    lines.append("Заполненных недель: %d" % len(weeks))
    lines.append("")
    lines.extend(_period_task_summary(storage, weeks))

    lines.append("## По неделям")
    lines.append("")
    for week_start in weeks:
        week_end = week_start + timedelta(days=6)
        data = collect_week(storage, week_start, week_end, rule)
        lines.append("### Неделя %s — %s" % (fmt_date(week_start), fmt_date(week_end)))
        if grouping == GROUPING_TABLE:
            lines.extend(render_week_table(data, jira_base, with_jira, facts))
            continue
        body = (
            _render_tasks_body(data, with_jira)
            if grouping == GROUPING_BY_TASKS
            else _render_days_body(data, with_jira)
        )
        lines.extend(_shift_headings(_shift_headings(body)))

    return "\n".join(lines).strip() + "\n"


# --- Человекочитаемый вид -----------------------------------------------------


def _strip_inline(text: str) -> str:
    """Убирает из строки жирный шрифт, код и ссылки, оставляя сам текст."""
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)


def to_plain(markdown: str) -> str:
    """Убирает разметку: то же самое, но без решёток, звёздочек и ссылок.

    На экране отчёт удобнее читать без служебных символов, а копируется он
    по-прежнему с разметкой — её ждут и Obsidian, и Confluence.
    """
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()

        if re.fullmatch(r"\s*\|[\s|:-]+\|\s*", line):
            continue  # разделительная строка таблицы
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            line = "  —  ".join(cell for cell in cells if cell)

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            title = _strip_inline(heading.group(2))
            lines.append(title.upper() if len(heading.group(1)) <= 2 else title)
            continue

        line = re.sub(r"^(\s*)[-*]\s+\[[ xX]\]\s+", r"\1• ", line)
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        lines.append(_strip_inline(line))

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


def all_weeks_filename(start: date, end: date) -> str:
    return "Задачи по неделям %s — %s.md" % (start.isoformat(), end.isoformat())
