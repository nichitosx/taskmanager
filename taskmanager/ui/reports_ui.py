"""Диалоги отчётов: недельный отчёт и история отчётов по датам."""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QThread, Signal
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..integrations import jira
from ..integrations.jira import JiraClient, JiraConfig, JiraError
from ..integrations.confluence import (
    ConfluenceClient,
    ConfluenceConfig,
    ConfluenceError,
    _first_column_spans,
    markdown_to_storage,
)
from ..models import JIRA_CREATED, JIRA_NOT_NEEDED, PRIORITY_LABELS
from ..reports import (
    GROUPING_BY_DAYS,
    GROUPING_BY_TASKS,
    GROUPING_LABELS,
    GROUPING_TABLE,
    all_weeks_filename,
    collect_week,
    export_markdown,
    fmt_date,
    render_all_weeks,
    render_daily,
    render_weekly,
    to_plain,
    JiraFacts,
    WeekRule,
    week_bounds,
    weekly_filename,
)
from ..storage import Storage
from . import theme
from .terminal import (
    LeaderRow,
    TitledPanel,
    cell_width,
    glyph_label,
    link_button,
)
from .widgets import GridText, clear_background, manage_window, hline, section_label


TABLE_HEADER = ["Статус", "Задача", "Тема", "Результат за неделю"]


def week_table_html(markdown: str, colors: dict) -> str:
    """Таблица отчёта для экрана: та же, что уйдёт в Confluence.

    Статус группы — одна высокая клетка на все её строки, как и после
    вставки; ключ и тема — ссылками на Jira.
    """
    rows = []
    for line in markdown.splitlines():
        text = line.strip()
        if not text.startswith("|") or set(text) <= set("|-: "):
            continue
        rows.append([cell.strip() for cell in text.strip("|").split("|")])
    if rows and rows[0] and rows[0][0] == TABLE_HEADER[0]:
        header = rows.pop(0)
    else:
        header = TABLE_HEADER
    if not rows:
        return '<p style="color: %s">за неделю ничего не отмечено</p>' % colors["text_dim"]

    def inline(text: str) -> str:
        text = html.escape(text.replace("**", ""))
        return re.sub(
            r"\[(.+?)\]\((.+?)\)",
            r'<a href="\2" style="color: %s; text-decoration: none">\1</a>' % colors["text"],
            text,
        )

    # Статус и ключ — по ширине их слов, чтобы ключ не рвался на две строки.
    cell = cell_width()
    widths = [str(cell * 12), str(cell * 10), "32%", ""]
    style = 'style="color: %s; border-color: %s"'
    parts = [
        '<table width="100%%" cellspacing="0" cellpadding="6" border="1" '
        'style="border-collapse: collapse; border-color: %s; border-style: solid">'
        % colors["dim"],
        "<tr>",
    ]
    for index, caption in enumerate(header):
        width = ' width="%s"' % widths[index] if index < len(widths) and widths[index] else ""
        parts.append('<th align="left"%s %s><span style="font-weight: 400">%s</span></th>'
                     % (width, style % (colors["text_dim"], colors["dim"]), html.escape(caption)))
    parts.append("</tr>")

    spans = _first_column_spans(rows, 0)
    quiet = ("выполнено", "за неделю ничего не отмечено")
    for number, row in enumerate(rows):
        parts.append("<tr>")
        for column, value in enumerate(row):
            if column == 0:
                if number not in spans:
                    continue
                ink = colors["bright"] if value.lower().startswith("выполн") else colors["text"]
                parts.append('<td rowspan="%d" valign="top" %s>%s</td>'
                             % (spans[number], style % (ink, colors["dim"]), inline(value)))
                continue
            ink = colors["text"]
            text = inline(value)
            if column == 1 and not value:
                ink, text = colors["faint"], "\u00b7" * 8
            elif value.lower() in quiet:
                ink = colors["text_dim"]
            parts.append('<td valign="top" %s>%s</td>' % (style % (ink, colors["dim"]), text))
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def week_chart_lines(counts: list[int], days: list[date], colors: dict) -> list:
    """Отметки по дням недели: столбик в три клетки на день, подписи снизу."""
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    rows = 5
    top = max(counts) if counts else 0
    scale = max(top, 1)
    today = date.today()
    lines = []
    for row in range(rows, 0, -1):
        if row == rows and top:
            label = str(top)
        elif row == 3 and top > 1:
            label = str((top + 1) // 2)
        else:
            label = ""
        text = ("%2s \u2524" % label) if label else "   \u2502"
        inks = [colors["text_dim"]] * len(text)
        for index, value in enumerate(counts):
            height = value / scale * rows * 2
            if height >= 2 * row:
                block = "\u2588" * 3
            elif height >= 2 * row - 1:
                block = "\u2584" * 3
            else:
                block = "   "
            day = days[index]
            ink = colors["bright"] if day == today else (
                colors["text_dim"] if day.weekday() >= 5 else colors["text"])
            text += " " + block + " "
            inks += [ink] * 5
        lines.append((text, inks))
    lines.append((" 0 \u253c" + "\u2500" * (5 * len(counts)), colors["text_dim"]))
    axis = "    " + "".join(" %s  " % names[day.weekday()] for day in days)
    inks = [colors["text_dim"]] * len(axis)
    for index, day in enumerate(days):
        if day == today:
            for shift in range(5):
                inks[4 + index * 5 + shift] = colors["bright"]
    lines.append((axis, inks))
    return lines


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def copy_report(markdown: str) -> None:
    """Кладёт отчёт в буфер дважды: разметкой и готовым HTML.

    Confluence, Word и почта берут из буфера HTML, если он там есть, — тогда
    таблица вставляется таблицей, а не строчками с чёрточками. Редакторы
    простого текста возьмут разметку.
    """
    mime = QMimeData()
    mime.setText(markdown)
    mime.setHtml("<html><body>%s</body></html>" % markdown_to_storage(markdown))
    QApplication.clipboard().setMimeData(mime)


class JiraDoneFetch(QThread):
    """Спрашивает Jira, что было закрыто за неделю. Фоном, чтобы окно не вставало."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JiraConfig, since, until, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        # Не start/end: у QThread уже есть метод start, и поле бы его перекрыло.
        self.since = since
        self.until = until

    def run(self) -> None:  # noqa: D102 (Qt naming)
        try:
            client = JiraClient(self.config)
            # Спрашиваем и закрытое за неделю, и то, что в Jira ещё в работе:
            # в отчёт идёт и первое, и второе, просто разными разделами.
            self.done.emit({
                "done": client.search_done(self.since, self.until),
                "active": client.search(self.config.jql_active),
            })
        except JiraError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # неожиданная ошибка не должна ронять окно
            self.failed.emit("Не удалось спросить Jira: %s" % exc)


def _rows_word(count: int) -> str:
    """«строка», «строки» или «строк» — число рядом с ними живое."""
    tail, hundred = count % 10, count % 100
    if tail == 1 and hundred != 11:
        return "строка"
    if tail in (2, 3, 4) and hundred not in (12, 13, 14):
        return "строки"
    return "строк"


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
        self.jira_base = settings.get("jira.base_url", "") if self.jira_enabled else ""
        self.content = ""
        self.editing = False
        # Что Jira рассказала про эту неделю: названия задач и чем их закрыли.
        self.facts = JiraFacts()
        self.jira_note = ""
        self._jira_thread: JiraDoneFetch | None = None
        self.grouping = settings.get("weekly.grouping", GROUPING_BY_DAYS)
        if self.grouping not in GROUPING_LABELS:
            self.grouping = GROUPING_BY_DAYS
        self.colors = theme.palette(settings.get("theme", theme.DEFAULT_THEME))
        self.setWindowTitle("Недельный отчёт")
        self._build()
        self.refresh()
        self.load_jira_done()
        manage_window(self, settings, "weekly", 1360, 860)

    def _build(self) -> None:
        c = self.colors
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.px(18), theme.px(14), theme.px(18), theme.px(14))
        self.panel = TitledPanel("Отчёт за неделю", c)
        outer.addWidget(self.panel)
        layout = self.panel.box
        layout.setSpacing(theme.px(12))

        # Листание недель — на правом краю рамки.
        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(theme.px(6), 0, theme.px(6), 0)
        corner_row.setSpacing(theme.px(4))
        self.prev_button = link_button(
            "\u25c4 назад", "Предыдущая неделя, за которую что-то заполнено"
        )
        self.prev_button.clicked.connect(lambda: self._step(-1))
        corner_row.addWidget(self.prev_button)
        corner_row.addWidget(glyph_label("\u2502", c["faint"]))
        self.next_button = link_button("вперёд \u25ba", "Следующая заполненная неделя")
        self.next_button.clicked.connect(lambda: self._step(1))
        corner_row.addWidget(self.next_button)
        self.panel.set_corner(corner)

        # Разрез: «по дням │ по задачам │ таблицей», выбранный — инверсией.
        head_row = QHBoxLayout()
        head_row.setSpacing(theme.px(6))
        head_row.addWidget(glyph_label("Разрез:", c["text_dim"]))
        self.grouping_buttons: dict[str, QPushButton] = {}
        for index, key in enumerate((GROUPING_BY_DAYS, GROUPING_BY_TASKS, GROUPING_TABLE)):
            if index:
                head_row.addWidget(glyph_label("\u2502", c["faint"]))
            button = link_button(
                GROUPING_LABELS[key],
                "Таблица «задача — что сделано», её удобно вставлять в Confluence"
                if key == GROUPING_TABLE else "",
            )
            button.clicked.connect(lambda _=False, k=key: self.set_grouping(k))
            self.grouping_buttons[key] = button
            head_row.addWidget(button)
        head_row.addStretch(1)
        # Редактор Confluence вставляет таблицу в таблицу «поверх»: сколько
        # строк вставляем, столько снизу и затрётся. Поэтому говорим число
        # заранее — столько пустых строк нужно добавить перед вставкой.
        self.table_hint = QLabel("")
        self.table_hint.setStyleSheet("color: %s; background: transparent;" % c["bright"])
        self.table_hint.setToolTip(
            "Confluence вставляет таблицу поверх существующих строк: добавьте "
            "в неё столько же пустых строк перед вставкой — иначе написанное "
            "ниже затрётся."
        )
        head_row.addWidget(self.table_hint)
        layout.addLayout(head_row)

        body = QHBoxLayout()
        body.setSpacing(theme.px(22))
        layout.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(theme.px(8))
        # Таблица — настоящей таблицей, как она встанет в Confluence; другие
        # разрезы и правка — текстом.
        self.table_view = QTextBrowser()
        self.table_view.setProperty("plain", "true")
        self.table_view.setOpenExternalLinks(True)
        left.addWidget(self.table_view, 1)
        self.text_edit = QPlainTextEdit()
        left.addWidget(self.text_edit, 1)
        body.addLayout(left, 1)

        side = QWidget()
        side.setFixedWidth(theme.px(360))
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, theme.px(4), 0, 0)
        side_layout.setSpacing(theme.px(16))

        stats = TitledPanel("Отметки по дням", c)
        self.week_chart = GridText(c)
        stats.box.addWidget(self.week_chart)
        self.marks_row = LeaderRow("отметок", c)
        self.closed_row = LeaderRow("закрыто", c)
        self.overdue_row = LeaderRow("просрочено", c)
        for row in (self.marks_row, self.closed_row, self.overdue_row):
            stats.box.addWidget(row)
        self.rule_label = QLabel()
        self.rule_label.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
        stats.box.addWidget(self.rule_label)
        side_layout.addWidget(stats)

        self.jira_panel = TitledPanel("Завести в Jira", c)
        self.jira_hint = QLabel()
        self.jira_hint.setWordWrap(True)
        self.jira_hint.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
        self.jira_panel.box.addWidget(self.jira_hint)
        self.jira_area = QScrollArea()
        self.jira_area.setWidgetResizable(True)
        self.jira_area.setFrameShape(QFrame.Shape.NoFrame)
        self.jira_panel.box.addWidget(self.jira_area, 1)
        self.jira_status = QLabel(self.jira_note)
        self.jira_status.setWordWrap(True)
        self.jira_status.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
        self.jira_panel.box.addWidget(self.jira_status)
        side_layout.addWidget(self.jira_panel, 1)
        # Интеграция выключена — панель «Завести в Jira» не нужна.
        self.jira_panel.setVisible(self.jira_enabled)
        if not self.jira_enabled:
            side_layout.addStretch(1)
        body.addWidget(side)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: %s; background: transparent;" % c["text_dim"])
        layout.addWidget(self.status)

        rule = QFrame()
        rule.setFixedHeight(theme.px(2))
        rule.setStyleSheet("background: %s; border: none;" % c["faint"])
        layout.addWidget(rule)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.px(10))
        self.copy_button = _button("[ Скопировать ]", "accent")
        self.copy_button.clicked.connect(self._copy)
        buttons.addWidget(self.copy_button)
        self.confluence_button = _button("[ В Confluence ]", "flat")
        self.confluence_button.clicked.connect(self._publish_confluence)
        buttons.addWidget(self.confluence_button)
        self.obsidian_button = _button("[ В Obsidian ]", "flat")
        self.obsidian_button.clicked.connect(self._export_obsidian)
        buttons.addWidget(self.obsidian_button)
        regenerate = _button("[ Пересобрать ]", "flat")
        regenerate.setToolTip("Собрать отчёт заново из отметок и спросить Jira")
        regenerate.clicked.connect(self._regenerate)
        buttons.addWidget(regenerate)
        self.edit_button = _button("[ Править ]", "flat")
        self.edit_button.setToolTip(
            "Показать разметку и разрешить правку. Копируется отчёт и разметкой, "
            "и готовой таблицей — Confluence вставит таблицу."
        )
        self.edit_button.clicked.connect(self._toggle_edit)
        buttons.addWidget(self.edit_button)
        buttons.addStretch(1)
        all_weeks = _button("все недели\u2026", "flat")
        all_weeks.setToolTip("Выгрузка по задачам за все заполненные недели")
        all_weeks.clicked.connect(self._open_all_weeks)
        buttons.addWidget(all_weeks)
        close_button = _button("Готово", "flat")
        close_button.clicked.connect(self._save_and_close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.obsidian_button.setEnabled(bool(self.settings.get("obsidian.vault_path", "")))
        config = ConfluenceConfig.from_settings(
            self.settings.get("confluence", {}) or {},
            self.settings.get("network.ca_file", ""),
            self.settings.get("network.proxy", ""),
        )
        cf_on = bool(self.settings.get("confluence.enabled", False)) and config.is_configured
        self.confluence_button.setVisible(cf_on)

    # --- Данные ---------------------------------------------------------------

    def _known_weeks(self) -> list[date]:
        """Недели, между которыми имеет смысл листать: заполненные плюс текущая."""
        weeks = set(self.storage.weeks_with_activity())
        weeks.add(week_bounds()[0])
        weeks.add(self.start)
        return sorted(weeks)

    def _step(self, direction: int) -> None:
        """Переходит к соседней заполненной неделе, не заглядывая в будущее."""
        weeks = self._known_weeks()
        if self.start not in weeks:
            return
        index = weeks.index(self.start) + direction
        if not 0 <= index < len(weeks):
            return
        self.start = weeks[index]
        self.end = self.start + timedelta(days=6)
        # Другая неделя — другие закрытые задачи, спрашиваем Jira заново.
        self.facts = JiraFacts()
        self.refresh()
        self.load_jira_done()

    def _sync_navigation(self) -> None:
        weeks = self._known_weeks()
        index = weeks.index(self.start)
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(weeks) - 1)

    def set_grouping(self, grouping: str) -> None:
        """Переключает разрез отчёта и запоминает выбор на будущее."""
        if grouping == self.grouping:
            return
        self.grouping = grouping
        self.settings.set("weekly.grouping", grouping)
        self.settings.save()
        self.refresh(regenerate=True)
        self.status.setText("Отчёт пересобран %s" % GROUPING_LABELS[grouping])

    def table_rows(self) -> int:
        """Сколько строк в таблице отчёта — без шапки и разделителя."""
        rows = 0
        for line in self.content.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            if set(line) <= set("|-: "):
                continue
            rows += 1
        return rows

    def _sync_table_hint(self) -> None:
        """Подсказка про вставку — только там, где отчёт это таблица."""
        if self.grouping != GROUPING_TABLE:
            self.table_hint.setVisible(False)
            return
        rows = self.table_rows()
        self.table_hint.setVisible(True)
        self.table_hint.setText(
            "! в таблице %d %s — добавьте в Confluence столько же пустых строк"
            % (rows, _rows_word(rows))
        )

    def _render_view(self) -> None:
        """Показывает отчёт: таблицей, читаемым текстом или разметкой при правке."""
        as_table = self.grouping == GROUPING_TABLE and not self.editing
        self.table_view.setVisible(as_table)
        self.text_edit.setVisible(not as_table)
        if as_table:
            self.table_view.setHtml(week_table_html(self.content, self.colors))
        else:
            self.text_edit.setPlainText(
                self.content if self.editing else to_plain(self.content)
            )
            self.text_edit.setReadOnly(not self.editing)
            theme.apply_text_spacing(self.text_edit)
        self.edit_button.setText("[ Готово ]" if self.editing else "[ Править ]")
        self.copy_button.setText(
            "[ Скопировать таблицу ]" if self.grouping == GROUPING_TABLE else "[ Скопировать ]"
        )

    def _toggle_edit(self) -> None:
        if self.editing:
            self.content = self.text_edit.toPlainText()
        self.editing = not self.editing
        self._render_view()
        self.status.setText(
            "Показана разметка — так отчёт попадёт в буфер и в Confluence."
            if self.editing
            else ""
        )

    def _regenerate(self) -> None:
        """Пересобрать — значит и переспросить Jira: неделя могла дополниться."""
        self.refresh(regenerate=True)
        self.load_jira_done()

    def _jira_config(self) -> JiraConfig:
        return JiraConfig.from_settings(
            self.settings.get("jira", {}) or {},
            self.settings.get("network.ca_file", ""),
            self.settings.get("network.proxy", ""),
        )

    def load_jira_done(self) -> None:
        """Спрашивает Jira, что закрыто за неделю — вдруг здесь это не отмечено."""
        if not self.jira_enabled:
            return
        config = self._jira_config()
        if not config.is_configured:
            return
        if self._jira_thread is not None and self._jira_thread.isRunning():
            return
        self.jira_note = "Спрашиваю Jira о закрытых задачах…"
        self._sync_jira_note()
        thread = JiraDoneFetch(config, self.start, self.end, self)
        thread.done.connect(self._on_jira_done)
        thread.failed.connect(self._on_jira_failed)
        self._jira_thread = thread
        thread.start()

    def _on_jira_done(self, issues) -> None:
        if isinstance(issues, dict):
            self.facts = JiraFacts.from_issues(issues.get("done"), issues.get("active"))
        else:
            self.facts = JiraFacts.from_issues(issues)
        self.jira_note = "Jira: закрыто за неделю — %d, в работе — %d" % (
            len(self.facts.done), len(self.facts.active)
        )
        self._sync_jira_note()
        # Обычный refresh, а не пересборка: сохранённый и правленый вручную
        # отчёт затирать нельзя. Разрез «таблицей» и так собирается заново.
        self.refresh()

    def _on_jira_failed(self, message: str) -> None:
        self.facts = JiraFacts()
        # Отчёт нужен и без Jira, поэтому сообщаем тихо, одной строкой.
        self.jira_note = "Jira не ответила: %s" % message.split("\n")[0]
        self._sync_jira_note()

    def _sync_jira_note(self) -> None:
        label = getattr(self, "jira_status", None)
        if label is not None:
            label.setText(self.jira_note)

    def _sync_grouping_buttons(self) -> None:
        for key, button in self.grouping_buttons.items():
            button.setProperty("active", "true" if key == self.grouping else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def refresh(self, regenerate: bool = False) -> None:
        """Перечитывает отчёт. ``regenerate`` игнорирует ранее сохранённый текст."""
        self.panel.set_title(
            "Отчёт за неделю \u00b7 НЕД %d \u00b7 %s \u2014 %s" % (
                self.start.isocalendar()[1],
                self.start.strftime("%d.%m"),
                self.end.strftime("%d.%m"),
            )
        )
        self.setWindowTitle(
            "Недельный отчёт: %s — %s" % (fmt_date(self.start), fmt_date(self.end))
        )
        stale_days = self.settings.get_int("stale_days", 5)
        saved = None if regenerate else self.storage.get_weekly_report(self.start)
        # Разрез «таблицей» — представление, а не сохранённый текст: его всегда
        # собираем заново, иначе показали бы вчерашний отчёт по дням.
        if saved and self.grouping == GROUPING_TABLE:
            saved = None
        self.content = saved or render_weekly(
            self.storage,
            self.start,
            self.end,
            stale_days,
            self.grouping,
            with_jira=self.jira_enabled,
            jira_base=self.jira_base,
            rule=WeekRule.from_settings(self.settings),
            facts=self.facts,
        )
        self._render_view()
        self._sync_table_hint()
        self._sync_grouping_buttons()
        self._sync_navigation()
        self._sync_week_stats()
        self._fill_jira_list()

    def _sync_week_stats(self) -> None:
        """Сводка справа: отметки по дням, закрытое и просроченное."""
        c = self.colors
        days = [self.start + timedelta(days=i) for i in range(7)]
        per_day = {day: 0 for day in days}
        for log in self.storage.logs_in_range(self.start, self.end):
            if log.log_date in per_day:
                per_day[log.log_date] += 1
        # Выходные — только если в них работали: иначе это два пустых столбика.
        shown = [day for day in days if day.weekday() < 5 or per_day[day]]
        self.week_chart.set_lines(
            week_chart_lines([per_day[day] for day in shown], shown, c)
        )
        rule = WeekRule.from_settings(self.settings)
        data = collect_week(self.storage, self.start, self.end, rule)
        self.marks_row.set_value(str(sum(per_day.values())), c["bright"])
        self.closed_row.set_value(str(len(data["completed"])), c["bright"])
        overdue = sum(1 for task in self.storage.list_tasks(include_done=False)
                      if task.is_overdue)
        self.overdue_row.set_value(str(overdue), c["danger"] if overdue else c["text_dim"])
        self.overdue_row.key.setStyleSheet(
            "color: %s; background: transparent;" % (c["danger"] if overdue else c["text_dim"])
        )
        self.rule_label.setText(
            "рубеж недели \u2014 %s" % rule.describe() if rule.enabled else "без рубежа недели"
        )

    def _fill_jira_list(self) -> None:
        if not self.jira_enabled:
            return
        data = collect_week(
            self.storage, self.start, self.end, WeekRule.from_settings(self.settings)
        )
        tasks = data["jira_todo"]
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, theme.px(8), 0)
        layout.setSpacing(theme.px(10))

        if not tasks:
            self.jira_hint.setText("По всем задачам недели вопрос с Jira закрыт.")
        else:
            self.jira_hint.setText(
                "Была работа, а ключа нет. Укажите ключ — задача уйдёт из списка."
            )
            for task in tasks:
                layout.addWidget(self._jira_card(task))
        layout.addStretch(1)
        self.jira_area.setWidget(container)

    def _jira_card(self, task) -> QWidget:
        c = self.colors
        card = QWidget()
        clear_background(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.px(2))

        title = QLabel("\u25aa " + task.title)
        title.setWordWrap(True)
        title.setStyleSheet("color: %s; background: transparent;" % c["text"])
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(cell_width() * 2, 0, 0, 0)
        row.setSpacing(theme.px(4))
        created = link_button("ключ\u2026", "Указать ключ задачи в Jira")
        created.clicked.connect(lambda _=False, t=task: self._mark_created(t))
        row.addWidget(created)
        row.addWidget(glyph_label("\u2502", c["faint"]))
        not_needed = link_button("не нужна", "Эту задачу в Jira заводить не нужно")
        not_needed.clicked.connect(lambda _=False, t=task: self._mark_not_needed(t))
        row.addWidget(not_needed)
        base = self.settings.get("jira.base_url", "")
        if base:
            row.addWidget(glyph_label("\u2502", c["faint"]))
            open_jira = link_button("создать", "Открыть форму новой задачи в Jira")
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
        """Текст с разметкой — именно он копируется и публикуется."""
        if self.editing:
            self.content = self.text_edit.toPlainText()
        return self.content

    def _save_and_close(self) -> None:
        # Таблица — только представление, сохранять её вместо отчёта не нужно.
        if self.grouping == GROUPING_TABLE:
            self.accept()
            return
        self.storage.save_weekly_report(self.start, self._content())
        self.storage.set_meta("last_weekly_report", self.start.isoformat())
        self.accept()

    def _copy(self) -> None:
        copy_report(self._content())
        if self.grouping == GROUPING_TABLE:
            rows = self.table_rows()
            self.status.setText(
                "Скопировано таблицей: %d %s. Столько строк Confluence и "
                "перезапишет при вставке." % (rows, _rows_word(rows))
            )
        else:
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
        config = ConfluenceConfig.from_settings(
            self.settings.get("confluence", {}) or {},
            self.settings.get("network.ca_file", ""),
            self.settings.get("network.proxy", ""),
        )
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
        manage_window(self, settings, "history", 880, 620)
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

        self._markdown = ""
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(theme.mono_font(9))
        splitter.addWidget(self.view)
        splitter.setSizes([250, 610])

        buttons = QHBoxLayout()
        copy_button = _button("Скопировать")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self._markdown)
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
        jira_on = bool(self.settings.get("jira.enabled", True))
        if self.kind_box.currentData() == "daily":
            report = self.storage.get_daily_report(value)
            self._markdown = (
                render_daily(report, self.storage, with_jira=jira_on) if report else ""
            )
            self.view.setPlainText(to_plain(self._markdown))
            theme.apply_text_spacing(self.view)
        else:
            content = self.storage.get_weekly_report(value)
            if not content:
                content = render_weekly(
                    self.storage,
                    value,
                    value + timedelta(days=6),
                    self.settings.get_int("stale_days", 5),
                    self.settings.get("weekly.grouping", GROUPING_BY_DAYS),
                    with_jira=jira_on,
                    jira_base=self.settings.get("jira.base_url", "") if jira_on else "",
                    rule=WeekRule.from_settings(self.settings),
                )
            self._markdown = content
            self.view.setPlainText(to_plain(content))
            theme.apply_text_spacing(self.view)


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
        self._build()
        self.refresh()
        manage_window(self, settings, "all_weeks", 920, 700)

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
        for key in (GROUPING_BY_TASKS, GROUPING_BY_DAYS, GROUPING_TABLE):
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
        jira_on = bool(self.settings.get("jira.enabled", True))
        self.content = render_all_weeks(
            self.storage,
            self.grouping,
            self.settings.get_int("stale_days", 5),
            with_jira=jira_on,
            jira_base=self.settings.get("jira.base_url", "") if jira_on else "",
            rule=WeekRule.from_settings(self.settings),
        )
        self.text_edit.setPlainText(to_plain(self.content))
        self.text_edit.setReadOnly(True)
        theme.apply_text_spacing(self.text_edit)
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
        QApplication.clipboard().setText(self.content)
        self.status.setText("Выгрузка скопирована в буфер обмена — с разметкой")

    def _export_obsidian(self) -> None:
        vault = self.settings.get("obsidian.vault_path", "")
        if not vault:
            QMessageBox.information(self, "Obsidian", "Укажите путь к хранилищу в настройках.")
            return
        target = Path(vault) / self.settings.get("obsidian.weekly_subdir", "")
        try:
            path = export_markdown(self.content, target, self._filename())
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
            Path(path).write_text(self.content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Сохранение", "Не удалось записать файл:\n%s" % exc)
            return
        self.status.setText("Сохранено: %s" % path)
