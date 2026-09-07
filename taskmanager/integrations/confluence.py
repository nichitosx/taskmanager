"""Публикация отчётов в Confluence через REST API.

Интеграция выключена, пока в настройках не заданы адрес, e-mail и API-токен.
Используется только стандартная библиотека — лишних зависимостей нет.
"""

from __future__ import annotations

import base64
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


class ConfluenceError(RuntimeError):
    """Ошибка обращения к Confluence с человекочитаемым текстом."""


@dataclass
class ConfluenceConfig:
    base_url: str = ""
    email: str = ""
    token: str = ""
    space_key: str = ""
    parent_id: str = ""

    @classmethod
    def from_settings(cls, data: dict[str, Any]) -> "ConfluenceConfig":
        return cls(
            base_url=(data.get("base_url") or "").strip(),
            email=(data.get("email") or "").strip(),
            token=(data.get("token") or "").strip(),
            space_key=(data.get("space_key") or "").strip(),
            parent_id=str(data.get("parent_id") or "").strip(),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.token and self.space_key)

    @property
    def api_root(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/wiki"):
            return base
        if "atlassian.net" in base:
            return base + "/wiki"
        return base


def markdown_to_storage(markdown: str) -> str:
    """Простая конвертация нашего Markdown в storage format Confluence.

    Поддерживаются заголовки, списки, жирный шрифт, inline-код и ссылки —
    всё, что реально встречается в генерируемых отчётах.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    in_list = False

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
        return text

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = min(len(heading.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (level, inline(heading.group(2)), level))
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(bullet.group(1)))
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append("<p>%s</p>" % inline(line))

    if in_list:
        out.append("</ul>")
    return "\n".join(out)


class ConfluenceClient:
    def __init__(self, config: ConfluenceConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    # --- Низкий уровень -------------------------------------------------------

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        if not self.config.is_configured:
            raise ConfluenceError("Интеграция с Confluence не настроена.")
        url = self.config.api_root + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        credentials = "%s:%s" % (self.config.email, self.config.token)
        auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", "Basic " + auth)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            if exc.code in (401, 403):
                raise ConfluenceError(
                    "Confluence отклонил доступ (%s). Проверьте e-mail и API-токен." % exc.code
                ) from exc
            raise ConfluenceError("Confluence вернул ошибку %s: %s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise ConfluenceError("Не удалось связаться с Confluence: %s" % exc.reason) from exc
        return json.loads(body) if body else {}

    # --- Операции -------------------------------------------------------------

    def check_connection(self) -> str:
        """Проверяет доступ и возвращает название пространства."""
        data = self._request("GET", "/rest/api/space/" + self.config.space_key)
        return data.get("name") or self.config.space_key

    def find_page(self, title: str) -> Optional[dict]:
        query = urllib.parse.urlencode(
            {"title": title, "spaceKey": self.config.space_key, "expand": "version"}
        )
        data = self._request("GET", "/rest/api/content?" + query)
        results = data.get("results") or []
        return results[0] if results else None

    def publish(self, title: str, markdown: str) -> str:
        """Создаёт страницу или обновляет существующую с тем же заголовком.

        Возвращает ссылку на страницу.
        """
        storage = markdown_to_storage(markdown)
        existing = self.find_page(title)
        if existing:
            version = int(existing.get("version", {}).get("number", 1)) + 1
            payload = {
                "id": existing["id"],
                "type": "page",
                "title": title,
                "space": {"key": self.config.space_key},
                "body": {"storage": {"value": storage, "representation": "storage"}},
                "version": {"number": version},
            }
            data = self._request("PUT", "/rest/api/content/" + existing["id"], payload)
        else:
            payload = {
                "type": "page",
                "title": title,
                "space": {"key": self.config.space_key},
                "body": {"storage": {"value": storage, "representation": "storage"}},
            }
            if self.config.parent_id:
                payload["ancestors"] = [{"id": self.config.parent_id}]
            data = self._request("POST", "/rest/api/content", payload)

        webui = (data.get("_links") or {}).get("webui", "")
        return self.config.api_root + webui if webui else self.config.api_root
