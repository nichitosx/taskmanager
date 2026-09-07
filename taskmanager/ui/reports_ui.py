"""Диалоги отчётов: недельный отчёт и история отчётов по датам."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..integrations import jira
from ..integrations.confluence import ConfluenceClient, ConfluenceConfig, ConfluenceError
from ..models import JIRA_CREATED, JIRA_NOT_NEEDED, PRIORITY_LABELS
from ..reports import (
    GROUPING_BY_DAYS,
    GROUPING_BY_TASKS,
    GROUPING_LABELS,
    all_weeks_filename,
    collect_week,
    export_markdown,
    fmt_date,
    render_all_weeks,
    render_daily,
    render_weekly,
    week_bounds,
    weekly_filename,
)
from ..storage import Storage
from . import theme
from .widgets import hline, section_label


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class WeeklyReportDialog(QDialog):
    """Готовый отчёт за неделю плюс разбор задач без Jira."""

    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        start: date | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        if start is None:
            # В пятницу отчёт составляется по текущей неделе.
            start, _ = week_bounds()
        self.start = start
        self.end = start + timedelta(days=6)
        self.jira_enabled = bool(settings.get("jira.enabled", True))
        self.grouping = settings.get("weekly.grouping", GROUPING_BY_DAYS)
        if self.grouping not in GROUPING_LABELS:
            self.grouping = GROUPING_BY_DAYS
        self.colors = theme.palette(settings.get("theme", "dark"))
        self.setWindowTitle("Недельный отчёт")
        self.setMinimumSize(980, 700)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.header_label = QLabel()
        self.header_label.setFont(theme.ui_font(13, bold=True))
        header.addWidget(self.header_label)
        header.addStretch(1)
        prev_button = _button("← неделя назад", "flat")
        prev_button.clicked.connect(lambda: self._shift(-7))
        next_button = _button("неделя вперёд →", "flat")
        next_button.clicked.connect(lambda: self._shift(7))
        header.addWidget(prev_button)
        header.addWidget(next_button)
        layout.addLayout(header)
        layout.addWidget(hline())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 8, 12, 0)
        left_layout.setSpacing(8)
        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        head_row.addWidget(section_label("текст отчёта"))
        head_row.addStretch(1)
        head_row.addWidget(section_label("разрез"))
        self.grouping_buttons: dict[str, QPushButton] = {}
        for key in (GROUPING_BY_DAYS, GROUPING_BY_TASKS):
            button = _button(GROUPING_LABELS[key].capitalize(), "nav")
            button.clicked.connect(lambda _=False, k=key: self.set_grouping(k))
            self.grouping_buttons[key] = button
            head_row.addWidget(button)
        left_layout.addLayout(head_row)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(theme.mono_font(9))
        left_layout.addWidget(self.text_edit, 1)
        regenerate = _button("Пересобрать из данных", "flat")
        regenerate.clicked.connect(lambda: self.refresh(regenerate=True))
        left_layout.addWidget(regenerate, 0, Qt.AlignmentFlag.AlignLeft)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 8, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(section_label("нужно завести в jira"))
        self.jira_hint = QLabel()
        self.jira_hint.setProperty("dim", "true")
        self.jira_hint.setWordWrap(True)
        right_layout.addWidget(self.jira_hint)

        self.jira_area = QScrollArea()
        self.jira_area.setWidgetResizable(True)
        self.jira_area.setFrameShape(QFrame.Shape.NoFrame)
        right_layout.addWidget(self.jira_area, 1)
        splitter.addWidget(right)
        splitter.setSizes([620, 340])
        # Интеграция выключена — панель «нужно завести в Jira» не нужна.
        right.setVisible(self.jira_enabled)
        if not self.jira_enabled:
            splitter.setSizes([960, 0])

        self.status = QLabel("")
        self.status.setProperty("faint", "true")
        self.status.setFont(theme.mono_font(8))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        copy_button = _button("Скопировать")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        self.obsidian_button = _button("В Obsidian")
        self.obsidian_button.clicked.connect(self._export_obsidian)
        buttons.addWidget(self.obsidian_button)
        self.confluence_button = _button("В Confluence")
        self.confluence_button.clicked.connect(self._publish_confluence)
        buttons.addWidget(self.confluence_button)
        all_weeks = _button("Все недели…", "flat")
        all_weeks.setToolTip("Выгрузка по задачам за все заполненные недели")
        all_weeks.clicked.connect(self._open_all_weeks)
        buttons.addWidget(all_weeks)
        buttons.addStretch(1)
        close_button = _button("Готово", "accent")
        close_button.clicked.connect(self._save_and_close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.obsidian_button.setEnabled(bool(self.settings.get("obsidian.vault_path", "")))
        config = ConfluenceConfig.from_settings(self.settings.get("confluence", {}) or {})
        cf_on = bool(self.settings.get("confluence.enabled", False)) and config.is_configured
        self.confluence_button.setVisible(cf_on)

    # --- Данные ---------------------------------------------------------------

    def _shift(self, days: int) -> None:
        self.start += timedelta(days=days)
        self.end = self.start + timedelta(days=6)
        self.refresh()

    def set_grouping(self, grouping: str) -> None:
        """Переключает разрез отчёта и запоминает выбор на будущее."""
        if grouping == self.grouping:
            return
        self.grouping = grouping
        self.settings.set("weekly.grouping", grouping)
        self.settings.save()
        self.refresh(regenerate=True)
        self.status.setText("Отчёт пересобран %s" % GROUPING_LABELS[grouping])

    def _sync_grouping_buttons(self) -> None:
        for key, button in self.grouping_buttons.items():
            button.setProperty("active", "true" if key == self.grouping else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def refresh(self, regenerate: bool = False) -> None:
        """Перечитывает отчёт. ``regenerate`` игнорирует ранее сохранённый текст."""
        self.header_label.setText(
            "Неделя %s — %s" % (fmt_date(self.start), fmt_date(self.end))
        )
        stale_days = self.settings.get_int("stale_days", 5)
        saved = None if regenerate else self.storage.get_weekly_report(self.start)
        text = saved or render_weekly(
            self.storage,
            self.start,
            self.end,
            stale_days,
            self.grouping,
            with_jira=self.jira_enabled,
        )
        self.text_edit.setPlainText(text)
        self._sync_grouping_buttons()
        self._fill_jira_list()

    def _fill_jira_list(self) -> None:
        if not self.jira_enabled:
            return
        data = collect_week(self.storage, self.start, self.end)
        tasks = data["jira_todo"]
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        if not tasks:
            self.jira_hint.setText(
                "По всем задачам недели вопрос с Jira закрыт. Ничего заводить не нужно."
            )
        else:
            self.jira_hint.setText(
                "По этим задачам была работа, но issue ещё не отмечена. "
                "Заведите её в Jira и укажите ключ — задача исчезнет из списка."
            )
            for task in tasks:
                layout.addWidget(self._jira_card(task))
        layout.addStretch(1)
        self.jira_area.setWidget(container)

    def _jira_card(self, task) -> QWidget:
        c = self.colors
        card = QFrame()
        card.setObjectName("jiraCard")
        card.setStyleSheet(
            "#jiraCard { background: %s; border: 1px solid %s; border-radius: 8px; }"
            % (c["surface"], c["border_soft"])
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        title = QLabel(task.title)
        title.setWordWrap(True)
        title.setFont(theme.ui_font(10, bold=True))
        title.setStyleSheet("background: transparent;")
        layout.addWidget(title)

        meta_parts = [PRIORITY_LABELS.get(task.priority, "обычный")]
        if task.due_date:
            meta_parts.append("срок %s" % fmt_date(task.due_date))
        meta = QLabel(" · ".join(meta_parts))
        meta.setFont(theme.mono_font(8))
        meta.setStyleSheet("color: %s; background: transparent;" % c["text_faint"])
        layout.addWidget(meta)

        row = QHBoxLayout()
        row.setSpacing(6)
        created = _button("Указать ключ", "flat")
        created.clicked.connect(lambda _=False, t=task: self._mark_created(t))
        row.addWidget(created)
        not_needed = _button("Не нужна", "flat")
        not_needed.clicked.connect(lambda _=False, t=task: self._mark_not_needed(t))
        row.addWidget(not_needed)
        base = self.settings.get("jira.base_url", "")
        if base:
            open_jira = _button("Создать в Jira", "flat")
            open_jira.clicked.connect(lambda _=False: self._open_create_form())
            row.addWidget(open_jira)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _mark_created(self, task) -> None:
        key, ok = QInputDialog.getText(
            self, "Ключ Jira", "Ключ задачи для «%s»:" % task.title, text=task.jira_key
        )
        if not ok:
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
        self.refresh()

    def _mark_not_needed(self, task) -> None:
        task.jira_state = JIRA_NOT_NEEDED
        task.jira_key = ""
        self.storage.update_task(task, touch_activity=False)
        self.refresh()

    def _open_create_form(self) -> None:
        import webbrowser

        url = jira.create_issue_url(self.settings.get("jira.base_url", ""))
        if url:
            webbrowser.open(url)

    def _open_all_weeks(self) -> None:
        AllWeeksDialog(self.storage, self.settings, self.grouping, self).exec()

    # --- Выгрузка -------------------------------------------------------------

    def _content(self) -> str:
        return self.text_edit.toPlainText()

    def _save_and_close(self) -> None:
        self.storage.save_weekly_report(self.start, self._content())
        self.storage.set_meta("last_weekly_report", self.start.isoformat())
        self.accept()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._content())
        self.status.setText("Отчёт скопирован в буфер обмена")

    def _export_obsidian(self) -> None:
        vault = self.settings.get("obsidian.vault_path", "")
        if not vault:
            QMessageBox.information(self, "Obsidian", "Укажите путь к хранилищу в настройках.")
            return
        target = Path(vault) / self.settings.get("obsidian.weekly_subdir", "")
        try:
            path = export_markdown(
                self._content(), target, weekly_filename(self.start, self.end)
            )
        except OSError as exc:
            QMessageBox.warning(self, "Obsidian", "Не удалось записать файл:\n%s" % exc)
            return
        self.status.setText("Сохранено: %s" % path)

    def _publish_confluence(self) -> None:
        config = ConfluenceConfig.from_settings(self.settings.get("confluence", {}) or {})
        title = "Отчёт за неделю %s — %s" % (fmt_date(self.start), fmt_date(self.end))
        answer = QMessageBox.question(
            self,
            "Confluence",
            "Опубликовать страницу «%s» в пространстве %s?\n"
            "Если страница с таким названием уже есть, она будет обновлена."
            % (title, config.space_key),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.status.setText("Публикую в Confluence…")
        QApplication.processEvents()
        try:
            url = ConfluenceClient(config).publish(title, self._content())
        except ConfluenceError as exc:
            self.status.setText("")
            QMessageBox.warning(self, "Confluence", str(exc))
            return
        self.status.setText("Опубликовано: %s" % url)


class HistoryDialog(QDialog):
    """Просмотр сохранённых отчётов по датам."""

    def __init__(self, storage: Storage, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.setWindowTitle("История отчётов")
        self.setMinimumSize(860, 600)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(section_label("что показывать"))
        self.kind_box = QComboBox()
        self.kind_box.addItem("Отчёты за день", "daily")
        self.kind_box.addItem("Недельные отчёты", "weekly")
        self.kind_box.currentIndexChanged.connect(self._load)
        top.addWidget(self.kind_box)
        top.addStretch(1)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self.list = QListWidget()
        self.list.setFont(theme.mono_font(9))
        self.list.currentItemChanged.connect(self._show)
        splitter.addWidget(self.list)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(theme.mono_font(9))
        splitter.addWidget(self.view)
        splitter.setSizes([250, 610])

        buttons = QHBoxLayout()
        copy_button = _button("Скопировать")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.view.toPlainText())
        )
        buttons.addWidget(copy_button)
        all_weeks = _button("Выгрузить все недели")
        all_weeks.clicked.connect(
            lambda: AllWeeksDialog(
                self.storage,
                self.settings,
                self.settings.get("weekly.grouping", GROUPING_BY_TASKS),
                self,
            ).exec()
        )
        buttons.addWidget(all_weeks)
        buttons.addStretch(1)
        close_button = _button("Закрыть", "accent")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _load(self) -> None:
        self.list.clear()
        self.view.clear()
        kind = self.kind_box.currentData()
        if kind == "daily":
            for day in self.storage.report_dates():
                item = QListWidgetItem(fmt_date(day))
                item.setData(Qt.ItemDataRole.UserRole, day)
                self.list.addItem(item)
        else:
            # Только недели, за которые что-то заполнено: пустые показывать незачем.
            for start in self.storage.weeks_with_activity():
                item = QListWidgetItem(
                    "%s — %s" % (fmt_date(start), fmt_date(start + timedelta(days=6)))
                )
                item.setData(Qt.ItemDataRole.UserRole, start)
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.view.setPlainText(
                "Пока ничего не заполнено — отметьте работу по задачам или "
                "сохраните отчёт за день."
            )

    def _show(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        value = current.data(Qt.ItemDataRole.UserRole)
        if self.kind_box.currentData() == "daily":
            report = self.storage.get_daily_report(value)
            self.view.setPlainText(render_daily(report, self.storage) if report else "")
        else:
            content = self.storage.get_weekly_report(value)
            if not content:
                content = render_weekly(
                    self.storage,
                    value,
                    value + timedelta(days=6),
                    self.settings.get_int("stale_days", 5),
                    self.settings.get("weekly.grouping", GROUPING_BY_DAYS),
                    with_jira=bool(self.settings.get("jira.enabled", True)),
                )
            self.view.setPlainText(content)


class AllWeeksDialog(QDialog):
    """Одна выгрузка по всем неделям, за которые что-то заполнено."""

    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        grouping: str = GROUPING_BY_TASKS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.grouping = grouping if grouping in GROUPING_LABELS else GROUPING_BY_TASKS
        self.weeks = sorted(storage.weeks_with_activity())
        self.setWindowTitle("Выгрузка по неделям")
        self.setMinimumSize(900, 680)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        self.header = QLabel()
        self.header.setFont(theme.ui_font(13, bold=True))
        layout.addWidget(self.header)

        hint = QLabel(
            "Собрано по всем неделям, где есть отметки о работе или комментарии. "
            "Пустые недели пропущены."
        )
        hint.setProperty("dim", "true")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        head_row.addWidget(section_label("текст выгрузки"))
        head_row.addStretch(1)
        head_row.addWidget(section_label("разрез"))
        self.grouping_buttons: dict[str, QPushButton] = {}
        for key in (GROUPING_BY_TASKS, GROUPING_BY_DAYS):
            button = _button(GROUPING_LABELS[key].capitalize(), "nav")
            button.clicked.connect(lambda _=False, k=key: self.set_grouping(k))
            self.grouping_buttons[key] = button
            head_row.addWidget(button)
        layout.addLayout(head_row)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(theme.mono_font(9))
        layout.addWidget(self.text_edit, 1)

        self.status = QLabel("")
        self.status.setProperty("faint", "true")
        self.status.setFont(theme.mono_font(8))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        copy_button = _button("Скопировать")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        self.obsidian_button = _button("В Obsidian")
        self.obsidian_button.clicked.connect(self._export_obsidian)
        self.obsidian_button.setEnabled(bool(self.settings.get("obsidian.vault_path", "")))
        buttons.addWidget(self.obsidian_button)
        save_button = _button("Сохранить в файл")
        save_button.clicked.connect(self._save_file)
        buttons.addWidget(save_button)
        buttons.addStretch(1)
        close_button = _button("Закрыть", "accent")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    # --- Данные ---------------------------------------------------------------

    def set_grouping(self, grouping: str) -> None:
        if grouping == self.grouping:
            return
        self.grouping = grouping
        self.refresh()

    def refresh(self) -> None:
        if self.weeks:
            self.header.setText(
                "Недель с данными: %d  ·  %s — %s"
                % (
                    len(self.weeks),
                    fmt_date(self.weeks[0]),
                    fmt_date(self.weeks[-1] + timedelta(days=6)),
                )
            )
        else:
            self.header.setText("Заполненных недель пока нет")
        self.text_edit.setPlainText(
            render_all_weeks(
                self.storage, self.grouping, self.settings.get_int("stale_days", 5)
            )
        )
        for key, button in self.grouping_buttons.items():
            button.setProperty("active", "true" if key == self.grouping else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _period(self) -> tuple[date, date]:
        if not self.weeks:
            today = date.today()
            return today, today
        return self.weeks[0], self.weeks[-1] + timedelta(days=6)

    def _filename(self) -> str:
        start, end = self._period()
        return all_weeks_filename(start, end)

    # --- Выгрузка -------------------------------------------------------------

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        self.status.setText("Выгрузка скопирована в буфер обмена")

    def _export_obsidian(self) -> None:
        vault = self.settings.get("obsidian.vault_path", "")
        if not vault:
            QMessageBox.information(self, "Obsidian", "Укажите путь к хранилищу в настройках.")
            return
        target = Path(vault) / self.settings.get("obsidian.weekly_subdir", "")
        try:
            path = export_markdown(self.text_edit.toPlainText(), target, self._filename())
        except OSError as exc:
            QMessageBox.warning(self, "Obsidian", "Не удалось записать файл:\n%s" % exc)
            return
        self.status.setText("Сохранено: %s" % path)

    def _save_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить выгрузку", self._filename(), "Markdown (*.md);;Все файлы (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.text_edit.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Сохранение", "Не удалось записать файл:\n%s" % exc)
            return
        self.status.setText("Сохранено: %s" % path)
