"""Главное окно: быстрый ввод, список задач, панель деталей, трей."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import demo
from .. import products as products_module
from .. import quickadd
from ..appicon import make_icon
from ..config import Settings
from ..horizons import HORIZON_HINTS, HORIZON_LABELS, in_horizon, start_text
from ..integrations import jira
from ..models import (
    JIRA_NOT_NEEDED,
    JIRA_STATE_LABELS,
    PRIORITY_LABELS,
    STATUS_ACTIVE,
    STATUS_DONE,
    Task,
)
from ..reports import fmt_date
from ..scheduler import Scheduler
from ..storage import Storage
from . import theme
from .dialogs import DailyReportDialog, LogWorkDialog, TaskDialog, UpcomingTasksDialog
from .reports_ui import HistoryDialog, WeeklyReportDialog
from .settings_dialog import SettingsDialog
from .widgets import NavItem, StatChip, TaskRow, hline, section_label

# Боковое меню делится на две части: «когда» — горизонты планирования,
# «состояние» — то, что требует внимания независимо от сроков.
HORIZON_FILTERS = [(key, HORIZON_LABELS[key]) for key in ("today", "week", "month", "planned")]

STATE_FILTERS = [
    ("active", "Все активные"),
    ("overdue", "Просрочено"),
    ("stale", "Без движения"),
    ("jira", "Ждут Jira"),
    ("done", "Выполненные"),
]

FILTERS = HORIZON_FILTERS + STATE_FILTERS

PRODUCT_PREFIX = "product:"


class TaskDetail(QWidget):
    """Правая панель: подробности выбранной задачи."""

    def __init__(self, storage: Storage, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.task: Task | None = None
        self.owner = parent
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 4, 12)
        layout.setSpacing(10)

        self.placeholder = QLabel(
            "Выберите задачу слева.\n\nДвойной клик открывает карточку,\n"
            "правая кнопка — быстрые действия."
        )
        self.placeholder.setProperty("faint", "true")
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, 0, Qt.AlignmentFlag.AlignTop)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        layout.addWidget(self.body, 1)

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setFont(theme.ui_font(13, bold=True))
        body_layout.addWidget(self.title)

        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setFont(theme.mono_font(8))
        self.meta.setProperty("dim", "true")
        body_layout.addWidget(self.meta)

        body_layout.addWidget(hline())

        body_layout.addWidget(section_label("заметки"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Детали, ссылки, договорённости")
        self.notes.setFixedHeight(120)
        self.notes.focusOutEvent = self._notes_focus_out  # type: ignore[assignment]
        body_layout.addWidget(self.notes)

        body_layout.addWidget(section_label("история работы"))
        self.history = QListWidget()
        self.history.setFont(theme.mono_font(9))
        body_layout.addWidget(self.history, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.log_button = QPushButton("Отметить работу")
        self.log_button.setProperty("accent", "true")
        self.log_button.clicked.connect(self._log_work)
        row1.addWidget(self.log_button)
        self.edit_button = QPushButton("Изменить")
        self.edit_button.clicked.connect(self._edit)
        row1.addWidget(self.edit_button)
        buttons.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.jira_button = QPushButton("Открыть в Jira")
        self.jira_button.setProperty("flat", "true")
        self.jira_button.clicked.connect(self._open_jira)
        row2.addWidget(self.jira_button)
        self.no_jira_button = QPushButton("Jira не нужна")
        self.no_jira_button.setProperty("flat", "true")
        self.no_jira_button.clicked.connect(self._mark_no_jira)
        row2.addWidget(self.no_jira_button)
        row2.addStretch(1)
        buttons.addLayout(row2)
        body_layout.addLayout(buttons)

        self.body.hide()

    # --- Отображение ----------------------------------------------------------

    def show_task(self, task: Task | None) -> None:
        self.task = task
        if task is None:
            self.body.hide()
            self.placeholder.show()
            return
        self.placeholder.hide()
        self.body.show()

        self.title.setText(task.title)
        parts = [PRIORITY_LABELS.get(task.priority, "обычный")]
        if task.product:
            parts.append(task.product)
        if task.is_planned:
            parts.append(start_text(task))
        if task.due_date:
            parts.append("срок %s" % fmt_date(task.due_date))
        if self.settings.get("jira.enabled", True):
            if task.jira_key:
                parts.append(task.jira_key)
            else:
                parts.append("jira: %s" % JIRA_STATE_LABELS.get(task.jira_state, "не решено"))
        parts.append("без движения %d дн." % task.days_since_activity)
        if task.tags:
            parts.append(" ".join("#" + t for t in task.tags))
        self.meta.setText("  ·  ".join(parts))

        self.notes.blockSignals(True)
        self.notes.setPlainText(task.notes)
        self.notes.blockSignals(False)

        self.history.clear()
        logs = self.storage.logs_for_task(task.id)
        if not logs:
            self.history.addItem("Отметок пока нет — нажмите «Отметить работу»")
        for log in logs:
            self.history.addItem(
                "%s  %s" % (log.log_date.strftime("%d.%m"), log.comment or "работа по задаче")
            )

        jira_on = bool(self.settings.get("jira.enabled", True))
        self.jira_button.setVisible(jira_on)
        self.jira_button.setEnabled(bool(task.jira_key))
        self.no_jira_button.setVisible(jira_on and task.jira_state != JIRA_NOT_NEEDED)

    # --- Действия -------------------------------------------------------------

    def _notes_focus_out(self, event) -> None:
        QPlainTextEdit.focusOutEvent(self.notes, event)
        if self.task is None:
            return
        text = self.notes.toPlainText().strip()
        if text != self.task.notes:
            self.task.notes = text
            self.storage.update_task(self.task)
            if self.owner is not None:
                self.owner.refresh(keep_selection=True)

    def _log_work(self) -> None:
        if self.task is None:
            return
        dialog = LogWorkDialog(self.task, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.storage.add_work_log(self.task.id, dialog.text())
            if self.owner is not None:
                self.owner.refresh(keep_selection=True)

    def _edit(self) -> None:
        if self.task is not None and self.owner is not None:
            self.owner.open_task(self.task.id)

    def _open_jira(self) -> None:
        if self.task is None:
            return
        base = self.settings.get("jira.base_url", "")
        if not jira.open_issue(base, self.task.jira_key):
            QMessageBox.information(
                self, "Jira", "Укажите адрес Jira в настройках, чтобы открывать задачи по ключу."
            )

    def _mark_no_jira(self) -> None:
        if self.task is None:
            return
        self.task.jira_state = JIRA_NOT_NEEDED
        self.task.jira_key = ""
        self.storage.update_task(self.task, touch_activity=False)
        if self.owner is not None:
            self.owner.refresh(keep_selection=True)


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage, settings: Settings) -> None:
        super().__init__()
        self.storage = storage
        self.settings = settings
        self.filter = "active"
        self.selected_id: int | None = None
        theme.set_style(settings.get("ui_style", theme.STYLE_SOFT))
        self.colors = theme.palette(settings.get("theme", "dark"))
        self._force_quit = False

        self.setWindowTitle("TaskManager")
        self.setWindowIcon(self._icon())
        self.resize(1180, 760)
        self.setMinimumSize(940, 600)

        self._build()
        self._build_tray()
        self._build_shortcuts()

        self.scheduler = Scheduler(storage, settings, self)
        self.scheduler.eod_due.connect(self._on_eod_due)
        self.scheduler.weekly_due.connect(self._on_weekly_due)
        self.scheduler.missed_report.connect(self._on_missed_report)
        self.scheduler.starts_soon.connect(self._on_starts_soon)
        self.scheduler.start()

        demo.seed_if_empty(storage, settings)
        self.refresh()

    # --- Интерфейс ------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())
        root.addWidget(hline())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(0)
        root.addWidget(body, 1)

        body_layout.addWidget(self._sidebar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        body_layout.addWidget(splitter, 1)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 0, 4, 0)
        center_layout.setSpacing(12)
        splitter.addWidget(center)

        self.demo_bar = self._demo_bar()
        center_layout.addWidget(self.demo_bar)

        self.quick_add = QLineEdit()
        self.quick_add.setPlaceholderText(
            "Новая задача — Enter, чтобы добавить.  !! срочно   @завтра   #тег   PROJ-142"
        )
        self.quick_add.setFont(theme.ui_font(11))
        self.quick_add.setMinimumHeight(42)
        self.quick_add.returnPressed.connect(self._quick_add)
        center_layout.addWidget(self.quick_add)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по задачам")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self.refresh())
        search_row.addWidget(self.search, 1)
        self.filter_label = QLabel()
        self.filter_label.setFont(theme.mono_font(8))
        self.filter_label.setProperty("faint", "true")
        search_row.addWidget(self.filter_label)
        center_layout.addLayout(search_row)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        center_layout.addWidget(self.list, 1)

        self.empty_label = QLabel()
        self.empty_label.setProperty("faint", "true")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        center_layout.addWidget(self.empty_label)

        self.detail = TaskDetail(self.storage, self.settings, self)
        splitter.addWidget(self.detail)
        splitter.setSizes([700, 380])
        splitter.setCollapsible(0, False)

    def _demo_bar(self) -> QWidget:
        """Полоса-подсказка про задачи-примеры с кнопкой «убрать»."""
        c = self.colors
        bar = QFrame()
        bar.setObjectName("demoBar")
        bar.setStyleSheet(
            "#demoBar { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (theme.tint(c["info"], 0.10), theme.tint(c["info"], 0.30), theme.radius("card"))
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(13, 8, 10, 8)
        layout.setSpacing(10)

        label = QLabel(
            "Это задачи-примеры — посмотрите, как всё устроено, и убирайте."
        )
        label.setWordWrap(True)
        label.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
        layout.addWidget(label, 1)

        remove = QPushButton("Убрать примеры")
        remove.setProperty("flat", "true")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(self._remove_demo)
        layout.addWidget(remove)
        bar.hide()
        return bar

    def _remove_demo(self) -> None:
        removed = demo.remove(self.storage, self.settings)
        self.selected_id = None
        self.refresh(keep_selection=False)
        self.statusBar().showMessage("Примеры убраны (%d шт.)" % removed, 3000)

    def _header(self) -> QWidget:
        c = self.colors
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 14, 20, 10)
        layout.setSpacing(22)

        logo = QLabel("TASKMANAGER")
        logo.setFont(theme.mono_font(11, bold=True, spacing=2.5))
        logo.setStyleSheet("color: %s;" % c["text"])
        layout.addWidget(logo)

        dot = QLabel("•")
        dot.setStyleSheet("color: %s; font-size: 18px;" % c["accent"])
        layout.addWidget(dot)

        self.chips: dict[str, StatChip] = {}
        for key, caption in (
            ("active", "в работе"),
            ("today", "на сегодня"),
            ("planned", "плановых"),
            ("overdue", "просрочено"),
            ("stale", "без движения"),
            ("jira", "ждут jira"),
        ):
            chip = StatChip(caption, c)
            chip.clicked.connect(lambda k=key: self.set_filter(k))
            self.chips[key] = chip
            layout.addWidget(chip)

        layout.addStretch(1)

        daily = QPushButton("Отчёт за день")
        daily.setProperty("flat", "true")
        daily.clicked.connect(self.open_daily)
        layout.addWidget(daily)

        weekly = QPushButton("Неделя")
        weekly.setProperty("flat", "true")
        weekly.clicked.connect(lambda: self.open_weekly())
        layout.addWidget(weekly)

        history = QPushButton("История")
        history.setProperty("flat", "true")
        history.clicked.connect(self.open_history)
        layout.addWidget(history)

        settings_button = QPushButton("Настройки")
        settings_button.setProperty("flat", "true")
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(settings_button)

        return header

    def _sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(202)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(3)
        self.nav_items: dict[str, NavItem] = {}

        layout.addWidget(section_label("когда"))
        layout.addSpacing(2)
        for key, title in HORIZON_FILTERS:
            layout.addWidget(self._nav_item(key, title, HORIZON_HINTS.get(key, "")))

        layout.addSpacing(12)
        layout.addWidget(section_label("состояние"))
        layout.addSpacing(2)
        for key, title in STATE_FILTERS:
            layout.addWidget(self._nav_item(key, title))

        # Раздел продуктов появляется, только когда продукты заведены.
        self.products_caption = section_label("продукты")
        self.products_caption.hide()
        layout.addSpacing(12)
        layout.addWidget(self.products_caption)
        self.products_box = QWidget()
        self.products_layout = QVBoxLayout(self.products_box)
        self.products_layout.setContentsMargins(0, 2, 0, 0)
        self.products_layout.setSpacing(3)
        layout.addWidget(self.products_box)

        layout.addStretch(1)

        hint = QLabel(
            "!!  срочно\n"
            "@завтра  @пт  @кмес  срок\n"
            ">15.10  начать позже\n"
            "#тег  ·  PROJ-142"
        )
        hint.setWordWrap(True)
        hint.setFont(theme.mono_font(8))
        hint.setProperty("faint", "true")
        layout.addWidget(hint)
        return panel

    def _nav_item(self, key: str, title: str, tooltip: str = "") -> NavItem:
        item = NavItem(title, self.colors, self.colors["accent"])
        if tooltip:
            item.setToolTip(tooltip)
        item.clicked.connect(lambda k=key: self.set_filter(k))
        self.nav_items[key] = item
        return item

    def _sync_products_nav(self) -> None:
        """Пересобирает список продуктов в боковой панели."""
        catalog = products_module.load(self.settings)
        known = products_module.names(catalog)
        # Показываем и продукты из справочника, и те, что уже стоят у задач.
        for name in self.storage.products_in_use():
            if name not in known:
                known.append(name)

        for key in [k for k in self.nav_items if k.startswith(PRODUCT_PREFIX)]:
            self.nav_items.pop(key).deleteLater()
        while self.products_layout.count():
            item = self.products_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        self.products_caption.setVisible(bool(known))
        self.products_box.setVisible(bool(known))
        for name in known:
            key = PRODUCT_PREFIX + name
            item = NavItem(name, self.colors, products_module.color_for(catalog, name))
            item.clicked.connect(lambda k=key: self.set_filter(k))
            self.nav_items[key] = item
            self.products_layout.addWidget(item)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("TaskManager")
        menu = QMenu()
        show_action = QAction("Открыть", self)
        show_action.triggered.connect(self._restore)
        menu.addAction(show_action)
        daily_action = QAction("Отчёт за день", self)
        daily_action.triggered.connect(self.open_daily)
        menu.addAction(daily_action)
        weekly_action = QAction("Недельный отчёт", self)
        weekly_action.triggered.connect(lambda: self.open_weekly())
        menu.addAction(weekly_action)
        menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self._restore)
        self.tray.show()

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.quick_add.setFocus)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.open_daily)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=lambda: self.open_weekly())
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._log_selected)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)

    # --- Данные ---------------------------------------------------------------

    def visible_tasks(self) -> list[Task]:
        query = self.search.text().strip()
        if query:
            return self.storage.search_tasks(query)

        stale_days = self.settings.get_int("stale_days", 5)
        if self.filter == "done":
            tasks = [t for t in self.storage.list_tasks(include_done=True) if t.is_done]
            tasks.sort(key=lambda t: t.done_at or t.updated_at, reverse=True)
            return tasks[:100]

        tasks = self.storage.list_tasks(include_done=False)
        if self.filter.startswith(PRODUCT_PREFIX):
            name = self.filter[len(PRODUCT_PREFIX):].lower()
            return [t for t in tasks if t.product.lower() == name]
        if self.filter in HORIZON_LABELS:
            return [t for t in tasks if in_horizon(t, self.filter)]
        if self.filter == "overdue":
            return [t for t in tasks if t.is_overdue]
        if self.filter == "stale":
            return [t for t in tasks if t.is_stale(stale_days)]
        if self.filter == "jira":
            return [t for t in tasks if t.needs_jira()]
        return tasks

    def refresh(self, keep_selection: bool = True) -> None:
        previous = self.selected_id if keep_selection else None
        stale_days = self.settings.get_int("stale_days", 5)

        self.list.clear()
        self.rows: dict[int, TaskRow] = {}
        tasks = self.visible_tasks()
        catalog = products_module.load(self.settings)

        show_jira = bool(self.settings.get("jira.enabled", True))
        for task in tasks:
            color = products_module.color_for(catalog, task.product, self.colors["info"])
            row = TaskRow(task, self.colors, stale_days, color, show_jira)
            row.toggled.connect(self._toggle_task)
            row.activated.connect(self.open_task)
            row.clicked.connect(self._select_task)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, row.sizeHint().height() + 4))
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.rows[task.id] = row

        self.empty_label.setVisible(not tasks)
        self.list.setVisible(bool(tasks))
        self.empty_label.setText(self._empty_text())

        counters = self.storage.counters(stale_days)
        self.chips["active"].set_value(counters["active"])
        self.chips["today"].set_value(counters["today"], self.colors["accent"])
        self.chips["planned"].set_value(counters["planned"], self.colors["info"])
        self.chips["overdue"].set_value(counters["overdue"], self.colors["danger"])
        self.chips["stale"].set_value(counters["stale"], self.colors["warning"])
        self.chips["jira"].set_value(counters["jira"], self.colors["info"])

        searching = bool(self.search.text().strip())
        jira_on = bool(self.settings.get("jira.enabled", True))
        self.chips["jira"].setVisible(jira_on)
        if "jira" in self.nav_items:
            self.nav_items["jira"].setVisible(jira_on)
        if not jira_on and self.filter == "jira":
            self.filter = "active"
        self.demo_bar.setVisible(bool(demo.remaining_ids(self.storage)))
        for key, chip in self.chips.items():
            chip.set_active(key == self.filter and not searching)

        self._sync_products_nav()
        active_tasks = self.storage.list_tasks(include_done=False)
        for key, item in self.nav_items.items():
            item.set_active(key == self.filter and not searching)
            item.set_count(self._nav_count(key, active_tasks, stale_days, counters))

        self.filter_label.setText(
            ("найдено: %d" % len(tasks))
            if searching
            else "%s: %d" % (self._filter_title().lower(), len(tasks))
        )

        if previous is not None and previous in self.rows:
            self._select_task(previous)
        elif previous is not None:
            task = self.storage.get_task(previous)
            self.detail.show_task(task)
        else:
            self.detail.show_task(None)

        self._update_tray_tooltip(counters)

    def _filter_title(self) -> str:
        if self.filter.startswith(PRODUCT_PREFIX):
            return self.filter[len(PRODUCT_PREFIX):]
        return dict(FILTERS).get(self.filter, "")

    def _nav_count(
        self, key: str, tasks: list[Task], stale_days: int, counters: dict[str, int]
    ) -> int:
        """Счётчик рядом с пунктом меню — по тем же правилам, что и сам список."""
        if key.startswith(PRODUCT_PREFIX):
            name = key[len(PRODUCT_PREFIX):].lower()
            return sum(1 for t in tasks if t.product.lower() == name)
        if key == "done":
            return 0  # выполненных много, число тут только мешает
        return counters.get(key, 0)

    def _empty_text(self) -> str:
        if self.search.text().strip():
            return "Ничего не нашлось"
        if self.filter.startswith(PRODUCT_PREFIX):
            return "По продукту «%s» активных задач нет." % self._filter_title()
        return {
            "active": "Задач нет. Введите первую в поле сверху.",
            "today": "На сегодня ничего не запланировано.",
            "week": "На этой неделе задач со сроком нет.",
            "month": "До конца месяца задач со сроком нет.",
            "planned": "Плановых задач нет. Поставьте дату начала в карточке задачи.",
            "overdue": "Просроченных задач нет.",
            "stale": "Все задачи в движении.",
            "jira": "По всем задачам вопрос с Jira закрыт.",
            "done": "Выполненных задач пока нет.",
        }.get(self.filter, "Пусто")

    def _update_tray_tooltip(self, counters: dict[str, int]) -> None:
        self.tray.setToolTip(
            "TaskManager — в работе: %d, просрочено: %d, ждут Jira: %d"
            % (counters["active"], counters["overdue"], counters["jira"])
        )

    # --- Действия со списком --------------------------------------------------

    def set_filter(self, key: str) -> None:
        self.filter = key
        self.search.clear()
        self.refresh(keep_selection=False)

    def _quick_add(self) -> None:
        text = self.quick_add.text().strip()
        if not text:
            return
        task = quickadd.parse(text)
        products_module.apply_to_task(task, self.settings)
        created = self.storage.add_task(task)
        self.quick_add.clear()
        # Остаёмся в текущем списке, только если новая задача в нём видна.
        if all(t.id != created.id for t in self.visible_tasks()):
            self.filter = "planned" if created.is_planned else "active"
        self.selected_id = created.id
        self.refresh()

        parts = ["Добавлено: %s" % created.title]
        if created.product:
            parts.append("продукт «%s»" % created.product)
        if created.is_planned:
            parts.append(start_text(created))
        self.statusBar().showMessage("  ·  ".join(parts), 3500)

    @staticmethod
    def _product_key(task: Task) -> str:
        return PRODUCT_PREFIX + task.product if task.product else ""

    def _select_task(self, task_id: int) -> None:
        self.selected_id = task_id
        for other_id, row in self.rows.items():
            row.set_selected(other_id == task_id)
        self.detail.show_task(self.storage.get_task(task_id))

    def _toggle_task(self, task_id: int, done: bool) -> None:
        self.storage.set_status(task_id, STATUS_DONE if done else STATUS_ACTIVE)
        QTimer.singleShot(120, lambda: self.refresh(keep_selection=True))

    def open_task(self, task_id: int) -> None:
        task = self.storage.get_task(task_id)
        if task is None:
            return
        dialog = TaskDialog(self.storage, self.settings, task, self)
        result = dialog.exec()
        if result == 2:  # задача удалена
            self.selected_id = None
            self.refresh(keep_selection=False)
        elif result == dialog.DialogCode.Accepted:
            self.refresh(keep_selection=True)

    def _log_selected(self) -> None:
        if self.selected_id is not None:
            self.detail._log_work()

    def _context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = self.storage.get_task(task_id)
        if task is None:
            return
        self._select_task(task_id)

        menu = QMenu(self)
        menu.addAction("Открыть карточку", lambda: self.open_task(task_id))
        menu.addAction("Отметить работу", lambda: self.detail._log_work())
        menu.addSeparator()
        if task.is_done:
            menu.addAction("Вернуть в работу", lambda: self._toggle_task(task_id, False))
        else:
            menu.addAction("Выполнена", lambda: self._toggle_task(task_id, True))
        if self.settings.get("jira.enabled", True):
            if task.jira_key:
                menu.addAction(
                    "Открыть в Jira",
                    lambda: jira.open_issue(
                        self.settings.get("jira.base_url", ""), task.jira_key
                    ),
                )
            if task.jira_state != JIRA_NOT_NEEDED:
                menu.addAction("Jira не нужна", lambda: self._set_no_jira(task))
        menu.addSeparator()
        menu.addAction("Удалить", lambda: self._delete_task(task))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _set_no_jira(self, task: Task) -> None:
        task.jira_state = JIRA_NOT_NEEDED
        task.jira_key = ""
        self.storage.update_task(task, touch_activity=False)
        self.refresh(keep_selection=True)

    def _delete_task(self, task: Task) -> None:
        answer = QMessageBox.question(
            self, "Удалить задачу", "Удалить «%s» вместе с историей работы?" % task.title
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.storage.delete_task(task.id)
            self.selected_id = None
            self.refresh(keep_selection=False)

    # --- Отчёты и настройки ---------------------------------------------------

    def open_daily(self, day: date | None = None) -> None:
        dialog = DailyReportDialog(self.storage, self.settings, day, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.scheduler.mark_eod_handled(dialog.day)
            self.statusBar().showMessage("Отчёт за %s сохранён" % fmt_date(dialog.day), 3000)
        self.refresh(keep_selection=True)

    def open_weekly(self, start: date | None = None) -> None:
        dialog = WeeklyReportDialog(self.storage, self.settings, start, self)
        dialog.exec()
        self.refresh(keep_selection=True)

    def open_history(self) -> None:
        HistoryDialog(self.storage, self.settings, self).exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self, storage=self.storage)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.apply_theme()
            self.refresh(keep_selection=True)

    def _icon(self):
        return make_icon(self.colors["accent"], self.colors["bg"], theme.is_pixel())

    def apply_theme(self) -> None:
        """Перекрашивает приложение после смены темы или стиля в настройках."""
        name = self.settings.get("theme", "dark")
        theme.set_style(self.settings.get("ui_style", theme.STYLE_SOFT))
        self.colors = theme.palette(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(name, theme.current_style()))
        icon = self._icon()
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        # Виджеты, которые красятся кодом, а не таблицей стилей.
        for widget in list(self.chips.values()) + list(self.nav_items.values()):
            widget.colors = self.colors

    # --- Напоминания ----------------------------------------------------------

    def _on_eod_due(self) -> None:
        self._notify(
            "Конец рабочего дня",
            "Отметьте, по каким задачам сегодня была работа. Нажмите, чтобы заполнить отчёт.",
        )
        self._pending_action = self.open_daily

    def _on_weekly_due(self, start: date) -> None:
        self._notify(
            "Недельный отчёт готов к сборке",
            "Собрал, что вы делали на этой неделе, и отметил задачи без Jira.",
        )
        QTimer.singleShot(1200, lambda: self.open_weekly(start))

    def _on_missed_report(self, day: date) -> None:
        self._notify(
            "Вчерашний отчёт не заполнен",
            "За %s отчёта нет. Заполнить сейчас?" % fmt_date(day),
        )
        self._pending_action = lambda: self.open_daily(day)

    def _on_starts_soon(self, tasks: list[Task]) -> None:
        """Плановые задачи на подходе: сначала уведомление, потом окно со списком."""
        if not tasks:
            return
        first = tasks[0]
        self._notify(
            "Скоро в работу: %d %s"
            % (len(tasks), "задача" if len(tasks) == 1 else "задачи"),
            "%s — %s" % (first.title, start_text(first)),
        )
        self._pending_action = lambda: self.show_upcoming(tasks)
        if self.isVisible():
            QTimer.singleShot(1500, lambda: self.show_upcoming(tasks))

    def show_upcoming(self, tasks: list[Task]) -> None:
        self._pending_action = None
        fresh = [t for t in (self.storage.get_task(t.id) for t in tasks) if t is not None]
        if not fresh:
            return
        dialog = UpcomingTasksDialog(fresh, self.settings, self)
        if dialog.exec() == UpcomingTasksDialog.OPEN_LIST:
            self.set_filter("planned")

    def _notify(self, title: str, message: str) -> None:
        if self.tray.isSystemTrayAvailable() and self.tray.supportsMessages():
            self.tray.showMessage(title, message, self.windowIcon(), 15000)
        else:
            self._restore()
            QMessageBox.information(self, title, message)

    def _tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore()

    def _restore(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        action = getattr(self, "_pending_action", None)
        if action is not None:
            self._pending_action = None
            QTimer.singleShot(150, action)

    # --- Окно -----------------------------------------------------------------

    def _quit(self) -> None:
        self._force_quit = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self._force_quit and self.settings.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "TaskManager работает в трее",
                "Программа продолжит следить за задачами и напомнит про отчёт.",
                self.windowIcon(),
                4000,
            )
            return
        self.settings.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.settings.save()
        self.scheduler.stop()
        self.tray.hide()
        event.accept()
