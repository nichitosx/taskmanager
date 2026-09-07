"""Примеры задач для первого запуска.

Пустая программа ничего не объясняет о себе, поэтому при первом старте база
наполняется небольшим набором задач: они показывают сроки, приоритеты, метки
продуктов, плановую задачу и отметку о работе. Убрать их можно одной кнопкой —
идентификаторы созданных записей запомнены, чужие задачи не пострадают.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .models import JIRA_CREATED, JIRA_NOT_NEEDED, STATUS_DONE, Task
from .storage import Storage

META_TASKS = "demo_task_ids"
META_PRODUCTS = "demo_products"
META_DONE = "demo_seeded"

# Продукты-примеры создаются, только если справочник пуст.
DEMO_PRODUCTS = [
    {"name": "Личный кабинет", "keywords": ["лк", "кабинет", "профиль"]},
    {"name": "Биллинг", "keywords": ["счёт", "договор", "выгрузк", "тариф"]},
]


def _task(
    title: str,
    *,
    priority: int = 1,
    due: int | None = None,
    start: int | None = None,
    product: str = "",
    jira_key: str = "",
    jira_state: str = "",
    tags: list[str] | None = None,
    notes: str = "",
) -> Task:
    today = date.today()
    task = Task(title=title, priority=priority, product=product, notes=notes)
    task.due_date = today + timedelta(days=due) if due is not None else None
    task.start_date = today + timedelta(days=start) if start is not None else None
    task.tags = list(tags or [])
    if jira_key:
        task.jira_key = jira_key
        task.jira_state = JIRA_CREATED
    elif jira_state:
        task.jira_state = jira_state
    return task


def _samples() -> list[Task]:
    return [
        _task(
            "Пример: собрать выгрузку по договорам",
            priority=2,
            due=0,
            product="Биллинг",
            jira_key="DEMO-142",
            tags=["выгрузки"],
            notes="Это пример задачи. Откройте карточку двойным кликом — "
            "внутри срок, дата начала, продукт и привязка к Jira.",
        ),
        _task(
            "Пример: согласовать макет личного кабинета",
            due=2,
            product="Личный кабинет",
            tags=["дизайн"],
            notes="У этой задачи вопрос с Jira ещё не решён — она попадёт "
            "в список «Ждут Jira» и в недельный отчёт.",
        ),
        _task(
            "Пример: просроченная задача",
            priority=3,
            due=-2,
            product="Биллинг",
            notes="Срок был позавчера, поэтому строка подсвечена и попала "
            "в список «Просрочено».",
        ),
        _task(
            "Пример: плановая задача на будущее",
            start=5,
            due=20,
            product="Личный кабинет",
            notes="Работа ещё не началась. Такие задачи лежат в списке "
            "«Плановые», а за неделю до старта программа напомнит.",
        ),
        _task(
            "Пример: задача без Jira",
            jira_state=JIRA_NOT_NEEDED,
            tags=["документы"],
            notes="Отмечено «Jira не нужна» — из напоминаний исчезла.",
        ),
    ]


def seed(storage: Storage, settings) -> list[int]:
    """Создаёт примеры. Возвращает идентификаторы созданных задач."""
    if not settings.get("products", []):
        settings.set("products", [dict(p) for p in DEMO_PRODUCTS])
        settings.save()
        storage.set_meta(META_PRODUCTS, ",".join(p["name"] for p in DEMO_PRODUCTS))

    created: list[int] = []
    for task in _samples():
        created.append(storage.add_task(task).id)

    # Немного истории, чтобы отчёты не были пустыми.
    yesterday = date.today() - timedelta(days=1)
    storage.add_work_log(created[0], "разобрался с форматом, жду данные", yesterday)
    storage.add_work_log(created[1], "показал макет, собрал правки", yesterday)
    storage.save_daily_report(
        yesterday,
        "Пример отчёта за день: так выглядит запись, если вечером описать день своими словами.",
    )

    done = storage.add_task(_task("Пример: выполненная задача", product="Биллинг"))
    storage.add_work_log(done.id, "доделал и закрыл", yesterday)
    storage.set_status(done.id, STATUS_DONE)
    created.append(done.id)

    # Задача, по которой давно не было движения — покажет метку «тишина N дн.».
    stale = storage.add_task(
        _task("Пример: задача без движения", product="Личный кабинет", tags=["инфра"])
    )
    old = (datetime.now() - timedelta(days=9)).isoformat(timespec="seconds")
    storage.conn.execute(
        "UPDATE tasks SET last_activity_at=?, updated_at=? WHERE id=?", (old, old, stale.id)
    )
    storage.conn.commit()
    created.append(stale.id)

    # Примеры могли добавляться и раньше — не теряем прошлые идентификаторы,
    # иначе «Убрать примеры» уберёт не всё.
    known = remaining_ids(storage)
    storage.set_meta(META_TASKS, ",".join(str(i) for i in known + created))
    storage.set_meta(META_DONE, "1")
    return created


def seed_if_empty(storage: Storage, settings) -> list[int]:
    """Наполняет базу примерами при самом первом запуске.

    Ничего не делает, если задачи уже есть или примеры когда-то уже создавались,
    — повторно навязывать их нельзя.
    """
    if storage.get_meta(META_DONE) == "1":
        return []
    if storage.list_tasks(include_done=True, include_archived=True):
        storage.set_meta(META_DONE, "1")  # база не пустая: примеры не нужны
        return []
    return seed(storage, settings)


def remaining_ids(storage: Storage) -> list[int]:
    """Идентификаторы примеров, которые ещё есть в базе."""
    raw = storage.get_meta(META_TASKS, "")
    ids = [int(part) for part in raw.split(",") if part.strip().isdigit()]
    return [task_id for task_id in ids if storage.get_task(task_id) is not None]


def remove(storage: Storage, settings) -> int:
    """Удаляет примеры вместе с их отметками. Возвращает число удалённых задач."""
    removed = 0
    for task_id in remaining_ids(storage):
        storage.delete_task(task_id)
        removed += 1
    storage.set_meta(META_TASKS, "")

    # Продукты-примеры убираем, только если ими никто не пользуется.
    demo_products = [p for p in storage.get_meta(META_PRODUCTS, "").split(",") if p]
    if demo_products:
        in_use = {name.lower() for name in storage.products_in_use()}
        keep = [
            product
            for product in (settings.get("products", []) or [])
            if not isinstance(product, dict)
            or product.get("name") not in demo_products
            or product.get("name", "").lower() in in_use
        ]
        settings.set("products", keep)
        settings.save()
        storage.set_meta(META_PRODUCTS, "")
    return removed
