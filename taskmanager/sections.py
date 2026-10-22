"""Свои разделы: подборки задач по правилу, которое задаёт пользователь.

Раздел — это название и правило. Правило бывает разным: фильтр Jira (задачи
читаются из Jira), продукт, ключевые слова, тег, проект Jira по ключу,
важность или близкий срок. Все правила, кроме Jira, разбирают ваши
собственные задачи — им не нужна ни сеть, ни настройка Jira.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import PRIORITY_LABELS, Task

KIND_JIRA = "jira"
KIND_PRODUCT = "product"
KIND_KEYWORD = "keyword"
KIND_TAG = "tag"
KIND_PROJECT = "project"
KIND_PRIORITY = "priority"
KIND_DUE = "due"

# Порядок важен: так виды и показываются в настройках.
KINDS = {
    KIND_PRODUCT: "Продукт",
    KIND_KEYWORD: "Ключевые слова",
    KIND_TAG: "Тег",
    KIND_PROJECT: "Проект Jira (по ключу)",
    KIND_PRIORITY: "Важность не ниже",
    KIND_DUE: "Срок в ближайшие дни",
    KIND_JIRA: "Фильтр Jira (JQL)",
}

# Ключ раздела в меню — по его месту в настройках: переименование не теряет
# выбранный список.
PREFIX = "section:"


@dataclass
class Section:
    key: str
    name: str
    kind: str
    value: str

    @property
    def is_jira(self) -> bool:
        return self.kind == KIND_JIRA

    def describe(self) -> str:
        """Правило словами — для подсказки в меню и в настройках."""
        value = self.value.strip()
        if self.kind == KIND_JIRA:
            return "Jira: %s" % value
        if self.kind == KIND_PRODUCT:
            return "продукт «%s»" % value
        if self.kind == KIND_KEYWORD:
            return "в названии, заметках или тегах: %s" % ", ".join(words(value))
        if self.kind == KIND_TAG:
            return "тег #%s" % value.lstrip("#")
        if self.kind == KIND_PROJECT:
            return "ключ Jira %s-…" % project_prefix(value)
        if self.kind == KIND_PRIORITY:
            return "важность не ниже «%s»" % PRIORITY_LABELS.get(_int(value, 2), "")
        if self.kind == KIND_DUE:
            days = _int(value, 7)
            return "срок в ближайшие %d дн. и просроченное" % days
        return value

    def matches(self, task: Task) -> bool:
        return matches(task, self.kind, self.value)


def _int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def words(value: str) -> list[str]:
    """Слова через запятую — в нижнем регистре, без пустых."""
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def project_prefix(value: str) -> str:
    return (value or "").strip().upper().rstrip("-")


def matches(task: Task, kind: str, value: str) -> bool:
    """Подходит ли своя задача под правило раздела."""
    value = (value or "").strip()
    if kind == KIND_PRODUCT:
        return bool(value) and (task.product or "").lower() == value.lower()
    if kind == KIND_KEYWORD:
        haystack = " ".join([task.title or "", task.notes or "", " ".join(task.tags)]).lower()
        return any(word in haystack for word in words(value))
    if kind == KIND_TAG:
        tag = value.lstrip("#").lower()
        return bool(tag) and tag in [t.lower() for t in task.tags]
    if kind == KIND_PROJECT:
        prefix = project_prefix(value)
        return bool(prefix) and (task.jira_key or "").upper().startswith(prefix + "-")
    if kind == KIND_PRIORITY:
        return task.priority >= _int(value, 2)
    if kind == KIND_DUE:
        days = task.days_to_due
        return days is not None and days <= _int(value, 7)
    return False


def load(settings) -> list[Section]:
    """Разделы из настроек. Пустые и непонятные пропускаем.

    Разделы прошлой версии жили в ``jira.sections`` и были только про Jira —
    они читаются как разделы с фильтром Jira.
    """
    raw_sections = settings.get("sections", None)
    if raw_sections is None:
        raw_sections = [
            {"name": raw.get("name", ""), "kind": KIND_JIRA, "value": raw.get("jql", "")}
            for raw in (settings.get("jira.sections", []) or [])
            if isinstance(raw, dict)
        ]
    sections = []
    for index, raw in enumerate(raw_sections or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "") or "").strip()
        kind = str(raw.get("kind", "") or KIND_JIRA)
        value = str(raw.get("value", raw.get("jql", "")) or "").strip()
        if name and kind in KINDS and value:
            sections.append(Section("%s%d" % (PREFIX, index), name, kind, value))
    return sections


def raw(settings) -> list[dict]:
    """Разделы как они лежат в настройках — для правки, включая неполные."""
    raw_sections = settings.get("sections", None)
    if raw_sections is None:
        return [
            {"name": str(item.get("name", "")), "kind": KIND_JIRA,
             "value": str(item.get("jql", ""))}
            for item in (settings.get("jira.sections", []) or [])
            if isinstance(item, dict)
        ]
    return [
        {"name": str(item.get("name", "")), "kind": str(item.get("kind", KIND_JIRA)),
         "value": str(item.get("value", ""))}
        for item in raw_sections
        if isinstance(item, dict)
    ]


def apply_to_new_task(task: Task, section: Section) -> None:
    """Задача, заведённая из раздела, сразу в него и попадает — где это можно."""
    if section.kind == KIND_PRODUCT and not task.product:
        task.product = section.value
    elif section.kind == KIND_TAG:
        tag = section.value.lstrip("#")
        if tag and tag.lower() not in [t.lower() for t in task.tags]:
            task.tags.append(tag)
    elif section.kind == KIND_PRIORITY:
        task.priority = max(task.priority, _int(section.value, 2))
