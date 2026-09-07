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


# --- Чтение задач из Jira по REST API ------------------------------------------

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Порядок попыток: новый эндпоинт Jira Cloud, прежний, затем Server/Data Center.
SEARCH_PATHS = ("/rest/api/3/search/jql", "/rest/api/3/search", "/rest/api/2/search")

DEFAULT_JQL = 'assignee = currentUser() AND statusCategory = "To Do" ORDER BY duedate ASC'

FIELDS = "summary,status,duedate,priority,assignee"


class JiraError(Exception):
    """Не удалось получить данные из Jira — текст пригоден для показа пользователю."""


@dataclass
class JiraIssue:
    key: str = ""
    summary: str = ""
    status: str = ""
    status_category: str = ""
    priority: str = ""
    assignee: str = ""
    due_date: date | None = None
    url: str = ""


@dataclass
class JiraConfig:
    base_url: str = ""
    email: str = ""
    token: str = ""
    jql: str = DEFAULT_JQL
    enabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.email.strip() and self.token.strip())

    @classmethod
    def from_settings(cls, raw: dict[str, Any]) -> "JiraConfig":
        raw = raw or {}
        return cls(
            base_url=str(raw.get("base_url", "")).strip(),
            email=str(raw.get("email", "")).strip(),
            token=str(raw.get("token", "")).strip(),
            jql=str(raw.get("jql", "") or DEFAULT_JQL).strip(),
            enabled=bool(raw.get("enabled", True)),
        )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class JiraClient:
    """Минимальный клиент: только чтение списка задач по JQL."""

    def __init__(self, config: JiraConfig, timeout: int = 15) -> None:
        self.config = config
        self.timeout = timeout

    def _auth_header(self) -> str:
        pair = "%s:%s" % (self.config.email, self.config.token)
        return "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")

    def _get(self, path: str, params: dict[str, str]) -> dict:
        base = self.config.base_url.strip().rstrip("/")
        url = base + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url)
        request.add_header("Authorization", self._auth_header())
        request.add_header("Accept", "application/json")
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))

    def search(self, jql: str = "", limit: int = 50) -> list[JiraIssue]:
        """Возвращает задачи по JQL. Бросает JiraError с понятным текстом."""
        if not self.config.is_configured:
            raise JiraError("Заполните адрес, e-mail и API-токен Jira в настройках.")
        query = (jql or self.config.jql or DEFAULT_JQL).strip()
        params = {"jql": query, "maxResults": str(limit), "fields": FIELDS}

        last_error: Exception | None = None
        for path in SEARCH_PATHS:
            try:
                payload = self._get(path, params)
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):  # эндпоинта нет — пробуем следующий
                    last_error = exc
                    continue
                raise JiraError(self._http_message(exc)) from exc
            except urllib.error.URLError as exc:
                raise JiraError("Не удалось соединиться с Jira: %s" % exc.reason) from exc
            except (ValueError, ssl.SSLError) as exc:
                raise JiraError("Неожиданный ответ Jira: %s" % exc) from exc
            return [self._issue(item) for item in payload.get("issues", [])]

        raise JiraError(
            "Jira не отвечает ни на один из известных адресов поиска (%s)." % (last_error or "")
        )

    @staticmethod
    def _http_message(exc: urllib.error.HTTPError) -> str:
        if exc.code in (401, 403):
            return "Jira отклонила доступ (%d): проверьте e-mail и API-токен." % exc.code
        if exc.code == 400:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8"))
                messages = body.get("errorMessages") or []
                detail = "; ".join(str(m) for m in messages)
            except Exception:
                detail = ""
            return "Jira не приняла запрос: %s" % (detail or "проверьте JQL-фильтр.")
        return "Jira ответила ошибкой %d." % exc.code

    def _issue(self, raw: dict) -> JiraIssue:
        fields = raw.get("fields") or {}
        status = fields.get("status") or {}
        category = (status.get("statusCategory") or {}).get("name", "")
        priority = (fields.get("priority") or {}).get("name", "")
        assignee = (fields.get("assignee") or {}).get("displayName", "")
        key = raw.get("key", "")
        return JiraIssue(
            key=key,
            summary=fields.get("summary", "") or "",
            status=status.get("name", "") or "",
            status_category=category,
            priority=priority,
            assignee=assignee,
            due_date=_parse_date(fields.get("duedate")),
            url=issue_url(self.config.base_url, key),
        )
