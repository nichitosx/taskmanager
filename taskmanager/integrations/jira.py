"""Работа с Jira.

Сейчас — только ручная привязка: ключ задачи хранится в самой задаче, а по
адресу Jira из настроек собирается ссылка «Открыть в Jira». Архитектура
рассчитана на то, что позже сюда добавится клиент REST API (чтение статуса и
создание issue) — вся остальная программа работает через эти функции и о
способе получения данных ничего не знает.
"""

from __future__ import annotations

import re
import webbrowser
from urllib.parse import urlparse

KEY_RE = re.compile(r"^[A-ZА-Я][A-ZА-Я0-9]{1,14}-\d+$")


def normalize_key(value: str) -> str:
    """Приводит ввод к виду ``PROJ-123``: принимает и ключ, и ссылку целиком."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        tail = urlparse(value).path.rstrip("/").split("/")[-1]
        value = tail or value
    value = value.upper().replace(" ", "")
    return value


def is_valid_key(value: str) -> bool:
    return bool(KEY_RE.match(normalize_key(value)))


def issue_url(base_url: str, key: str) -> str:
    """Собирает ссылку на issue. Пустая строка, если данных не хватает."""
    key = normalize_key(key)
    base = (base_url or "").strip().rstrip("/")
    if not key:
        return ""
    if not base:
        return ""
    if base.endswith("/browse"):
        return base + "/" + key
    return base + "/browse/" + key


def open_issue(base_url: str, key: str) -> bool:
    """Открывает issue в браузере. False, если ссылку собрать не удалось."""
    url = issue_url(base_url, key)
    if not url:
        return False
    webbrowser.open(url)
    return True


def create_issue_url(base_url: str) -> str:
    """Ссылка на форму создания задачи — используется, пока нет API."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + "/secure/CreateIssue!default.jspa"
