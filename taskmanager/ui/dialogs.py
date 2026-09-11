"""Диалоги: карточка задачи, отметка о работе, отчёт за день."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QGridLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import products as products_module
from ..config import Settings
from .. import recurrence
from ..horizons import start_text
from ..integrations import jira
from ..models import (
    JIRA_CREATED,
    JIRA_NOT_NEEDED,
    JIRA_STATE_LABELS,
    JIRA_UNKNOWN,
    PRIORITY_LABELS,
    STATUS_ACTIVE,
    STATUS_DONE,
    Task,
)
from ..reports import fmt_date_long
from ..storage import Storage
from . import theme
from .widgets import (
    CheckCircle,
    PriorityBars,
    ProductPill,
    SubtaskList,
    manage_window,
    hline,
    section_label,
)


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class LogWorkDialog(QDialog):
    """Короткая заметка о том, что сделано по задаче."""

    def __init__(self, task: Task, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Отметить работу")
        self.setMinimumWidth(380)
        self.resize(480, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        layout.addWidget(section_label("задача"))
        title = QLabel(task.title)
        title.setWordWrap(True)
        title.setFont(theme.ui_font(11, bold=True))
        layout.addWidget(title)

        layout.addWidget(section_label("что сделано"))
        self.comment = QPlainTextEdit()
        self.comment.setPlaceholderText("Например: собрал выгрузку, отдал на проверку")
        self.comment.setMinimumHeight(64)
        self.comment.setMaximumHeight(120)
        layout.addWidget(self.comment)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = _button("Отмена", "flat")
        cancel.clicked.connect(self.reject)
        save = _button("Записать", "accent")
        save.clicked.connect(self.accept)
        save.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.comment.setFocus()

    def text(self) -> str:
        return self.comment.toPlainText().strip()


class TaskDialog(QDialog):
    """Карточка задачи: поля, привязка к Jira и история работы."""

    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        task: Task | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.task = task or Task()
        self.colors = theme.palette(settings.get("theme", "dark"))
        self.is_new = task is None
        self.setWindowTitle("Новая задача" if self.is_new else "Задача")
        self._build()
        self._load()
        manage_window(self, settings, "task", 620, 720)

    def _build(self) -> None:
        # Содержимое карточки живёт в прокручиваемой области: на невысоком
        # экране окно можно сжать, а кнопки внизу останутся на месте.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(area, 1)

        content = QWidget()
        area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 20, 22, 12)
        layout.setSpacing(14)

        layout.addWidget(section_label("название"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Что нужно сделать")
        self.title_edit.setFont(theme.ui_font(11))
        layout.addWidget(self.title_edit)

        row = QHBoxLayout()
        row.setSpacing(14)
        layout.addLayout(row)

        priority_col = QVBoxLayout()
        priority_col.setSpacing(6)
        priority_col.addWidget(section_label("важность"))
        # Та же шкала, что и в списке: кликаем по полоске, а не выбираем из меню.
        bars_row = QHBoxLayout()
        bars_row.setSpacing(8)
        self.priority_bars = PriorityBars(self.task.priority, self.colors)
        self.priority_bars.picked.connect(self._pick_priority)
        bars_row.addWidget(self.priority_bars)
        self.priority_label = QLabel()
        self.priority_label.setProperty("faint", "true")
        bars_row.addWidget(self.priority_label, 1)
        priority_col.addLayout(bars_row)
        row.addLayout(priority_col, 1)

        due_col, self.due_check, self.due_edit = self._date_field("срок", "Задача со сроком")
        row.addLayout(due_col, 1)

        start_col, self.start_check, self.start_edit = self._date_field(
            "начало", "Плановая задача: работа начнётся с этой даты"
        )
        self.start_check.toggled.connect(self._sync_start_hint)
        self.start_edit.dateChanged.connect(self._sync_start_hint)
        row.addLayout(start_col, 1)

        self.start_hint = QLabel()
        self.start_hint.setProperty("faint", "true")
        self.start_hint.setFont(theme.mono_font(8))
        layout.addWidget(self.start_hint)

        row2 = QHBoxLayout()
        row2.setSpacing(14)
        layout.addLayout(row2)

        product_col = QVBoxLayout()
        product_col.setSpacing(6)
        product_col.addWidget(section_label("продукт"))
        self.product_box = QComboBox()
        product_col.addWidget(self.product_box)
        row2.addLayout(product_col, 1)

        repeat_col = QVBoxLayout()
        repeat_col.setSpacing(6)
        repeat_col.addWidget(section_label("повторять"))
        self.repeat_box = QComboBox()
        for value, title in (
            ("", "Не повторять"),
            ("daily", "Каждый день"),
            ("weekly", "Каждую неделю"),
            ("days:14", "Раз в две недели"),
            ("monthly", "Каждый месяц"),
        ):
            self.repeat_box.addItem(title, value)
        self.repeat_box.currentIndexChanged.connect(self._sync_repeat_hint)
        repeat_col.addWidget(self.repeat_box)
        row2.addLayout(repeat_col, 1)

        tags_col = QVBoxLayout()
        tags_col.setSpacing(6)
        tags_col.addWidget(section_label("теги"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("через запятую")
        tags_col.addWidget(self.tags_edit)
        row2.addLayout(tags_col, 2)

        self.repeat_hint = QLabel()
        self.repeat_hint.setProperty("faint", "true")
        self.repeat_hint.setFont(theme.mono_font(8))
        self.repeat_hint.setWordWrap(True)
        layout.addWidget(self.repeat_hint)

        suggest_row = QHBoxLayout()
        suggest_row.setSpacing(8)
        self.product_hint = QLabel()
        self.product_hint.setProperty("faint", "true")
        self.product_hint.setFont(theme.mono_font(8))
        suggest_row.addWidget(self.product_hint)
        self.product_apply = _button("Подставить", "flat")
        self.product_apply.clicked.connect(self._apply_suggestion)
        suggest_row.addWidget(self.product_apply)
        suggest_row.addStretch(1)
        layout.addLayout(suggest_row)
        self.title_edit.textChanged.connect(self._sync_product_hint)

        self.jira_line = hline()
        layout.addWidget(self.jira_line)

        self.jira_caption = section_label("jira")
        layout.addWidget(self.jira_caption)
        jira_row = QHBoxLayout()
        jira_row.setSpacing(8)
        self.jira_state_box = QComboBox()
        for state in (JIRA_UNKNOWN, JIRA_CREATED, JIRA_NOT_NEEDED):
            self.jira_state_box.addItem(JIRA_STATE_LABELS[state].capitalize(), state)
        self.jira_state_box.currentIndexChanged.connect(self._sync_jira_controls)
        jira_row.addWidget(self.jira_state_box)
        self.jira_edit = QLineEdit()
        self.jira_edit.setPlaceholderText("PROJ-142 или ссылка на задачу")
        self.jira_edit.setFont(theme.mono_font(9))
        jira_row.addWidget(self.jira_edit, 1)
        self.open_jira_button = _button("Открыть", "flat")
        self.open_jira_button.clicked.connect(self._open_jira)
        jira_row.addWidget(self.open_jira_button)
        self.jira_row_box = QWidget()
        self.jira_row_box.setLayout(jira_row)
        layout.addWidget(self.jira_row_box)

        self.jira_hint = QLabel()
        self.jira_hint.setProperty("faint", "true")
        self.jira_hint.setFont(theme.mono_font(8))
        layout.addWidget(self.jira_hint)

        layout.addWidget(section_label("заметки"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Детали, ссылки, договорённости")
        self.notes_edit.setMinimumHeight(70)
        self.notes_edit.setMaximumHeight(140)
        layout.addWidget(self.notes_edit)

        self.subtasks = SubtaskList(
            self.storage,
            theme.palette(self.settings.get("theme", "dark")),
            None if self.is_new else self.task.id,
            scroll_height=190,
        )
        layout.addWidget(self.subtasks)

        self.history_label = section_label("история работы")
        layout.addWidget(self.history_label)
        self.history = QListWidget()
        self.history.setMinimumHeight(80)
        self.history.setMaximumHeight(150)
        self.history.setFont(theme.mono_font(9))
        layout.addWidget(self.history)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(22, 10, 22, 16)
        self.done_button = _button("Выполнена", "flat")
        self.done_button.clicked.connect(self._toggle_done)
        buttons.addWidget(self.done_button)
        self.delete_button = _button("Удалить", "danger")
        self.delete_button.setProperty("flat", "true")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        cancel = _button("Отмена", "flat")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = _button("Сохранить", "accent")
        save.clicked.connect(self._save)
        save.setDefault(True)
        buttons.addWidget(save)
        outer.addLayout(buttons)

    def _date_field(self, caption: str, tooltip: str):
        """Колонка «галочка + дата»: дата задаётся, только если галочка стоит."""
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(section_label(caption))
        row = QHBoxLayout()
        row.setSpacing(6)
        check = QCheckBox()
        check.setToolTip(tooltip)
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setDate(QDate.currentDate())
        edit.setEnabled(False)
        check.toggled.connect(edit.setEnabled)
        row.addWidget(check)
        row.addWidget(edit, 1)
        column.addLayout(row)
        return column, check, edit

    # --- Данные ---------------------------------------------------------------

    def _fill_products(self) -> None:
        """Список продуктов из настроек плюс текущее значение задачи."""
        catalog = products_module.names(products_module.load(self.settings))
        current = self.task.product
        if current and current not in catalog:
            catalog.append(current)  # продукт убрали из справочника — не теряем метку
        self.product_box.clear()
        self.product_box.addItem("— не задан —", "")
        for name in catalog:
            self.product_box.addItem(name, name)
        index = self.product_box.findData(current)
        self.product_box.setCurrentIndex(index if index >= 0 else 0)

    def _suggestion(self) -> str:
        probe = Task(title=self.title_edit.text(), notes=self.notes_edit.toPlainText())
        return products_module.detect_for_task(probe, self.settings)

    def _sync_product_hint(self) -> None:
        """Показывает подсказку про угаданный продукт, пока он не выбран."""
        suggestion = self._suggestion()
        current = self.product_box.currentData() or ""
        show = bool(suggestion) and suggestion != current
        self.product_hint.setText(("Похоже на «%s»" % suggestion) if show else "")
        self.product_hint.setVisible(show)
        self.product_apply.setVisible(show)
        self._suggested = suggestion

    def _apply_suggestion(self) -> None:
        suggestion = getattr(self, "_suggested", "")
        if not suggestion:
            return
        index = self.product_box.findData(suggestion)
        if index < 0:
            self.product_box.addItem(suggestion, suggestion)
            index = self.product_box.findData(suggestion)
        self.product_box.setCurrentIndex(index)
        self._sync_product_hint()

    def _anchor_date(self):
        """Дата, от которой отсчитывается повторение: срок, иначе начало, иначе сегодня."""
        if self.due_check.isChecked():
            return self.due_edit.date().toPython()
        if self.start_check.isChecked():
            return self.start_edit.date().toPython()
        return date.today()

    def _repeat_rule(self) -> str:
        choice = self.repeat_box.currentData() or ""
        anchor = self._anchor_date()
        if choice == "weekly":
            return recurrence.make(recurrence.WEEKLY, anchor.weekday())
        if choice == "monthly":
            return recurrence.make(recurrence.MONTHLY, anchor.day)
        return choice

    def _sync_repeat_hint(self) -> None:
        text = recurrence.describe(self._repeat_rule())
        self.repeat_hint.setText(
            ("Повторяется %s. Следующая появится, когда отметите эту выполненной." % text)
            if text
            else ""
        )

    def _sync_start_hint(self) -> None:
        if not self.start_check.isChecked():
            self.start_hint.setText("")
            return
        probe = Task(start_date=self.start_edit.date().toPython())
        text = start_text(probe)
        self.start_hint.setText(
            ("Плановая задача: %s. Предупредим заранее." % text)
            if text
            else "Дата начала уже наступила — задача в общем списке."
        )

    def _pick_priority(self, level: int) -> None:
        """Выбор на шкале: в карточке подтверждение не нужно — есть «Сохранить»."""
        self.priority_bars.set_level(level)
        self.priority_label.setText(PRIORITY_LABELS.get(self.priority_bars.level, ""))

    def _load(self) -> None:
        task = self.task
        self.title_edit.setText(task.title)
        self._pick_priority(task.priority)
        self.due_check.setChecked(task.due_date is not None)
        self.due_edit.setEnabled(task.due_date is not None)
        if task.due_date:
            self.due_edit.setDate(QDate(task.due_date.year, task.due_date.month, task.due_date.day))
        self.start_check.setChecked(task.start_date is not None)
        self.start_edit.setEnabled(task.start_date is not None)
        if task.start_date:
            self.start_edit.setDate(
                QDate(task.start_date.year, task.start_date.month, task.start_date.day)
            )
        self._fill_products()
        kind, number = recurrence.parse(task.repeat)
        stored = task.repeat if kind == recurrence.EVERY_DAYS else kind
        index = self.repeat_box.findData(stored)
        self.repeat_box.setCurrentIndex(index if index >= 0 else 0)
        self.tags_edit.setText(", ".join(task.tags))
        self.jira_edit.setText(task.jira_key)
        index = self.jira_state_box.findData(task.jira_state)
        self.jira_state_box.setCurrentIndex(index if index >= 0 else 0)
        self.notes_edit.setPlainText(task.notes)
        self.done_button.setText("Вернуть в работу" if task.is_done else "Выполнена")
        self._sync_jira_controls()
        # Интеграция выключена — блок Jira просто не показываем.
        jira_on = bool(self.settings.get("jira.enabled", True))
        for widget in (self.jira_line, self.jira_caption, self.jira_row_box, self.jira_hint):
            widget.setVisible(jira_on)
        self._sync_start_hint()
        self._sync_repeat_hint()
        self._sync_product_hint()

        if self.is_new or task.id is None:
            self.history_label.hide()
            self.history.hide()
            self.delete_button.hide()
            self.done_button.hide()
        else:
            self._load_history()

    def _load_history(self) -> None:
        self.history.clear()
        logs = self.storage.logs_for_task(self.task.id)
        if not logs:
            item = QListWidgetItem("Отметок о работе пока нет")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history.addItem(item)
            return
        for log in logs:
            text = "%s  %s" % (log.log_date.strftime("%d.%m"), log.comment or "работа по задаче")
            self.history.addItem(QListWidgetItem(text))

    def _sync_jira_controls(self) -> None:
        state = self.jira_state_box.currentData()
        editable = state != JIRA_NOT_NEEDED
        self.jira_edit.setEnabled(editable)
        base = self.settings.get("jira.base_url", "")
        if state == JIRA_NOT_NEEDED:
            self.jira_hint.setText("Задача не требует issue — в напоминаниях не появится.")
        elif state == JIRA_UNKNOWN:
            self.jira_hint.setText("Попадёт в список «нужно завести в Jira» в недельном отчёте.")
        elif not base:
            self.jira_hint.setText("Укажите адрес Jira в настройках, чтобы работала кнопка «Открыть».")
        else:
            url = jira.issue_url(base, self.jira_edit.text())
            self.jira_hint.setText(url or "Введите ключ задачи.")

    def _open_jira(self) -> None:
        base = self.settings.get("jira.base_url", "")
        if not jira.open_issue(base, self.jira_edit.text()):
            QMessageBox.information(
                self,
                "Jira",
                "Не удалось собрать ссылку.\nПроверьте ключ задачи и адрес Jira в настройках.",
            )

    # --- Действия -------------------------------------------------------------

    def _collect(self) -> Task | None:
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.information(self, "Задача", "Введите название задачи.")
            self.title_edit.setFocus()
            return None
        task = self.task
        task.title = title
        task.priority = self.priority_bars.level
        task.due_date = self.due_edit.date().toPython() if self.due_check.isChecked() else None
        task.start_date = (
            self.start_edit.date().toPython() if self.start_check.isChecked() else None
        )
        task.product = self.product_box.currentData() or ""
        task.repeat = self._repeat_rule()
        task.tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        task.notes = self.notes_edit.toPlainText().strip()
        if not task.product:
            products_module.apply_to_task(task, self.settings)

        state = self.jira_state_box.currentData()
        key = jira.normalize_key(self.jira_edit.text()) if state != JIRA_NOT_NEEDED else ""
        if state == JIRA_CREATED and not key:
            QMessageBox.information(
                self, "Jira", "Для состояния «заведена» нужен ключ задачи, например PROJ-142."
            )
            self.jira_edit.setFocus()
            return None
        if key and not jira.is_valid_key(key):
            answer = QMessageBox.question(
                self,
                "Jira",
                "«%s» не похоже на ключ задачи (ожидается вид PROJ-142).\nВсё равно сохранить?" % key,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        task.jira_key = key
        task.jira_state = state
        return task

    def _save(self) -> None:
        task = self._collect()
        if task is None:
            return
        if self.is_new or task.id is None:
            self.task = self.storage.add_task(task)
            # Подпункты, набранные до сохранения, переносим в созданную задачу.
            self.subtasks.flush(self.task.id)
        else:
            self.storage.update_task(task)
        self.accept()

    def _toggle_done(self) -> None:
        task = self._collect()
        if task is None:
            return
        new_status = STATUS_ACTIVE if task.is_done else STATUS_DONE
        task.status = new_status
        task.done_at = None
        self.storage.update_task(task)
        if new_status == STATUS_DONE:
            self.storage.set_status(task.id, STATUS_DONE)
        self.accept()

    def _delete(self) -> None:
        answer = QMessageBox.question(
            self, "Удалить задачу", "Удалить «%s» вместе с историей работы?" % self.task.title
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.storage.delete_task(self.task.id)
            self.done(2)  # особый код: список нужно перечитать


class DailyReportDialog(QDialog):
    """Отчёт за день: отметки по задачам плюс свободный комментарий."""

    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        day: date | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.day = day or date.today()
        self.rows: list[tuple[int, QCheckBox, QLineEdit]] = []
        self.setWindowTitle("Отчёт за день")
        self._build()
        self._load()
        manage_window(self, settings, "daily", 700, 640)

    def _build(self) -> None:
        colors = theme.palette(self.settings.get("theme", "dark"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.header = QLabel()
        self.header.setFont(theme.ui_font(13, bold=True))
        head_row.addWidget(self.header)
        head_row.addStretch(1)
        self.today_button = _button("Сегодня", "flat")
        self.today_button.clicked.connect(lambda: self._set_day(date.today()))
        head_row.addWidget(self.today_button)
        self.prev_button = _button("←", "flat")
        self.prev_button.setToolTip("Предыдущий день")
        self.prev_button.clicked.connect(lambda: self._shift(-1))
        head_row.addWidget(self.prev_button)
        self.next_button = _button("→", "flat")
        self.next_button.setToolTip("Следующий день")
        self.next_button.clicked.connect(lambda: self._shift(1))
        head_row.addWidget(self.next_button)
        layout.addLayout(head_row)

        hint = QLabel("Отметьте задачи, по которым в этот день была работа, и коротко опишите что сделано.")
        hint.setProperty("dim", "true")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(hline())
        layout.addWidget(section_label("задачи"))

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        # Сетка, а не отдельные строки: так поля «что сделано» выстраиваются
        # в одну колонку независимо от длины названий и меток.
        self.rows_layout = QGridLayout(container)
        self.rows_layout.setContentsMargins(0, 0, 8, 0)
        self.rows_layout.setHorizontalSpacing(10)
        self.rows_layout.setVerticalSpacing(7)
        self.rows_layout.setColumnStretch(4, 1)
        self._row_count = 0
        area.setWidget(container)
        layout.addWidget(area, 1)

        layout.addWidget(section_label("свободный комментарий"))
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText(
            "Как прошёл день: встречи, помехи, договорённости, что осталось на завтра"
        )
        self.note_edit.setMinimumHeight(70)
        self.note_edit.setMaximumHeight(150)
        layout.addWidget(self.note_edit)

        self.status = QLabel("")
        self.status.setProperty("faint", "true")
        self.status.setFont(theme.mono_font(8))
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        copy_button = _button("Скопировать", "flat")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        self.export_button = _button("В Obsidian", "flat")
        self.export_button.clicked.connect(self._export)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        later = _button("Позже", "flat")
        later.clicked.connect(self.reject)
        buttons.addWidget(later)
        save = _button("Сохранить отчёт", "accent")
        save.clicked.connect(self._save)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.export_button.setEnabled(bool(self.settings.get("obsidian.vault_path", "")))
        self._colors = colors

    def _sync_header(self) -> None:
        self.header.setText("Отчёт за %s" % fmt_date_long(self.day))
        today = date.today()
        self.next_button.setEnabled(self.day < today)
        self.today_button.setVisible(self.day != today)
        self.status.setText(
            "" if self.day == today else "Вы заполняете прошедший день — записи уйдут в его отчёт."
        )

    def _shift(self, days: int) -> None:
        self._set_day(self.day + timedelta(days=days))

    def _set_day(self, day: date) -> None:
        """Переключает день. Уже введённое сохраняем, пустой день не трогаем."""
        if day == self.day or day > date.today():
            return
        if self._has_input():
            self._persist()
        self.day = day
        self._clear_rows()
        self._load()

    def _has_input(self) -> bool:
        if self.note_edit.toPlainText().strip():
            return True
        return any(check.isChecked() for _, check, _ in self.rows)

    def _clear_rows(self) -> None:
        self.rows = []
        self.rows_layout.setRowStretch(self._row_count, 0)
        self._row_count = 0
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _load(self) -> None:
        self._sync_header()
        existing = {log.task_id: log.comment for log in self.storage.logs_for_date(self.day)}
        report = self.storage.get_daily_report(self.day)
        self.note_edit.setPlainText(report.note if report else "")

        tasks = [
            t
            for t in self.storage.list_tasks(include_done=True)
            if not t.is_done and (t.start_date is None or t.start_date <= self.day)
        ]
        done_today = [
            t
            for t in self.storage.list_tasks(include_done=True)
            if t.is_done and t.done_at and t.done_at.date() == self.day
        ]
        tasks = done_today + tasks
        tasks.sort(key=lambda t: (t.id not in existing, -t.priority))

        if not tasks:
            empty = QLabel("Активных задач нет — опишите день в свободном комментарии.")
            empty.setProperty("faint", "true")
            self.rows_layout.addWidget(empty, 0, 0, 1, 5)
        for index, task in enumerate(tasks):
            self._task_row(task, existing, index)
        self._row_count = len(tasks)
        self.rows_layout.setRowStretch(self._row_count, 1)

    def _task_row(self, task: Task, existing: dict, row: int) -> None:
        c = self._colors
        grid = self.rows_layout
        top = Qt.AlignmentFlag.AlignTop

        check = CheckCircle(task.id in existing, c)
        grid.addWidget(check, row, 0, top)

        label = QLabel(task.title)
        label.setMinimumWidth(190)
        label.setMaximumWidth(280)
        label.setWordWrap(True)
        if task.is_done:
            label.setStyleSheet("color: %s;" % c["success"])
        grid.addWidget(label, row, 1, top)

        if task.product:
            pill = ProductPill(
                task.product,
                products_module.color_for(
                    products_module.load(self.settings), task.product, c["info"]
                ),
            )
            grid.addWidget(pill, row, 2, top)

        if task.jira_key and self.settings.get("jira.enabled", True):
            key = QLabel(task.jira_key)
            key.setFont(theme.mono_font(8))
            key.setStyleSheet("color: %s;" % c["info"])
            grid.addWidget(key, row, 3, top)

        comment = QLineEdit()
        comment.setPlaceholderText("что сделано")
        comment.setText(existing.get(task.id, ""))
        comment.textEdited.connect(lambda text, box=check: box.setChecked(True) if text else None)
        grid.addWidget(comment, row, 4)

        self.rows.append((task.id, check, comment))

    # --- Действия -------------------------------------------------------------

    def _persist(self) -> None:
        for log in self.storage.logs_for_date(self.day):
            if log.task_id is not None:
                self.storage.delete_work_log(log.id)
        for task_id, check, comment in self.rows:
            if check.isChecked():
                self.storage.add_work_log(task_id, comment.text().strip(), self.day)
        self.storage.save_daily_report(self.day, self.note_edit.toPlainText().strip())

    def _save(self) -> None:
        self._persist()
        self.accept()

    def _text(self) -> str:
        from ..reports import render_daily

        self._persist()
        report = self.storage.get_daily_report(self.day)
        if report is None:
            return ""
        return render_daily(
            report, self.storage, with_jira=bool(self.settings.get("jira.enabled", True))
        )

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self._text()
        QApplication.clipboard().setText(text)
        self.status.setText("Текст отчёта скопирован в буфер обмена")

    def _export(self) -> None:
        from pathlib import Path

        from ..reports import daily_filename, export_markdown

        vault = self.settings.get("obsidian.vault_path", "")
        if not vault:
            QMessageBox.information(
                self, "Obsidian", "Укажите путь к хранилищу Obsidian в настройках."
            )
            return
        target = Path(vault) / self.settings.get("obsidian.daily_subdir", "")
        try:
            path = export_markdown(self._text(), target, daily_filename(self.day))
        except OSError as exc:
            QMessageBox.warning(self, "Obsidian", "Не удалось записать файл:\n%s" % exc)
            return
        self.status.setText("Сохранено: %s" % path)


class UpcomingTasksDialog(QDialog):
    """Предупреждение о плановых задачах, которые вот-вот начнутся."""

    OPEN_LIST = 2  # особый код возврата: показать список плановых задач

    def __init__(self, tasks: list[Task], settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Скоро в работу")
        self.setMinimumWidth(420)

        colors = theme.palette(settings.get("theme", "dark"))
        catalog = products_module.load(settings)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        header = QLabel("Скоро начинаются плановые задачи")
        header.setFont(theme.ui_font(13, bold=True))
        layout.addWidget(header)

        hint = QLabel(
            "Работа по ним ещё не шла — самое время посмотреть, что нужно подготовить."
        )
        hint.setProperty("dim", "true")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(hline())

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        rows = QVBoxLayout(container)
        rows.setContentsMargins(0, 0, 8, 0)
        rows.setSpacing(10)
        area.setWidget(container)
        layout.addWidget(area, 1)

        for task in tasks:
            rows.addWidget(self._row(task, colors, catalog))
        rows.addStretch(1)
        self.resize(560, min(560, 250 + 44 * min(len(tasks), 5)))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = _button("Понятно", "flat")
        later.clicked.connect(self.accept)
        buttons.addWidget(later)
        open_list = _button("Показать плановые", "accent")
        open_list.clicked.connect(lambda: self.done(self.OPEN_LIST))
        open_list.setDefault(True)
        buttons.addWidget(open_list)
        layout.addLayout(buttons)

    def _row(self, task: Task, colors: dict, catalog: list) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        title = QLabel(task.title)
        title.setWordWrap(True)
        title.setFont(theme.ui_font(11, bold=True))
        layout.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        starts = QLabel("%s · %s" % (start_text(task), fmt_date_long(task.start_date)))
        starts.setFont(theme.mono_font(8))
        starts.setStyleSheet("color: %s;" % colors["accent"])
        meta.addWidget(starts)
        if task.product:
            meta.addWidget(
                ProductPill(
                    task.product,
                    products_module.color_for(catalog, task.product, colors["info"]),
                )
            )
        if task.due_date:
            due = QLabel("срок %s" % task.due_date.strftime("%d.%m.%Y"))
            due.setFont(theme.mono_font(8))
            due.setProperty("faint", "true")
            meta.addWidget(due)
        meta.addStretch(1)
        layout.addLayout(meta)
        return row
