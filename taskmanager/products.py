"""Продукты: справочник направлений работы и угадывание продукта по тексту.

Продукт — это метка вида «над чем именно задача». Список ведётся в настройках,
у каждого продукта есть ключевые слова: если они встретились в названии или
заметках, продукт подставится сам. Подставленное значение всегда можно
поправить руками — автоопределение только предлагает.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Цвета для меток продуктов. Подобраны так, чтобы читаться и на тёмном, и на
# светлом фоне; назначаются по порядку, если у продукта не задан свой цвет.
PALETTE = [
    "#D97757",  # терракотовый
    "#6E8CA8",  # серо-синий
    "#6E9C6A",  # приглушённый зелёный
    "#B08BC0",  # лиловый
    "#C99A3F",  # охра
    "#5FA3A0",  # бирюзовый
    "#C4707E",  # пыльно-розовый
    "#8A8FB0",  # индиго
]


@dataclass
class Product:
    name: str = ""
    keywords: list[str] = field(default_factory=list)
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "keywords": list(self.keywords), "color": self.color}

    @classmethod
    def from_dict(cls, raw: Any) -> "Product":
        if isinstance(raw, str):  # совсем старый формат — просто список имён
            return cls(name=raw.strip())
        if not isinstance(raw, dict):
            return cls()
        keywords = raw.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]
        return cls(
            name=str(raw.get("name", "")).strip(),
            keywords=[str(k).strip() for k in keywords if str(k).strip()],
            color=str(raw.get("color", "")).strip(),
        )


def load(settings) -> list[Product]:
    """Читает справочник продуктов из настроек, отбрасывая пустые записи."""
    raw = settings.get("products", []) or []
    if not isinstance(raw, list):
        return []
    products = [Product.from_dict(item) for item in raw]
    return [p for p in products if p.name]


def save(settings, products: list[Product]) -> None:
    settings.set("products", [p.to_dict() for p in products if p.name])


def names(products: list[Product]) -> list[str]:
    return [p.name for p in products]


def find(products: list[Product], name: str) -> Product | None:
    lowered = (name or "").strip().lower()
    for product in products:
        if product.name.lower() == lowered:
            return product
    return None


def color_for(products: list[Product], name: str, fallback: str = "#6B665F") -> str:
    """Цвет метки продукта: свой, либо назначенный по порядку в списке."""
    for index, product in enumerate(products):
        if product.name.lower() == (name or "").strip().lower():
            return product.color or PALETTE[index % len(PALETTE)]
    return fallback


def _mentions(text: str, needle: str) -> int:
    """Длина совпадения, если слово встречается в тексте целиком, иначе 0."""
    needle = needle.strip().lower()
    if len(needle) < 2:
        return 0
    pattern = r"(?<!\w)" + re.escape(needle) + r"\w{0,3}(?!\w)"
    return len(needle) if re.search(pattern, text) else 0


def detect(text: str, products: list[Product]) -> str:
    """Угадывает продукт по тексту задачи. Пустая строка — не уверены.

    Считаем совпадением и само название продукта, и любое его ключевое слово;
    побеждает самое длинное совпадение — так «личный кабинет» выигрывает у
    короткого «лк», если в тексте есть оба.
    """
    haystack = (text or "").lower()
    if not haystack.strip():
        return ""

    best_name = ""
    best_score = 0
    for product in products:
        score = max(
            [_mentions(haystack, product.name)]
            + [_mentions(haystack, keyword) for keyword in product.keywords]
            or [0]
        )
        if score > best_score:
            best_score = score
            best_name = product.name
    return best_name


def detect_for_task(task, settings) -> str:
    """Продукт для задачи по её названию и заметкам (если автоопределение включено)."""
    if not settings.get("products_autodetect", True):
        return ""
    return detect("%s %s" % (task.title, task.notes), load(settings))


def apply_to_task(task, settings) -> str:
    """Проставляет продукт, если он ещё не задан. Возвращает итоговое значение."""
    if task.product:
        return task.product
    task.product = detect_for_task(task, settings)
    return task.product
