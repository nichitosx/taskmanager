r"""Пути хранения и пользовательские настройки.

Данные лежат в %APPDATA%\TaskManager. Если рядом с приложением есть файл
``portable.flag`` — всё хранится в папке приложения (портативный режим:
скопировал каталог на другой компьютер и работаешь дальше).
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_NAME = "TaskManager"

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",
    # Стиль оформления: "soft" — скруглённый, "pixel" — прямоугольный пиксельный.
    "ui_style": "soft",
    "stale_days": 5,
    # Jira: ручная привязка. Ссылка собирается как <base_url>/browse/<KEY>.
    "jira": {
        "enabled": True,
        "base_url": "",
        "auto_detect_keys": True,
    },
    # Напоминание в конце дня.
    "eod": {
        "enabled": True,
        "time": "17:30",
        "weekdays": [0, 1, 2, 3, 4],
    },
    # Недельный отчёт (по умолчанию — пятница, утро).
    "weekly": {
        "enabled": True,
        "weekday": 4,
        "time": "09:30",
        # Разрез основной части отчёта: "days" — по дням, "tasks" — по задачам.
        "grouping": "days",
    },
    # Плановые задачи: за сколько дней до старта предупреждать.
    "planning": {
        "notify_enabled": True,
        "notify_days": 7,
    },
    # Справочник продуктов: [{"name": ..., "keywords": [...], "color": "#..."}].
    "products": [],
    "products_autodetect": True,
    # Экспорт отчётов в хранилище Obsidian.
    "obsidian": {
        "enabled": False,
        "vault_path": "",
        "daily_subdir": "Отчёты/Дни",
        "weekly_subdir": "Отчёты/Недели",
    },
    # Публикация отчётов в Confluence (выключено, пока не заданы доступы).
    "confluence": {
        "enabled": False,
        "base_url": "",
        "email": "",
        "token": "",
        "space_key": "",
        "parent_id": "",
    },
    "autostart": False,
    "minimize_to_tray": True,
    "window_geometry": "",
}


def app_dir() -> Path:
    """Каталог самого приложения (рядом с run.py или с .exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (app_dir() / "portable.flag").exists()


def data_dir() -> Path:
    if is_portable():
        path = app_dir() / "data"
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / ".config")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "tasks.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно накладывает сохранённые значения на значения по умолчанию."""
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Настройки в JSON-файле рядом с базой."""

    def __init__(self) -> None:
        self.path = settings_path()
        self.data = deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Битый файл не должен мешать запуску — просто берём значения по умолчанию.
            return
        if isinstance(raw, dict):
            self.data = _merge(DEFAULT_SETTINGS, raw)

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, path: str, default: Any = None) -> Any:
        """Достаёт значение по пути вида ``"eod.time"``."""
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def get_int(self, path: str, default: int) -> int:
        """Числовая настройка. Ноль — допустимое значение, а не «пусто»."""
        value = self.get(path, None)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
