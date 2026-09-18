"""Чтение календаря по секретному адресу iCal.

У Google-календаря есть «секретный адрес в формате iCal»: постоянная ссылка,
по которой календарь отдаётся файлом. Этого хватает, чтобы видеть встречи в
программе — и не нужно ни проекта в Google Cloud, ни входа, ни разрешений.

Писать по такой ссылке нельзя: она только на чтение. Создание событий из
программы — отдельная работа, для неё понадобятся настоящие доступы.

Формат простой: текст из строк ``КЛЮЧ:значение``, события между BEGIN:VEVENT и
END:VEVENT. Разбираем сами: ради одного формата тянуть стороннюю библиотеку в
программу, которую ставят на рабочий ноутбук, не хочется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import net

# Строка длиннее 75 символов переносится, продолжение начинается с пробела.
FOLD_RE = re.compile(r"\r?\n[ \t]")

# Экранированные символы в тексте: переводы строк, запятые, точки с запятой.
# Обратная косая идёт последней: иначе она испортила бы остальные замены.
UNESCAPE = (
    (r"\n", "\n"),
    (r"\N", "\n"),
    (r"\,", ","),
    (r"\;", ";"),
    (r"\\", "\\"),
)


# Правильный секретный адрес оканчивается на /basic.ics и несёт длинный ключ
# после слова private. Всё остальное Google закрывает входом.
SECRET_RE = re.compile(r"/calendar/ical/.+/private-[^/]+/basic\.ics$", re.IGNORECASE)

WHERE_TO_GET = (
    "Адрес берётся так: откройте нужный календарь в Google, «Настройки и общий "
    "доступ» → «Интеграция календаря» → «Секретный адрес в формате iCal». Он "
    "оканчивается на /basic.ics и содержит длинный ключ после слова private."
)

WORKSPACE_HINT = (
    "В корпоративном Google (Workspace) администратор может запрещать внешний "
    "доступ к календарям — тогда секретный адрес не работает ни в одной "
    "программе. Проверить просто: откройте этот адрес в окне браузера без входа "
    "в аккаунт. Если и там просят войти — доступ закрыт, и обойти это нельзя. "
    "Тогда остаётся выгрузить календарь файлом .ics и указать путь к нему."
)


def looks_like_secret(url: str) -> bool:
    """Похож ли адрес на секретный iCal — до всякой сети."""
    return bool(SECRET_RE.search(normalize_url(url).split("?")[0]))


def looks_like_login(text: str, final_url: str = "") -> bool:
    """Ответ — это страница входа, а не календарь?"""
    probe = (final_url + " " + (text or "")[:400]).lower()
    return any(
        marker in probe
        for marker in ("accounts.google.com", "servicelogin", "signin", "<html")
    )


class CalendarError(Exception):
    """Не удалось прочитать календарь — текст пригоден для показа человеку."""


@dataclass
class Event:
    """Событие календаря."""

    uid: str = ""
    title: str = ""
    at: Optional[datetime] = None
    until: Optional[datetime] = None
    all_day: bool = False
    location: str = ""

    @property
    def when(self) -> Optional[date]:
        return self.at.date() if self.at else None

    def clock(self) -> str:
        if self.all_day or not self.at:
            return "весь день"
        return self.at.strftime("%H:%M")


def normalize_url(value: str) -> str:
    """Приводит ссылку к виду, который можно скачать.

    Google даёт адрес вида ``webcal://`` — это тот же https, просто с другой
    схемой, чтобы его подхватывала системная программа календаря.
    """
    url = (value or "").strip()
    if not url:
        return ""
    if url.startswith("webcal://"):
        return "https://" + url[len("webcal://"):]
    return url


def parse_moment(raw: str) -> tuple[Optional[datetime], bool]:
    """Разбирает дату-время события. Возвращает (момент, весь ли день)."""
    raw = (raw or "").strip()
    if not raw:
        return None, False
    # Метка времени в UTC оканчивается на Z; без неё время местное.
    utc = raw.endswith("Z")
    clean = raw[:-1] if utc else raw
    try:
        if len(clean) == 8:
            return datetime.strptime(clean, "%Y%m%d"), True
        moment = datetime.strptime(clean[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None, False
    if utc:
        # Приводим к местному времени: человек смотрит на свои часы.
        moment = moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return moment, False


def unescape(text: str) -> str:
    for pattern, replacement in UNESCAPE:
        text = text.replace(pattern, replacement)
    return text


def parse(text: str, final_url: str = "") -> list[Event]:
    """Достаёт события из текста календаря."""
    if not text or "BEGIN:VCALENDAR" not in text.upper():
        if looks_like_login(text, final_url):
            raise CalendarError(
                "Вместо календаря пришла страница входа Google: по этому адресу "
                "нужен вход, а программа входить не умеет.\n\n%s\n\n%s"
                % (WHERE_TO_GET, WORKSPACE_HINT)
            )
        raise CalendarError(
            "По этой ссылке пришёл не календарь.\n\n%s" % WHERE_TO_GET
        )

    events: list[Event] = []
    current: Optional[Event] = None
    for line in FOLD_RE.sub("", text).splitlines():
        upper = line.upper()
        if upper.startswith("BEGIN:VEVENT"):
            current = Event()
            continue
        if upper.startswith("END:VEVENT"):
            if current is not None and current.title:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        name, _, value = line.partition(":")
        key = name.split(";")[0].upper()
        if key == "UID":
            current.uid = value.strip()
        elif key == "SUMMARY":
            current.title = unescape(value.strip())
        elif key == "LOCATION":
            current.location = unescape(value.strip())
        elif key == "DTSTART":
            current.at, current.all_day = parse_moment(value)
        elif key == "DTEND":
            current.until, _ = parse_moment(value)

    events.sort(key=lambda e: (e.at is None, e.at or datetime.max))
    return events


def read_file(path: str) -> list[Event]:
    """Читает календарь из файла .ics, выгруженного вручную.

    Запасной путь для корпоративного календаря: если администратор закрыл
    внешний доступ, секретного адреса не будет ни у одной программы, зато
    выгрузить файл можно всегда.
    """
    from pathlib import Path

    source = Path(path.strip('"').strip())
    try:
        return parse(source.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise CalendarError("Не удалось прочитать файл календаря: %s" % exc) from exc


def is_file_source(value: str) -> bool:
    """Это путь к файлу, а не ссылка?

    Расширения мало: файл могли назвать как угодно. Поэтому если схемы нет, а
    такой файл на диске есть — считаем путём.
    """
    from pathlib import Path

    text = (value or "").strip().strip('"')
    if not text or "://" in text:
        return False
    if text.lower().endswith(".ics"):
        return True
    try:
        return Path(text).is_file()
    except OSError:
        return False


def fetch(url: str, timeout: int = 20, ca_file: str = "", proxy: str = "") -> list[Event]:
    """Читает календарь: по ссылке или из файла .ics."""
    import urllib.error
    import urllib.parse
    import urllib.request

    if is_file_source(url):
        return read_file(url)

    address = normalize_url(url)
    if not address:
        raise CalendarError("Ссылка на календарь не указана.")

    request = urllib.request.Request(address, headers={"Accept": "text/calendar"})
    try:
        with net.opener(ca_file, proxy).open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            reason = (
                "Адрес не похож на секретный: он должен оканчиваться на "
                "/basic.ics.\n\n%s" % WHERE_TO_GET
                if not looks_like_secret(address)
                else "Адрес выглядит правильно, значит дело в доступе.\n\n%s"
                % WORKSPACE_HINT
            )
            raise CalendarError(
                "Календарь потребовал вход (%s). %s" % (exc.code, reason)
            ) from exc
        if exc.code == 404:
            raise CalendarError(
                "Календаря по этому адресу нет (404). Секретный адрес могли "
                "сбросить — возьмите его заново.\n\n%s" % WHERE_TO_GET
            ) from exc
        raise CalendarError("Календарь ответил ошибкой %s." % exc.code) from exc
    except urllib.error.URLError as exc:
        host = urllib.parse.urlsplit(address).hostname or ""
        raise CalendarError(
            "Не удалось скачать календарь: %s" % net.describe(exc.reason, host)
        ) from exc
    return parse(body, final_url)


def between(events: list[Event], start: date, end: date) -> dict:
    """Раскладывает события по дням внутри отрезка."""
    by_day: dict = {}
    for event in events:
        day = event.when
        if day is None or not (start <= day <= end):
            continue
        by_day.setdefault(day, []).append(event)
    return by_day


def next_event(events: list[Event], moment: Optional[datetime] = None) -> Optional[Event]:
    """Ближайшее событие впереди."""
    moment = moment or datetime.now()
    upcoming = [e for e in events if e.at and e.at >= moment]
    return min(upcoming, key=lambda e: e.at) if upcoming else None


def horizon(days: int = 60) -> tuple[date, date]:
    """Отрезок, за который имеет смысл держать события: месяц назад и вперёд."""
    today = date.today()
    return today - timedelta(days=days // 2), today + timedelta(days=days)
