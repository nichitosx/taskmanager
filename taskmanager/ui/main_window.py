"""Главное окно: быстрый ввод, список задач, панель деталей, трей."""

from __future__ import annotations

import os
from datetime import date, datetime

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QInputDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QScrollArea,
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
from .. import updates as updates_module
from .. import products as products_module
from .. import quickadd
from .. import recurrence
from ..appicon import make_icon, make_watermark
from ..config import Settings
from ..horizons import (
    HORIZON_HINTS,
    HORIZON_LABELS,
    default_due,
    in_horizon,
    sort_tasks,
    start_text,
)
from ..integrations import jira
from ..integrations.jira import JiraClient, JiraConfig, JiraError
from ..models import (
    JIRA_CREATED,
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
from .calendar_view import CalendarDialog
from .dialogs import DailyReportDialog, LogWorkDialog, TaskDialog, UpcomingTasksDialog
from .reports_ui import HistoryDialog, WeeklyReportDialog
from .settings_dialog import SettingsDialog
from .widgets import (
    Card,
    DayIndicator,
    fit_to_screen,
    move_onto_screen,
    HintTrigger,
    SubtaskList,
    elide_text,
    headline,
    JiraIssueRow,
    NavItem,
    TaskRow,
    hline,
    section_label,
)

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

# Списки задач, прочитанных прямо из Jira: живут отдельно от локальных задач.
JIRA_PLAN = "jira_plan"        # то, что ещё предстоит
JIRA_ACTIVE = "jira_active"    # то, что уже в работе

JIRA_VIEWS = {
    JIRA_ACTIVE: "Из Jira: в работе",
    JIRA_PLAN: "Из Jira: планы",
}

# Сколько держим ответ Jira, прежде чем спрашивать снова.
JIRA_CACHE_SECONDS = 300


class JiraFetch(QThread):
    """Запрос к Jira в отдельном потоке, чтобы окно не подвисало."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JiraConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config

    def run(self) -> None:  # noqa: D102 (Qt naming)
        try:
            client = JiraClient(self.config)
            # Один вход, два запроса: списки собираются разными фильтрами.
            self.done.emit({
                JIRA_ACTIVE: client.search(self.config.jql_active),
                JIRA_PLAN: client.search(self.config.jql),
            })
        except JiraError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # неожиданная ошибка не должна ронять приложение
            self.failed.emit("Не удалось прочитать задачи из Jira: %s" % exc)


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

        colors = theme.palette(self.settings.get("theme", "dark"))
        self.placeholder = QWidget()
        self.placeholder.setStyleSheet("background: transparent;")
        hint_layout = QVBoxLayout(self.placeholder)
        hint_layout.setContentsMargins(0, 30, 0, 0)
        hint_layout.setSpacing(14)

        art = QLabel()
        art.setPixmap(make_watermark(96, colors["text_faint"], 34))
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setStyleSheet("background: transparent;")
        hint_layout.addWidget(art)

        text = QLabel(
            theme.multiline(
                "Выберите задачу слева.\n\nДвойной клик открывает карточку,\n"
                "правая кнопка — быстрые действия."
            )
        )
        text.setProperty("faint", "true")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        hint_layout.addWidget(text)
        hint_layout.addStretch(1)
        layout.addWidget(self.placeholder, 1)

        # Содержимое панели прокручивается целиком: у задачи может быть длинный
        # чек-лист, и раньше он выдавливал историю работы.
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.body_scroll.setStyleSheet("background: transparent;")
        layout.addWidget(self.body_scroll, 1)

        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 10, 0)
        body_layout.setSpacing(10)
        self.body_scroll.setWidget(self.body)

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

        self.subtasks = SubtaskList(
            self.storage,
            theme.palette(self.settings.get("theme", "dark")),
            compact=True,
        )
        self.subtasks.changed.connect(self._subtasks_changed)
        body_layout.addWidget(self.subtasks)

        body_layout.addWidget(section_label("история работы"))
        self.history = QListWidget()
        self.history.setFont(theme.mono_font(9))
        self.history.setFixedHeight(120)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.TextElideMode.ElideRight)
        body_layout.addWidget(self.history)

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
        body_layout.addStretch(1)

        self.body_scroll.hide()

    # --- Отображение ----------------------------------------------------------

    def show_task(self, task: Task | None) -> None:
        self.task = task
        if task is None:
            self.body_scroll.hide()
            self.placeholder.show()
            return
        self.placeholder.hide()
        self.body_scroll.show()

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

        self.subtasks.set_task(task.id)

        self.history.clear()
        logs = self.storage.logs_for_task(task.id)
        if not logs:
            self.history.addItem("Отметок пока нет")
        for log in logs:
            self.history.addItem(
                "%s  %s" % (log.log_date.strftime("%d.%m"), log.comment or "работа по задаче")
            )

        jira_on = bool(self.settings.get("jira.enabled", True))
        self.jira_button.setVisible(jira_on)
        self.jira_button.setEnabled(bool(task.jira_key))
        self.no_jira_button.setVisible(jira_on and task.jira_state != JIRA_NOT_NEEDED)

    def _subtasks_changed(self) -> None:
        """Отметили подпункт — обновляем счётчик в списке слева."""
        if self.owner is not None:
            self.owner.refresh(keep_selection=True)

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
        self._jira_issues: dict[str, list] = {JIRA_ACTIVE: [], JIRA_PLAN: []}
        self._jira_error = ""
        self._jira_loaded_at = None
        self._jira_thread: JiraFetch | None = None
        self._shown_filter = ""
        theme.set_style(settings.get("ui_style", theme.STYLE_SOFT))
        theme.set_preferred_pixel(settings.get("pixel_font", ""))
        self.colors = theme.palette(settings.get("theme", "dark"))
        self._force_quit = False

        self.setWindowTitle("TaskManager")
        self.setWindowIcon(self._icon())
        # Размер подбирается под экран: на ноутбуке окно не должно вылезать
        # за край, иначе часть интерфейса недостижима.
        fit_to_screen(self, 1180, 760)

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
        self._start_clock()
        self.refresh()
        # Проверку откладываем: пусть окно сначала появится.
        QTimer.singleShot(4000, self._check_updates)

    # --- Интерфейс ------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("canvas")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())
        root.addWidget(headline())

        body = QWidget()
        body.setObjectName("bodyArea")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(0)
        root.addWidget(body, 1)

        body_layout.addWidget(self._sidebar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        body_layout.addWidget(splitter, 1)

        center = QWidget()
        center.setObjectName("centerArea")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 0, 4, 0)
        center_layout.setSpacing(12)
        splitter.addWidget(center)

        self.update_bar = self._update_bar()
        center_layout.addWidget(self.update_bar)

        self.demo_bar = self._demo_bar()
        center_layout.addWidget(self.demo_bar)

        self.quick_add = QLineEdit()
        # Подсказки по синтаксису живут в шпаргалке слева, здесь только суть.
        self.quick_add.setPlaceholderText("Новая задача — нажмите Enter, чтобы добавить")
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

        self.empty_box = QWidget()
        self.empty_box.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self.empty_box)
        empty_layout.setContentsMargins(0, 40, 0, 0)
        empty_layout.setSpacing(16)
        empty_layout.addStretch(1)

        self.empty_art = QLabel()
        self.empty_art.setPixmap(make_watermark(112, self.colors["text_faint"], 40))
        self.empty_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_art.setStyleSheet("background: transparent;")
        empty_layout.addWidget(self.empty_art)

        self.empty_label = QLabel()
        self.empty_label.setProperty("faint", "true")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addStretch(2)

        self.empty_box.hide()
        center_layout.addWidget(self.empty_box, 1)

        self.detail = TaskDetail(self.storage, self.settings, self)
        self.detail.setObjectName("detailPanel")
        # Пиксельный шрифт шире, поэтому панели деталей нужно больше места.
        detail_width = 430 if theme.is_pixel() else 360
        self.detail.setMinimumWidth(detail_width)
        splitter.addWidget(self.detail)
        splitter.setSizes([700, detail_width])
        splitter.setCollapsible(0, False)

    def _update_bar(self) -> QWidget:
        """Полоса «вышла новая версия» с кнопкой обновления."""
        c = self.colors
        bar = Card(c)
        bar.set_card_colors(
            bg=theme.tint(c["accent"], 0.12), border=theme.tint(c["accent"], 0.34)
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(13, 8, 10, 8)
        layout.setSpacing(10)

        self.update_label = QLabel()
        self.update_label.setWordWrap(True)
        self.update_label.setStyleSheet("color: %s; background: transparent;" % c["text"])
        layout.addWidget(self.update_label, 1)

        install = QPushButton("Обновить")
        install.setProperty("accent", "true")
        install.setCursor(Qt.CursorShape.PointingHandCursor)
        install.clicked.connect(self._start_update)
        layout.addWidget(install)

        later = QPushButton("Позже")
        later.setProperty("flat", "true")
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.clicked.connect(bar.hide)
        layout.addWidget(later)

        bar.hide()
        return bar

    def _check_updates(self) -> None:
        """Раз в сутки тихо смотрит, не вышла ли новая версия."""
        if not self.settings.get("updates.check_on_start", True):
            return
        if not updates_module.due_today(self.settings):
            return
        updates_module.mark_checked(self.settings)
        self._update_check = updates_module.UpdateCheck(self)
        self._update_check.found.connect(self._on_update_found)
        self._update_check.start()

    def _on_update_found(self, description: str) -> None:
        self.update_label.setText(
            "Вышла новая версия (%s). Задачи и настройки при обновлении сохранятся."
            % description
        )
        self.update_bar.show()

    def _start_update(self) -> None:
        """Запускает обновление отдельным окном — оно само закроет программу."""
        from ..config import app_dir

        command = app_dir() / "Обновить.cmd"
        if not command.exists():
            QMessageBox.information(
                self, "Обновление", "Файл «Обновить.cmd» не найден рядом с программой."
            )
            return
        try:
            os.startfile(str(command))  # noqa: S606 (штатный запуск в отдельном окне)
        except OSError as exc:
            QMessageBox.warning(self, "Обновление", "Не удалось запустить: %s" % exc)
            return
        self.update_bar.hide()
        self.statusBar().showMessage(
            "Обновление идёт в отдельном окне — программа закроется и запустится заново.",
            8000,
        )

    def _demo_bar(self) -> QWidget:
        """Полоса-подсказка про задачи-примеры с кнопкой «убрать»."""
        c = self.colors
        bar = Card(c)
        bar.set_card_colors(c["surface_alt"], theme.tint(c["info"], 0.45), c["surface_alt"])
        bar.set_bar(c["info"])
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
        header.setObjectName("appHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 14, 20, 10)
        layout.setSpacing(22)

        logo = QLabel("TASKMANAGER")
        logo.setFont(theme.accent_font(12, bold=True, spacing=2.5))
        logo.setStyleSheet("color: %s;" % c["text"])
        layout.addWidget(logo)

        dot = QLabel("•")
        dot.setStyleSheet("color: %s; font-size: 18px;" % c["accent"])
        layout.addWidget(dot)

        # Счётчики по спискам показывает боковая панель, состояние дня —
        # индикатор справа; в шапке остаются только действия.
        layout.addStretch(1)

        self.day_indicator = DayIndicator(c)
        self.day_indicator.clicked.connect(self.open_daily)
        layout.addWidget(self.day_indicator)
        layout.addSpacing(18)

        daily = QPushButton("Отчёт за день")
        daily.setProperty("flat", "true")
        daily.clicked.connect(self.open_daily)
        layout.addWidget(daily)

        calendar_button = QPushButton("Календарь")
        calendar_button.setProperty("flat", "true")
        calendar_button.clicked.connect(self.open_calendar)
        layout.addWidget(calendar_button)

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
        panel.setObjectName("sidebarPanel")
        panel.setFixedWidth(216)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(theme.nav_spacing())
        self.nav_items: dict[str, NavItem] = {}

        layout.addWidget(section_label("когда"))
        layout.addSpacing(2)
        for key, title in HORIZON_FILTERS:
            layout.addWidget(self._nav_item(key, title, HORIZON_HINTS.get(key, "")))
        layout.addWidget(
            self._nav_item(
                JIRA_ACTIVE,
                JIRA_VIEWS[JIRA_ACTIVE],
                "Задачи из Jira, которые уже в работе (фильтр в настройках)",
            )
        )
        layout.addWidget(
            self._nav_item(
                JIRA_PLAN,
                JIRA_VIEWS[JIRA_PLAN],
                "Задачи из Jira, которые ещё предстоят (фильтр в настройках)",
            )
        )

        layout.addSpacing(theme.section_gap())
        layout.addWidget(section_label("состояние"))
        layout.addSpacing(2)
        for key, title in STATE_FILTERS:
            layout.addWidget(self._nav_item(key, title))

        # Продуктов может быть много, поэтому раздел сворачивается и прокручивается.
        layout.addSpacing(theme.section_gap())
        self.products_header = QWidget()
        self.products_header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_row = QHBoxLayout(self.products_header)
        header_row.setContentsMargins(0, 0, 4, 0)
        header_row.setSpacing(6)
        self.products_caption = section_label("продукты")
        header_row.addWidget(self.products_caption)
        header_row.addStretch(1)
        self.products_arrow = QLabel()
        self.products_arrow.setFont(theme.mono_font(8))
        self.products_arrow.setProperty("faint", "true")
        header_row.addWidget(self.products_arrow)
        self.products_header.mousePressEvent = (  # type: ignore[assignment]
            lambda _event: self._toggle_products()
        )
        self.products_header.hide()
        layout.addWidget(self.products_header)

        self.products_scroll = QScrollArea()
        self.products_scroll.setObjectName("productsScroll")
        self.products_scroll.setWidgetResizable(True)
        self.products_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.products_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.products_scroll.setMaximumHeight(190)
        self.products_box = QWidget()
        self.products_box.setObjectName("productsBox")
        self.products_layout = QVBoxLayout(self.products_box)
        self.products_layout.setContentsMargins(0, 2, 0, 0)
        self.products_layout.setSpacing(3)
        self.products_scroll.setWidget(self.products_box)
        self.products_scroll.hide()
        layout.addWidget(self.products_scroll)

        layout.addStretch(1)

        self.plans_box = self._plans_box()
        layout.addWidget(self.plans_box)

        # Шпаргалка занимает одну строку: подробности всплывают при наведении.
        layout.addSpacing(6)
        self.hint_trigger = HintTrigger(self.colors)
        layout.addWidget(self.hint_trigger)
        return panel

    def _plans_box(self) -> QWidget:
        """Минималистичное окошко: что и через сколько дней начнётся."""
        c = self.colors
        box = Card(c)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.setToolTip("Открыть список плановых задач")
        box.mousePressEvent = lambda _event: self.set_filter("planned")  # type: ignore[assignment]

        layout = QVBoxLayout(box)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(6)
        layout.addWidget(section_label("ближайшие планы"))

        self.plans_lines = QVBoxLayout()
        self.plans_lines.setContentsMargins(0, 0, 0, 0)
        self.plans_lines.setSpacing(5)
        layout.addLayout(self.plans_lines)
        box.hide()
        return box

    def _sync_plans_box(self, tasks: list[Task]) -> None:
        """Показывает ближайшие плановые задачи: название и через сколько дней."""
        c = self.colors
        while self.plans_lines.count():
            item = self.plans_lines.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        planned = sorted(
            (t for t in tasks if t.is_planned), key=lambda t: (t.start_date, -t.priority)
        )
        self.plans_box.setVisible(bool(planned))
        if not planned:
            return

        for task in planned[:4]:
            line = QWidget()
            # Без этого строка красится общим фоном окна и на подложке окошка
            # получаются тёмные полосы.
            line.setStyleSheet("background: transparent;")
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            days = task.days_to_start or 0
            left = QLabel("%d дн." % days if days > 1 else "завтра")
            left.setFont(theme.accent_font(8))

            title = QLabel(task.title)
            title.setFont(theme.ui_font(9))
            title.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
            # Сколько места осталось под название: ширина панели минус отступы
            # окошка и место под «через сколько дней».
            available = (
                self.plans_box.parentWidget().width() or 216
            ) - 24 - 10 - left.fontMetrics().horizontalAdvance(left.text())
            title.setText(
                elide_text(title.fontMetrics(), task.title, max(70, available))
            )
            title.setToolTip(task.title)
            row.addWidget(title)
            row.addStretch(1)
            left.setStyleSheet("color: %s; background: transparent;" % c["accent"])
            row.addWidget(left)
            self.plans_lines.addWidget(line)

        if len(planned) > 4:
            more = QLabel("и ещё %d" % (len(planned) - 4))
            more.setFont(theme.mono_font(8))
            more.setStyleSheet("color: %s; background: transparent;" % c["text_faint"])
            self.plans_lines.addWidget(more)

    def _toggle_products(self) -> None:
        opened = not bool(self.settings.get("sidebar.products_open", True))
        self.settings.set("sidebar.products_open", opened)
        self.settings.save()
        self.refresh(keep_selection=True)

    def _nav_item(self, key: str, title: str, tooltip: str = "") -> NavItem:
        item = NavItem(title, self.colors, self.colors["accent"])
        if tooltip:
            item.setToolTip(tooltip)
        item.clicked.connect(lambda k=key: self.set_filter(k))
        self.nav_items[key] = item
        return item

    def _jira_config(self) -> JiraConfig:
        return JiraConfig.from_settings(
            self.settings.get("jira", {}) or {},
            self.settings.get("network.ca_file", ""),
        )

    def _jira_ready(self) -> bool:
        config = self._jira_config()
        return bool(self.settings.get("jira.enabled", True)) and config.is_configured

    def _jira_fresh(self) -> bool:
        if self._jira_loaded_at is None:
            return False
        return (datetime.now() - self._jira_loaded_at).total_seconds() < JIRA_CACHE_SECONDS

    def load_jira(self, force: bool = False) -> None:
        """Спрашивает Jira в фоне. Свежий ответ переиспользуется."""
        if not self._jira_ready():
            return
        if self._jira_thread is not None and self._jira_thread.isRunning():
            return
        if self._jira_fresh() and not force:
            return
        self._jira_error = ""
        thread = JiraFetch(self._jira_config(), self)
        thread.done.connect(self._on_jira_done)
        thread.failed.connect(self._on_jira_failed)
        self._jira_thread = thread
        thread.start()
        if self.filter in JIRA_VIEWS:
            self.refresh(keep_selection=False)

    def _on_jira_done(self, issues: dict) -> None:
        self._jira_issues = {
            JIRA_ACTIVE: list(issues.get(JIRA_ACTIVE, [])),
            JIRA_PLAN: list(issues.get(JIRA_PLAN, [])),
        }
        self._jira_error = ""
        self._jira_loaded_at = datetime.now()
        if self.filter in JIRA_VIEWS:
            self.refresh(keep_selection=False)

    def _on_jira_failed(self, message: str) -> None:
        self._jira_error = message
        self._jira_loaded_at = datetime.now()
        if self.filter in JIRA_VIEWS:
            self.refresh(keep_selection=False)

    def _fill_jira_plan(self) -> None:
        """Показывает список задач из Jira вместо локальных."""
        self.rows = {}
        self.list.clear()
        loading = self._jira_thread is not None and self._jira_thread.isRunning()
        issues = self._jira_issues.get(self.filter, [])

        if not self._jira_ready():
            self._show_empty(
                "Чтобы видеть задачи из Jira, включите интеграцию и заполните адрес, "
                "e-mail и API-токен в настройках."
            )
            return
        if loading and not issues:
            self._show_empty("Спрашиваю Jira…")
            return
        if self._jira_error:
            self._show_empty(self._jira_error)
            return
        if not issues:
            self._show_empty(
                "Под фильтр «%s» в Jira не попала ни одна задача."
                % JIRA_VIEWS.get(self.filter, "")
            )
            return

        self.empty_box.hide()
        self.list.show()
        for issue in issues:
            already = self.storage.find_by_jira_key(issue.key) is not None
            row = JiraIssueRow(issue, self.colors, already)
            row.activated.connect(
                lambda key: jira.open_issue(self.settings.get("jira.base_url", ""), key)
            )
            row.take.connect(self._take_jira_issue)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, self._row_height(row)))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

        self.filter_label.setText(
            "%s: %d%s"
            % (
                JIRA_VIEWS.get(self.filter, "из jira").lower(),
                len(issues),
                " · обновляю…" if loading else "",
            )
        )

    def _show_empty(self, text: str) -> None:
        self.empty_label.setText(text)
        self.empty_box.show()
        self.list.hide()

    def _take_jira_issue(self, key: str) -> None:
        """Заводит локальную задачу по issue из Jira."""
        every = self._jira_issues.get(JIRA_ACTIVE, []) + self._jira_issues.get(JIRA_PLAN, [])
        issue = next((i for i in every if i.key == key), None)
        if issue is None:
            return
        task = Task(title=issue.summary or issue.key, jira_key=issue.key)
        task.jira_state = JIRA_CREATED
        task.due_date = issue.due_date
        task.notes = "Из Jira: %s" % (issue.url or issue.key)
        products_module.apply_to_task(task, self.settings)
        created = self.storage.add_task(task)
        self.selected_id = created.id
        self.statusBar().showMessage("Задача %s добавлена к вам в список" % issue.key, 3000)
        self.refresh(keep_selection=False)

    def _sync_products_nav(self, tasks: list[Task]) -> None:
        """Пересобирает список продуктов: сначала те, где есть активные задачи."""
        catalog = products_module.load(self.settings)
        known = products_module.names(catalog)
        # Показываем и продукты из справочника, и те, что уже стоят у задач.
        for name in self.storage.products_in_use():
            if name not in known:
                known.append(name)

        counts = {}
        for name in known:
            counts[name] = sum(1 for t in tasks if t.product.lower() == name.lower())
        known.sort(key=lambda name: (-counts[name], name.lower()))

        for key in [k for k in self.nav_items if k.startswith(PRODUCT_PREFIX)]:
            self.nav_items.pop(key).deleteLater()
        while self.products_layout.count():
            item = self.products_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        opened = bool(self.settings.get("sidebar.products_open", True))
        self.products_header.setVisible(bool(known))
        self.products_scroll.setVisible(bool(known) and opened)
        self.products_caption.setText(
            "продукты · %d" % len(known) if len(known) > 6 else "продукты"
        )
        self.products_arrow.setText("▾" if opened else "▸")
        if not known:
            return

        for name in known:
            key = PRODUCT_PREFIX + name
            item = NavItem(name, self.colors, products_module.color_for(catalog, name))
            item.setToolTip(name)
            item.clicked.connect(lambda k=key: self.set_filter(k))
            self.nav_items[key] = item
            self.products_layout.addWidget(item)
        self.products_layout.addStretch(1)

        # Список длинный — прокрутка; короткий — показываем целиком.
        rows = min(len(known), 6)
        row_height = self.nav_items[PRODUCT_PREFIX + known[0]].sizeHint().height()
        self.products_scroll.setMaximumHeight(
            rows * (row_height + theme.nav_spacing()) + 6
        )

    def _build_tray(self) -> None:
        # На некоторых машинах области уведомлений нет вовсе; тогда прятать окно
        # в трей нельзя — программа просто исчезнет без следа.
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
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
        if self.tray_available:
            self.tray.show()

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.quick_add.setFocus)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.open_daily)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=lambda: self.open_weekly())
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_calendar)
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
            chosen = [t for t in tasks if t.product.lower() == name]
        elif self.filter in HORIZON_LABELS:
            chosen = [t for t in tasks if in_horizon(t, self.filter)]
        elif self.filter == "overdue":
            chosen = [t for t in tasks if t.is_overdue]
        elif self.filter == "stale":
            chosen = [t for t in tasks if t.is_stale(stale_days)]
        elif self.filter == "jira":
            chosen = [t for t in tasks if t.needs_jira()]
        else:
            chosen = tasks
        # Порядок один на все списки: важность, затем срочность.
        return sort_tasks(chosen)

    def refresh(self, keep_selection: bool = True) -> None:
        previous = self.selected_id if keep_selection else None
        stale_days = self.settings.get_int("stale_days", 5)

        if self.filter in JIRA_VIEWS and not self.search.text().strip():
            self._refresh_chrome(stale_days)
            self._fill_jira_plan()
            self.detail.show_task(None)
            return

        self.list.clear()
        self.rows: dict[int, TaskRow] = {}
        tasks = self.visible_tasks()
        catalog = products_module.load(self.settings)

        show_jira = bool(self.settings.get("jira.enabled", True))
        progress = self.storage.subtask_progress_map()
        # Плановые задачи идут в конце списка, за чертой: работать по ним ещё рано.
        current = [t for t in tasks if not t.is_planned]
        upcoming = [t for t in tasks if t.is_planned]
        ordered = current + upcoming
        separator_before = current[-1].id if current and upcoming else None

        for task in ordered:
            color = products_module.color_for(catalog, task.product, self.colors["info"])
            row = TaskRow(
                task, self.colors, stale_days, color, show_jira, progress.get(task.id, (0, 0))
            )
            row.toggled.connect(self._toggle_task)
            row.activated.connect(self.open_task)
            row.clicked.connect(self._select_task)
            row.jira_requested.connect(self._ask_jira_key)
            row.product_requested.connect(self._ask_product)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, self._row_height(row)))
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.rows[task.id] = row
            if separator_before is not None and task.id == separator_before:
                self._add_planned_separator(len(upcoming))

        self.empty_box.setVisible(not tasks)
        self.list.setVisible(bool(tasks))
        self.empty_label.setText(self._empty_text())
        if tasks:
            self._fade_list()

        self._refresh_chrome(stale_days)

        self.filter_label.setText(
            ("найдено: %d" % len(tasks))
            if self.search.text().strip()
            else "%s: %d" % (self._filter_title().lower(), len(tasks))
        )

        if previous is not None and previous in self.rows:
            self._select_task(previous)
        elif previous is not None:
            task = self.storage.get_task(previous)
            self.detail.show_task(task)
        else:
            self.detail.show_task(None)

    def _refresh_chrome(self, stale_days: int) -> None:
        """Обновляет шапку, боковое меню и окошко планов."""
        counters = self.storage.counters(stale_days)
        self._sync_day_indicator(counters)

        searching = bool(self.search.text().strip())
        jira_on = bool(self.settings.get("jira.enabled", True))
        if "jira" in self.nav_items:
            self.nav_items["jira"].setVisible(jira_on)
        if not jira_on and self.filter == "jira":
            self.filter = "active"
        self.demo_bar.setVisible(bool(demo.remaining_ids(self.storage)))

        active_tasks = self.storage.list_tasks(include_done=False)
        self._sync_products_nav(active_tasks)
        self._sync_plans_box(active_tasks)
        for key in JIRA_VIEWS:
            if key in self.nav_items:
                self.nav_items[key].setVisible(self._jira_ready())
        for key, item in self.nav_items.items():
            item.set_active(key == self.filter and not searching)
            item.set_count(self._nav_count(key, active_tasks, stale_days, counters))

        self._update_tray_tooltip(counters)

    def _filter_title(self) -> str:
        if self.filter.startswith(PRODUCT_PREFIX):
            return self.filter[len(PRODUCT_PREFIX):]
        if self.filter in JIRA_VIEWS:
            return JIRA_VIEWS[self.filter]
        return dict(FILTERS).get(self.filter, "")

    def _nav_count(
        self, key: str, tasks: list[Task], stale_days: int, counters: dict[str, int]
    ) -> int:
        """Счётчик рядом с пунктом меню — по тем же правилам, что и сам список."""
        if key.startswith(PRODUCT_PREFIX):
            name = key[len(PRODUCT_PREFIX):].lower()
            return sum(1 for t in tasks if t.product.lower() == name)
        if key in JIRA_VIEWS:
            return len(self._jira_issues.get(key, []))
        if key == "done":
            return 0  # выполненных много, число тут только мешает
        return counters.get(key, 0)

    def _fade_list(self) -> None:
        """Мягкое появление списка при переходе в другой раздел.

        Только при смене раздела: мигать на каждом обновлении (отметил галочку,
        напечатал букву в поиске) было бы навязчиво.
        """
        current = self.filter + ("?" + self.search.text().strip() if self.search.text() else "")
        if current == self._shown_filter:
            return
        self._shown_filter = current

        effect = QGraphicsOpacityEffect(self.list)
        self.list.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(160)
        animation.setStartValue(0.25)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Эффект снимаем: с ним список рисуется через промежуточный буфер.
        animation.finished.connect(lambda: self.list.setGraphicsEffect(None))
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._list_animation = animation

    def _row_height(self, row) -> int:
        """Высота строки с учётом переноса меток на вторую строку."""
        width = max(320, self.list.viewport().width() - 4)
        height = row.heightForWidth(width) if row.hasHeightForWidth() else -1
        if height <= 0:
            height = row.sizeHint().height()
        return height + 4

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """При изменении ширины пересчитываем высоты строк — но не на каждый пиксель."""
        super().resizeEvent(event)
        timer = getattr(self, "_resize_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.refresh(keep_selection=True))
            self._resize_timer = timer
        timer.start(180)

    def _add_planned_separator(self, count: int) -> None:
        """Черта «плановые» между актуальными и будущими задачами."""
        c = self.colors
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(2, 8, 2, 4)
        layout.setSpacing(9)

        caption = section_label("плановые · %d" % count)
        layout.addWidget(caption)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: %s;" % c["border_soft"])
        layout.addWidget(line, 1)

        item = QListWidgetItem()
        # В пиксельном стиле строки выше — черта тоже должна занять больше места.
        item.setSizeHint(QSize(0, 30 + theme.line_extra() * 2))
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)
        self.list.setItemWidget(item, holder)

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

    def _sync_day_indicator(self, counters: dict[str, int]) -> None:
        """Сколько задач сегодня уже отмечено и заполнен ли отчёт."""
        today = date.today()
        logs = self.storage.logs_for_date(today)
        done = len({log.task_id for log in logs if log.task_id is not None})
        # За «план на день» считаем задачи со сроком на сегодня и раньше.
        total = max(counters.get("today", 0), done)
        self.day_indicator.set_clock(datetime.now())
        self.day_indicator.set_day(done, total, self.storage.has_saved_report(today))

    def _start_clock(self) -> None:
        """Часы в шапке: раз в полминуты обновляем только текст, без перечитывания."""
        self._clock = QTimer(self)
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(lambda: self.day_indicator.set_clock(datetime.now()))
        self._clock.start()

    def _update_tray_tooltip(self, counters: dict[str, int]) -> None:
        self.tray.setToolTip(
            "TaskManager — в работе: %d, просрочено: %d, ждут Jira: %d"
            % (counters["active"], counters["overdue"], counters["jira"])
        )

    # --- Действия со списком --------------------------------------------------

    def set_filter(self, key: str) -> None:
        # Повторный клик по тому же списку — принудительное обновление из Jira.
        force = key in JIRA_VIEWS and self.filter == key
        self.filter = key
        self.search.clear()
        if key in JIRA_VIEWS:
            self.load_jira(force=force)
        self.refresh(keep_selection=False)

    def _quick_add(self) -> None:
        text = self.quick_add.text().strip()
        if not text:
            return
        task = quickadd.parse(text)
        # Срок из выбранного списка, если в самой строке его не указали.
        if task.due_date is None and task.start_date is None:
            task.due_date = default_due(self.filter)
        products_module.apply_to_task(task, self.settings)
        created = self.storage.add_task(task)
        self.quick_add.clear()
        # Остаёмся в текущем списке, только если новая задача в нём видна.
        if all(t.id != created.id for t in self.visible_tasks()):
            self.filter = "planned" if created.is_planned else "active"
        self.selected_id = created.id
        self.refresh()

        parts = ["Добавлено: %s" % created.title]
        if created.due_date and quickadd.parse(text).due_date is None:
            parts.append("срок %s — по списку «%s»"
                         % (fmt_date(created.due_date), self._filter_title()))
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
        task = self.storage.get_task(task_id)
        if done and task is not None and not self._confirm_done(task):
            self._reset_check(task_id)
            return
        self.storage.set_status(task_id, STATUS_DONE if done else STATUS_ACTIVE)
        if done and task is not None:
            self._spawn_next_occurrence(task)
        QTimer.singleShot(120, lambda: self.refresh(keep_selection=True))

    def done_dialog(self, task: Task) -> QMessageBox:
        """Собирает окно подтверждения (отдельно от показа — так его видно тестам)."""
        text = "Отметить «%s» выполненной?" % task.title
        following = recurrence.next_occurrence(task)
        if following is not None:
            when = following.due_date or following.start_date
            text += "\n\nЗадача повторяется: следующая появится на %s." % (
                fmt_date(when) if when else "ближайшую дату"
            )

        box = QMessageBox(self)
        box.setWindowTitle("Выполнено")
        box.setText(text)
        # Системная иконка вопроса синяя и выбивается из палитры — обходимся текстом.
        box.setIcon(QMessageBox.Icon.NoIcon)
        yes = box.addButton("Выполнена", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        # Ссылку на галочку держим сами: без неё PySide отдаёт из checkBox()
        # безымянный QObject, у которого уже нет isChecked().
        box.skip_checkbox = QCheckBox("Больше не спрашивать")
        box.setCheckBox(box.skip_checkbox)
        return box

    def _confirm_done(self, task: Task) -> bool:
        """Спрашивает подтверждение перед отметкой «выполнено»."""
        if not self.settings.get("confirm_done", True):
            return True
        box = self.done_dialog(task)
        box.exec()
        if box.skip_checkbox.isChecked():
            self.settings.set("confirm_done", False)
            self.settings.save()
        # Сравниваем по роли кнопки, а не по объекту: обёртки Qt для одной и той
        # же кнопки могут не совпадать. Закрытие крестиком — тоже отказ.
        clicked = box.clickedButton()
        return (
            clicked is not None
            and box.buttonRole(clicked) == QMessageBox.ButtonRole.AcceptRole
        )

    def _reset_check(self, task_id: int) -> None:
        """Возвращает отметку в списке обратно, если выполнение не подтвердили."""
        row = self.rows.get(task_id)
        if row is not None:
            row.check.set_checked_silently(False)

    def _spawn_next_occurrence(self, task: Task) -> None:
        """Для повторяющейся задачи заводит следующий раз с новыми датами."""
        following = recurrence.next_occurrence(task)
        if following is None:
            return
        created = self.storage.add_task(following)
        when = created.due_date or created.start_date
        self.statusBar().showMessage(
            "Следующая: «%s» — %s" % (created.title, fmt_date(when) if when else "без даты"),
            4000,
        )

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
        self._add_product_menu(menu, task)
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

    def _ask_jira_key(self, task_id: int) -> None:
        """Клик по метке «jira?»: вписать ключ, не открывая карточку."""
        task = self.storage.get_task(task_id)
        if task is None:
            return
        menu = QMenu(self)
        menu.addAction("Указать ключ…", lambda: self._enter_jira_key(task))
        menu.addAction("Jira не нужна", lambda: self._set_no_jira(task))
        base = self.settings.get("jira.base_url", "")
        if base:
            menu.addAction("Создать задачу в Jira", self._open_jira_form)
        menu.exec(QCursor.pos())

    def _enter_jira_key(self, task: Task) -> None:
        key, accepted = QInputDialog.getText(
            self, "Ключ Jira", "Ключ задачи для «%s»:" % task.title, text=task.jira_key
        )
        if not accepted:
            return
        key = jira.normalize_key(key)
        if not key:
            return
        if not jira.is_valid_key(key):
            answer = QMessageBox.question(
                self, "Jira", "«%s» не похоже на ключ. Всё равно сохранить?" % key
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        task.jira_key = key
        task.jira_state = JIRA_CREATED
        self.storage.update_task(task, touch_activity=False)
        self.refresh(keep_selection=True)
        self.statusBar().showMessage("Задаче присвоен ключ %s" % key, 3000)

    def _open_jira_form(self) -> None:
        import webbrowser

        url = jira.create_issue_url(self.settings.get("jira.base_url", ""))
        if url:
            webbrowser.open(url)

    def _add_product_menu(self, menu: QMenu, task: Task) -> None:
        """Подменю «Продукт» в контекстном меню задачи."""
        catalog = products_module.load(self.settings)
        names = products_module.names(catalog)
        for name in self.storage.products_in_use():
            if name not in names:
                names.append(name)
        if not names:
            return

        submenu = menu.addMenu("Продукт")
        for name in names:
            action = submenu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == task.product)
            action.triggered.connect(lambda _=False, n=name: self._set_product(task, n))
        if task.product:
            submenu.addSeparator()
            submenu.addAction("Убрать", lambda: self._set_product(task, ""))

    def _ask_product(self, task_id: int) -> None:
        """Клик по метке продукта: выбрать продукт из справочника."""
        task = self.storage.get_task(task_id)
        if task is None:
            return
        catalog = products_module.load(self.settings)
        names = products_module.names(catalog)
        for name in self.storage.products_in_use():
            if name not in names:
                names.append(name)

        menu = QMenu(self)
        if not names:
            menu.addAction("Продукты не заведены — «Настройки → Продукты»").setEnabled(False)
        for name in names:
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == task.product)
            action.triggered.connect(lambda _=False, n=name: self._set_product(task, n))
        if task.product:
            menu.addSeparator()
            menu.addAction("Убрать продукт", lambda: self._set_product(task, ""))
        menu.exec(QCursor.pos())

    def _set_product(self, task: Task, name: str) -> None:
        task.product = name
        self.storage.update_task(task, touch_activity=False)
        self.refresh(keep_selection=True)
        self.statusBar().showMessage(
            ("Продукт: %s" % name) if name else "Продукт убран", 2500
        )

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

    def open_calendar(self) -> None:
        """Месяц целиком: где какие сроки."""
        dialog = CalendarDialog(self.storage, self.settings, self)
        dialog.open_task.connect(self.open_task)
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
        theme.set_preferred_pixel(self.settings.get("pixel_font", ""))
        self.colors = theme.palette(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(name, theme.current_style()))
        icon = self._icon()
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        # Виджеты, которые красятся кодом, а не таблицей стилей.
        for widget in self.nav_items.values():
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
        if (
            not self._force_quit
            and self.settings.get("minimize_to_tray", True)
            and getattr(self, "tray_available", True)
        ):
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
