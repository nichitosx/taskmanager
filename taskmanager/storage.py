"""SQLite-хранилище. Один файл базы, схема создаётся при первом запуске."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .config import db_path
from .models import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_DONE,
    DailyReport,
    Subtask,
    Task,
    WorkLog,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    notes            TEXT DEFAULT '',
    status           TEXT DEFAULT 'active',
    priority         INTEGER DEFAULT 1,
    due_date         TEXT,
    start_date       TEXT,
    product          TEXT DEFAULT '',
    repeat_rule      TEXT DEFAULT '',
    jira_key         TEXT DEFAULT '',
    jira_state       TEXT DEFAULT 'unknown',
    tags             TEXT DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    done_at          TEXT,
    last_activity_at TEXT
);

CREATE TABLE IF NOT EXISTS subtasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    done       INTEGER DEFAULT 0,
    position   INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at    TEXT
);

CREATE TABLE IF NOT EXISTS work_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    log_date   TEXT NOT NULL,
    comment    TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_reports (
    log_date   TEXT PRIMARY KEY,
    note       TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    week_start TEXT PRIMARY KEY,
    content    TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

"""

# Индексы создаются отдельно и после миграции: на базе прошлой версии таблица
# уже существует, а колонок из нового индекса в ней ещё нет.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_start ON tasks(start_date);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);
CREATE INDEX IF NOT EXISTS idx_logs_date ON work_logs(log_date);
CREATE INDEX IF NOT EXISTS idx_logs_task ON work_logs(task_id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else db_path()
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)
        self.conn.commit()

    def _migrate(self) -> None:
        """Дописывает колонки, появившиеся в новых версиях, в старую базу."""
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(tasks)")}
        for name, ddl in (
            ("start_date", "ALTER TABLE tasks ADD COLUMN start_date TEXT"),
            ("product", "ALTER TABLE tasks ADD COLUMN product TEXT DEFAULT ''"),
            ("repeat_rule", "ALTER TABLE tasks ADD COLUMN repeat_rule TEXT DEFAULT ''"),
        ):
            if name not in columns:
                self.conn.execute(ddl)

    def close(self) -> None:
        self.conn.close()

    # --- Задачи ---------------------------------------------------------------

    def add_task(self, task: Task) -> Task:
        now = _now()
        cur = self.conn.execute(
            """INSERT INTO tasks (title, notes, status, priority, due_date, start_date,
                                  product, repeat_rule, jira_key, jira_state, tags,
                                  created_at, updated_at, last_activity_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.title.strip(),
                task.notes,
                task.status,
                task.priority,
                task.due_date.isoformat() if task.due_date else None,
                task.start_date.isoformat() if task.start_date else None,
                task.product,
                task.repeat,
                task.jira_key,
                task.jira_state,
                ",".join(task.tags),
                now,
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get_task(cur.lastrowid)

    def update_task(self, task: Task, touch_activity: bool = True) -> None:
        now = _now()
        if touch_activity or not task.last_activity_at:
            activity = now
        else:
            activity = task.last_activity_at.isoformat(timespec="seconds")
        self.conn.execute(
            """UPDATE tasks SET title=?, notes=?, status=?, priority=?, due_date=?,
                                start_date=?, product=?, repeat_rule=?, jira_key=?,
                                jira_state=?, tags=?, updated_at=?, done_at=?,
                                last_activity_at=?
               WHERE id=?""",
            (
                task.title.strip(),
                task.notes,
                task.status,
                task.priority,
                task.due_date.isoformat() if task.due_date else None,
                task.start_date.isoformat() if task.start_date else None,
                task.product,
                task.repeat,
                task.jira_key,
                task.jira_state,
                ",".join(task.tags),
                now,
                task.done_at.isoformat(timespec="seconds") if task.done_at else None,
                activity,
                task.id,
            ),
        )
        self.conn.commit()

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def delete_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def set_status(self, task_id: int, status: str) -> None:
        done_at = _now() if status == STATUS_DONE else None
        self.conn.execute(
            "UPDATE tasks SET status=?, done_at=?, updated_at=?, last_activity_at=? WHERE id=?",
            (status, done_at, _now(), _now(), task_id),
        )
        self.conn.commit()

    def list_tasks(self, include_done: bool = False, include_archived: bool = False) -> list[Task]:
        statuses = [STATUS_ACTIVE]
        if include_done:
            statuses.append(STATUS_DONE)
        if include_archived:
            statuses.append(STATUS_ARCHIVED)
        placeholders = ",".join("?" for _ in statuses)
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status IN (" + placeholders + ") "
            "ORDER BY (start_date IS NOT NULL AND start_date > date('now', 'localtime')), "
            "(due_date IS NULL), due_date ASC, priority DESC, id DESC",
            statuses,
        ).fetchall()
        return [Task.from_row(r) for r in rows]

    def search_tasks(self, query: str) -> list[Task]:
        like = "%" + query.strip() + "%"
        rows = self.conn.execute(
            """SELECT * FROM tasks
               WHERE title LIKE ? OR notes LIKE ? OR jira_key LIKE ? OR tags LIKE ?
                     OR product LIKE ?
               ORDER BY (status='done'), (due_date IS NULL), due_date ASC, priority DESC""",
            (like, like, like, like, like),
        ).fetchall()
        return [Task.from_row(r) for r in rows]

    def find_by_jira_key(self, key: str) -> Optional[Task]:
        """Локальная задача с таким ключом Jira, если она уже заведена."""
        if not key:
            return None
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE upper(jira_key) = upper(?) ORDER BY id DESC LIMIT 1",
            (key.strip(),),
        ).fetchone()
        return Task.from_row(row) if row else None

    def touch_task(self, task_id: int) -> None:
        """Отметить, что по задаче было движение (сбрасывает счётчик простоя)."""
        self.conn.execute(
            "UPDATE tasks SET last_activity_at=?, updated_at=? WHERE id=?",
            (_now(), _now(), task_id),
        )
        self.conn.commit()

    # --- Подпункты ------------------------------------------------------------

    def list_subtasks(self, task_id: int) -> list[Subtask]:
        rows = self.conn.execute(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY position, id", (task_id,)
        ).fetchall()
        return [Subtask.from_row(row) for row in rows]

    def add_subtask(self, task_id: int, title: str) -> Optional[Subtask]:
        """Добавляет подпункт в конец списка. Пустое название игнорируется."""
        title = (title or "").strip()
        if not title:
            return None
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM subtasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        cur = self.conn.execute(
            "INSERT INTO subtasks (task_id, title, done, position, created_at) "
            "VALUES (?,?,0,?,?)",
            (task_id, title, row["next"], _now()),
        )
        self.conn.commit()
        return self.get_subtask(cur.lastrowid)

    def get_subtask(self, subtask_id: int) -> Optional[Subtask]:
        row = self.conn.execute(
            "SELECT * FROM subtasks WHERE id=?", (subtask_id,)
        ).fetchone()
        return Subtask.from_row(row) if row else None

    def rename_subtask(self, subtask_id: int, title: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        self.conn.execute("UPDATE subtasks SET title=? WHERE id=?", (title, subtask_id))
        self.conn.commit()

    def set_subtask_done(self, subtask_id: int, done: bool) -> None:
        """Отметка подпункта — это движение по задаче, обновляем и её активность."""
        self.conn.execute(
            "UPDATE subtasks SET done=?, done_at=? WHERE id=?",
            (1 if done else 0, _now() if done else None, subtask_id),
        )
        row = self.conn.execute(
            "SELECT task_id FROM subtasks WHERE id=?", (subtask_id,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE tasks SET last_activity_at=?, updated_at=? WHERE id=?",
                (_now(), _now(), row["task_id"]),
            )
        self.conn.commit()

    def delete_subtask(self, subtask_id: int) -> None:
        self.conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))
        self.conn.commit()

    def move_subtask(self, subtask_id: int, direction: int) -> None:
        """Меняет подпункт местами с соседним: -1 — выше, 1 — ниже."""
        current = self.get_subtask(subtask_id)
        if current is None:
            return
        items = self.list_subtasks(current.task_id)
        index = next((i for i, s in enumerate(items) if s.id == subtask_id), None)
        if index is None:
            return
        target = index + direction
        if not 0 <= target < len(items):
            return
        # Позиции могли совпадать у старых записей — переписываем весь список.
        items[index], items[target] = items[target], items[index]
        for position, item in enumerate(items):
            self.conn.execute(
                "UPDATE subtasks SET position=? WHERE id=?", (position, item.id)
            )
        self.conn.commit()

    def subtask_progress(self, task_id: int) -> tuple[int, int]:
        """Сколько подпунктов сделано из скольких."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done "
            "FROM subtasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return int(row["done"]), int(row["total"])

    def subtask_progress_map(self) -> dict[int, tuple[int, int]]:
        """Прогресс сразу по всем задачам — для списка, одним запросом."""
        rows = self.conn.execute(
            "SELECT task_id, COUNT(*) AS total, COALESCE(SUM(done), 0) AS done "
            "FROM subtasks GROUP BY task_id"
        ).fetchall()
        return {row["task_id"]: (int(row["done"]), int(row["total"])) for row in rows}

    # --- Отметки о работе -----------------------------------------------------

    def add_work_log(
        self, task_id: Optional[int], comment: str, log_date: Optional[date] = None
    ) -> int:
        log_date = log_date or date.today()
        cur = self.conn.execute(
            "INSERT INTO work_logs (task_id, log_date, comment, created_at) VALUES (?,?,?,?)",
            (task_id, log_date.isoformat(), comment.strip(), _now()),
        )
        if task_id is not None:
            self.conn.execute(
                "UPDATE tasks SET last_activity_at=? WHERE id=?", (_now(), task_id)
            )
        self.conn.commit()
        return cur.lastrowid

    def delete_work_log(self, log_id: int) -> None:
        self.conn.execute("DELETE FROM work_logs WHERE id=?", (log_id,))
        self.conn.commit()

    _LOG_SELECT = """SELECT w.*, t.title AS task_title, t.jira_key AS task_jira_key,
                            t.jira_state AS task_jira_state
                     FROM work_logs w LEFT JOIN tasks t ON t.id = w.task_id """

    def logs_for_date(self, log_date: date) -> list[WorkLog]:
        rows = self.conn.execute(
            self._LOG_SELECT + "WHERE w.log_date = ? ORDER BY w.id",
            (log_date.isoformat(),),
        ).fetchall()
        return [WorkLog.from_row(r) for r in rows]

    def logs_in_range(self, start: date, end: date) -> list[WorkLog]:
        rows = self.conn.execute(
            self._LOG_SELECT + "WHERE w.log_date BETWEEN ? AND ? ORDER BY w.log_date, w.id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [WorkLog.from_row(r) for r in rows]

    def logs_for_task(self, task_id: int, limit: int = 50) -> list[WorkLog]:
        rows = self.conn.execute(
            self._LOG_SELECT + "WHERE w.task_id = ? ORDER BY w.log_date DESC, w.id DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [WorkLog.from_row(r) for r in rows]

    # --- Ежедневный отчёт -----------------------------------------------------

    def save_daily_report(self, log_date: date, note: str) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO daily_reports (log_date, note, created_at, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(log_date) DO UPDATE SET note=excluded.note,
                                                   updated_at=excluded.updated_at""",
            (log_date.isoformat(), note, now, now),
        )
        self.conn.commit()

    def get_daily_report(self, log_date: date) -> Optional[DailyReport]:
        row = self.conn.execute(
            "SELECT * FROM daily_reports WHERE log_date=?", (log_date.isoformat(),)
        ).fetchone()
        logs = self.logs_for_date(log_date)
        if row is None and not logs:
            return None
        report = DailyReport(log_date=log_date, note=row["note"] if row else "")
        report.logs = logs
        return report

    def has_saved_report(self, log_date: date) -> bool:
        """Отчёт за день был сохранён явно (кнопкой «Сохранить отчёт»).

        Отдельные отметки о работе в течение дня отчётом не считаются — иначе
        вечернее напоминание пропадало бы после первой же записи.
        """
        row = self.conn.execute(
            "SELECT 1 FROM daily_reports WHERE log_date=?", (log_date.isoformat(),)
        ).fetchone()
        return bool(row)

    def has_daily_report(self, log_date: date) -> bool:
        """Есть ли за день хоть что-нибудь: сохранённый отчёт или отметки."""
        if self.has_saved_report(log_date):
            return True
        return bool(self.logs_for_date(log_date))

    # Дни, за которые есть хоть что-то: отметка о работе или непустой комментарий.
    # Пустая запись отчёта (открыли и закрыли) днём с данными не считается.
    _FILLED_DAYS = """SELECT log_date FROM daily_reports WHERE trim(note) != ''
                      UNION SELECT log_date FROM work_logs"""

    def report_dates(self, limit: int = 90) -> list[date]:
        rows = self.conn.execute(
            "SELECT log_date FROM (" + self._FILLED_DAYS + ") ORDER BY log_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [date.fromisoformat(r["log_date"]) for r in rows]

    def weeks_with_activity(self, limit: int = 260) -> list[date]:
        """Понедельники недель, за которые что-то заполнено, от свежих к старым.

        Недели без единой отметки и без комментариев не возвращаются — их незачем
        показывать в истории и выгружать.
        """
        rows = self.conn.execute(
            "SELECT DISTINCT date(log_date, 'weekday 0', '-6 days') AS week_start "
            "FROM (" + self._FILLED_DAYS + ") "
            "WHERE log_date IS NOT NULL ORDER BY week_start DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [date.fromisoformat(r["week_start"]) for r in rows if r["week_start"]]

    # --- Недельный отчёт ------------------------------------------------------

    def save_weekly_report(self, week_start: date, content: str) -> None:
        self.conn.execute(
            """INSERT INTO weekly_reports (week_start, content, created_at) VALUES (?,?,?)
               ON CONFLICT(week_start) DO UPDATE SET content=excluded.content""",
            (week_start.isoformat(), content, _now()),
        )
        self.conn.commit()

    def get_weekly_report(self, week_start: date) -> Optional[str]:
        row = self.conn.execute(
            "SELECT content FROM weekly_reports WHERE week_start=?", (week_start.isoformat(),)
        ).fetchone()
        return row["content"] if row else None

    def weekly_report_weeks(self, limit: int = 30) -> list[date]:
        rows = self.conn.execute(
            "SELECT week_start FROM weekly_reports ORDER BY week_start DESC LIMIT ?", (limit,)
        ).fetchall()
        return [date.fromisoformat(r["week_start"]) for r in rows]

    # --- Служебные значения ---------------------------------------------------

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # --- Сводка для главного экрана -------------------------------------------

    def counters(self, stale_days: int) -> dict[str, int]:
        from .horizons import horizon_counts

        tasks = self.list_tasks(include_done=False)
        counts = {
            "active": len(tasks),
            "overdue": sum(1 for t in tasks if t.is_overdue),
            "stale": sum(1 for t in tasks if t.is_stale(stale_days)),
            "jira": sum(1 for t in tasks if t.needs_jira()),
        }
        counts.update(horizon_counts(tasks))
        return counts

    def upcoming_starts(self, within_days: int) -> list[Task]:
        """Плановые задачи, старт которых наступит в ближайшие ``within_days`` дней."""
        tasks = [t for t in self.list_tasks(include_done=False) if t.starts_within(within_days)]
        tasks.sort(key=lambda t: (t.start_date, -t.priority))
        return tasks

    def products_in_use(self) -> list[str]:
        """Продукты, которые реально проставлены хотя бы у одной задачи."""
        rows = self.conn.execute(
            "SELECT DISTINCT product FROM tasks WHERE product != '' ORDER BY product"
        ).fetchall()
        return [r["product"] for r in rows]
