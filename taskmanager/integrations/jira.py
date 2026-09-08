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

from . import net
from datetime import date
from typing import Any

# Облачная Jira ищет через /rest/api/3/search/jql, Jira Server и Data Center —
# через /rest/api/2/search. Начинаем с подходящего адреса, но проверяем все:
# облачный адрес в своей установке приводит на страницу входа, а не к 404.
CLOUD_SEARCH_PATHS = ("/rest/api/3/search/jql", "/rest/api/3/search", "/rest/api/2/search")
SERVER_SEARCH_PATHS = ("/rest/api/2/search", "/rest/api/3/search/jql", "/rest/api/3/search")
SEARCH_PATHS = CLOUD_SEARCH_PATHS

# Кто я — самый простой способ проверить, что вход вообще принят. Вторая
# версия отвечает и в облаке, и в своей установке, поэтому спрашиваем ей.
WHOAMI_PATHS = ("/rest/api/2/myself", "/rest/api/3/myself")

# Способы входа. В облачной Jira (*.atlassian.net) — почта и API-токен, в
# корпоративной Jira Server/Data Center — личный токен (PAT) в заголовке Bearer.
AUTH_AUTO = "auto"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"

AUTH_LABELS = {
    AUTH_AUTO: "Подобрать автоматически",
    AUTH_BASIC: "Облачная Jira: e-mail и API-токен",
    AUTH_BEARER: "Своя Jira (Server/DC): личный токен",
}

# «Плановые» — то, что ещё не начато; «актуальные» — то, что уже в работе.
DEFAULT_JQL = 'assignee = currentUser() AND statusCategory = "To Do" ORDER BY duedate ASC'
DEFAULT_JQL_ACTIVE = (
    'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC'
)

FIELDS = "summary,status,duedate,priority,assignee"


class JiraError(Exception):
    """Не удалось получить данные из Jira — текст пригоден для показа пользователю."""


def describe_non_json(url: str, final_url: str, content_type: str, body: str) -> str:
    """Объясняет, почему вместо данных пришла страница."""
    preview = " ".join(body.split())[:160]
    looks_html = "html" in (content_type or "").lower() or preview.lower().startswith(
        ("<!doctype", "<html", "<?xml")
    )
    login_page = any(
        marker in (final_url + " " + preview).lower()
        for marker in ("login", "signin", "sso", "auth/realms", "adfs")
    )

    lines = ["Jira ответила не данными, а страницей — запрос не дошёл до API."]
    lines.append("Запрашивали: %s" % url)
    if final_url and final_url != url:
        lines.append("Перенаправило на: %s" % final_url)
    if content_type:
        lines.append("Тип ответа: %s" % content_type)
    if preview:
        lines.append("Начало ответа: %s" % preview[:120])

    lines.append("")
    if login_page:
        lines.append(
            "Похоже на страницу входа: вход идёт через SSO, а REST такой сессии не "
            "видит. Нужен личный токен (Profile → Personal Access Tokens) и способ "
            "входа «Своя Jira (Server/DC)»."
        )
    elif looks_html:
        lines.append(
            "Похоже на обычную веб-страницу. Проверьте адрес: он должен вести в "
            "корень Jira (например https://jira.company.ru или "
            "https://company.ru/jira), без /browse и /secure. Ещё вариант — ответ "
            "подменил прокси или средство защиты трафика."
        )
    else:
        lines.append(
            "Ответ не похож на JSON. Проверьте адрес Jira и не перехватывает ли "
            "запросы прокси."
        )
    return "\n".join(lines)


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
    jql_active: str = DEFAULT_JQL_ACTIVE
    enabled: bool = True
    ca_file: str = ""
    proxy: str = ""
    auth: str = AUTH_AUTO

    @property
    def is_configured(self) -> bool:
        """Личному токену почта не нужна, паре «почта + токен» — нужна."""
        if not (self.base_url.strip() and self.token.strip()):
            return False
        if self.auth == AUTH_BEARER:
            return True
        return bool(self.email.strip()) or self.auth == AUTH_AUTO

    def schemes(self) -> list[str]:
        """Порядок, в котором пробуем входить."""
        if self.auth in (AUTH_BASIC, AUTH_BEARER):
            return [self.auth]
        # Без почты пара «логин:токен» не соберётся — начинаем с личного токена.
        return [AUTH_BASIC, AUTH_BEARER] if self.email.strip() else [AUTH_BEARER, AUTH_BASIC]

    @classmethod
    def from_settings(
        cls, raw: dict[str, Any], ca_file: str = "", proxy: str = ""
    ) -> "JiraConfig":
        raw = dict(raw or {})
        if ca_file and not raw.get("ca_file"):
            raw["ca_file"] = ca_file
        if proxy and not raw.get("proxy"):
            raw["proxy"] = proxy
        return cls(
            base_url=normalize_base_url(str(raw.get("base_url", ""))),
            email=str(raw.get("email", "")).strip(),
            token=str(raw.get("token", "")).strip(),
            jql=str(raw.get("jql", "") or DEFAULT_JQL).strip(),
            jql_active=str(raw.get("jql_active", "") or DEFAULT_JQL_ACTIVE).strip(),
            enabled=bool(raw.get("enabled", True)),
            ca_file=str(raw.get("ca_file", "")).strip(),
            proxy=str(raw.get("proxy", "")).strip(),
            auth=str(raw.get("auth", AUTH_AUTO)).strip() or AUTH_AUTO,
        )


def normalize_base_url(value: str) -> str:
    """Приводит адрес Jira к корню.

    Люди копируют адрес из строки браузера — вместе с /browse/PROJ-1,
    /secure/Dashboard.jspa или параметрами. По такому адресу REST не отвечает.
    """
    base = (value or "").strip().rstrip("/")
    if not base:
        return ""
    for marker in ("/browse/", "/secure/", "/projects/", "/jira/software/", "/issues/"):
        position = base.find(marker)
        if position > 0:
            base = base[:position]
            break
    return base.rstrip("/")


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

    def _auth_header(self, scheme: str) -> str:
        if scheme == AUTH_BEARER:
            return "Bearer " + self.config.token
        pair = "%s:%s" % (self.config.email, self.config.token)
        return "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")

    def _get(self, path: str, params: dict[str, str], scheme: str) -> dict:
        base = normalize_base_url(self.config.base_url)
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url)
        request.add_header("Authorization", self._auth_header(scheme))
        request.add_header("Accept", "application/json")
        opener = net.opener(self.config.ca_file, self.config.proxy)
        with opener.open(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8", "replace")
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
        try:
            return json.loads(body)
        except ValueError:
            # Ответ пришёл, но это не данные: чаще всего страница входа,
            # заглушка прокси или адрес, указывающий не на Jira.
            raise JiraError(describe_non_json(url, final_url, content_type, body)) from None

    def whoami(self) -> tuple[str, str]:
        """Проверяет вход. Возвращает (имя пользователя, способ входа).

        Пробует оба способа: облачная Jira принимает почту с API-токеном, а
        Jira Server/Data Center — личный токен в заголовке Bearer. Ошибки от
        обоих попыток запоминаем, чтобы объяснить причину человеку.
        """
        if not self.config.is_configured:
            raise JiraError("Заполните адрес Jira и токен в настройках.")

        problems: list[str] = []
        for scheme in self.config.schemes():
            if scheme == AUTH_BASIC and not self.config.email.strip():
                continue
            for path in WHOAMI_PATHS:
                try:
                    payload = self._get(path, {}, scheme)
                except urllib.error.HTTPError as exc:
                    if exc.code in (404, 410):
                        continue          # этого адреса нет — пробуем следующий
                    problems.append(self._http_message(exc, scheme))
                    break                 # 401/403 — способ не подошёл целиком
                except urllib.error.URLError as exc:
                    raise JiraError(
                        "Не удалось соединиться с Jira: %s"
                        % net.describe(exc.reason, self._host())
                    ) from exc
                except ssl.SSLError as exc:
                    raise JiraError("Jira: %s" % net.describe(exc)) from exc
                except JiraError as exc:
                    # Пришла страница, а не данные — значит неверен сам адрес,
                    # и другие версии API ответят тем же. Пробуем другой вход.
                    problems.append(str(exc))
                    break

                self._scheme = scheme
                name = (
                    payload.get("displayName")
                    or payload.get("name")
                    or payload.get("emailAddress")
                    or "пользователь"
                )
                return name, scheme

        # Одинаковые жалобы от разных способов входа не повторяем.
        unique: list[str] = []
        for message in problems:
            if message not in unique:
                unique.append(message)
        raise JiraError(
            "\n\n".join(unique) or "Jira не приняла ни один способ входа."
        )

    def _host(self) -> str:
        """Имя сервера из настроек — чтобы называть его в сообщениях об ошибке."""
        return urllib.parse.urlsplit(self.config.base_url).hostname or ""

    def _search_paths(self) -> tuple[str, ...]:
        """Какой адрес поиска пробовать первым — облачный или свой."""
        host = urllib.parse.urlsplit(self.config.base_url).hostname or ""
        cloud = host.endswith(".atlassian.net") or self.config.auth == AUTH_BASIC
        return CLOUD_SEARCH_PATHS if cloud else SERVER_SEARCH_PATHS

    def search(self, jql: str = "", limit: int = 50) -> list[JiraIssue]:
        """Возвращает задачи по JQL. Бросает JiraError с понятным текстом."""
        if not self.config.is_configured:
            raise JiraError("Заполните адрес, e-mail и API-токен Jira в настройках.")
        query = (jql or self.config.jql or DEFAULT_JQL).strip()
        params = {"jql": query, "maxResults": str(limit), "fields": FIELDS}

        scheme = getattr(self, "_scheme", "")
        if not scheme:
            _, scheme = self.whoami()  # заодно поймём, какой вход работает
        paths = self._search_paths()

        last_error: Exception | None = None
        for path in paths:
            try:
                payload = self._get(path, params, scheme)
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):  # эндпоинта нет — пробуем следующий
                    last_error = exc
                    continue
                raise JiraError(self._http_message(exc, scheme)) from exc
            except urllib.error.URLError as exc:
                raise JiraError(
                    "Не удалось соединиться с Jira: %s"
                    % net.describe(exc.reason, self._host())
                ) from exc
            except ssl.SSLError as exc:
                raise JiraError("Jira: %s" % net.describe(exc)) from exc
            except JiraError as exc:
                # Ответ страницей: у этой версии API такого адреса нет.
                last_error = exc
                continue
            return [self._issue(item) for item in payload.get("issues", [])]

        if isinstance(last_error, JiraError):
            raise last_error
        raise JiraError(
            "Jira не отвечает ни на один из известных адресов поиска (%s)." % (last_error or "")
        )

    @staticmethod
    def _http_message(exc: urllib.error.HTTPError, scheme: str = "") -> str:
        """Объясняет ответ Jira так, чтобы было понятно, что делать дальше."""
        if exc.code == 401:
            if scheme == AUTH_BEARER:
                return (
                    "401: Jira не приняла личный токен. Проверьте, что токен создан "
                    "в вашем профиле Jira (Profile → Personal Access Tokens) и не истёк."
                )
            return (
                "401: Jira не приняла пару «e-mail + API-токен». Так входят только в "
                "облачную Jira (адрес вида *.atlassian.net). Если Jira корпоративная, "
                "выберите способ входа «Своя Jira (Server/DC)» и укажите личный токен."
            )
        if exc.code == 403:
            return (
                "403: доступ запрещён. Частая причина — Jira потребовала капчу после "
                "неудачных попыток входа: откройте Jira в браузере, войдите, введите "
                "капчу и повторите. Ещё вариант — у токена нет прав на чтение задач."
            )
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
