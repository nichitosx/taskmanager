"""Настройки приложения."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QTime, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QScrollArea,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import autostart
from .. import fonts as fonts_module
from .. import demo
from .. import products as products_module
from .. import shortcut
from ..config import Settings, data_dir, is_portable
from ..integrations.confluence import ConfluenceClient, ConfluenceConfig, ConfluenceError
from ..integrations.jira import (
    AUTH_LABELS,
    DEFAULT_JQL,
    DEFAULT_JQL_ACTIVE,
    JiraClient,
    JiraConfig,
    JiraError,
)
from ..reports import GROUPING_BY_DAYS, GROUPING_LABELS, WEEKDAY_NAMES
from . import theme
from .widgets import manage_window, hline, section_label


def _button(text: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty(kind, "true")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, storage=None) -> None:
        super().__init__(parent)
        self.settings = settings
        # Хранилище нужно только для кнопки с задачами-примерами.
        self.storage = storage if storage is not None else getattr(parent, "storage", None)
        self.setWindowTitle("Настройки")
        self._build()
        self._load()
        manage_window(self, settings, "settings", 680, 640)

    # --- Построение -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        tabs = QTabWidget()
        # Каждая вкладка прокручивается: на невысоком экране содержимое длиннее
        # окна, а кнопки сохранения должны оставаться на виду.
        tabs.addTab(self._scrollable(self._general_tab()), "Общее")
        tabs.addTab(self._scrollable(self._reminders_tab()), "Напоминания")
        tabs.addTab(self._scrollable(self._products_tab()), "Продукты")
        tabs.addTab(self._scrollable(self._integrations_tab()), "Интеграции")
        layout.addWidget(tabs, 1)

        self.status = QLabel("")
        self.status.setProperty("faint", "true")
        self.status.setFont(theme.mono_font(8))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        data_button = _button("Открыть папку с данными", "flat")
        data_button.clicked.connect(self._open_data_dir)
        buttons.addWidget(data_button)
        buttons.addStretch(1)
        cancel = _button("Отмена", "flat")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = _button("Сохранить", "accent")
        save.clicked.connect(self._save)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.theme_box = QComboBox()
        self.theme_box.addItem("Тёмная", "dark")
        self.theme_box.addItem("Светлая", "light")
        form.addRow("Оформление", self.theme_box)

        self.style_box = QComboBox()
        for key, title in theme.STYLE_LABELS.items():
            self.style_box.addItem(title, key)
        form.addRow("Стиль", self.style_box)

        self.stale_spin = QSpinBox()
        self.stale_spin.setRange(1, 60)
        self.stale_spin.setSuffix(" дн.")
        form.addRow("Считать задачу «без движения» через", self.stale_spin)

        layout.addLayout(form)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        font_row.addWidget(QLabel("Пиксельный шрифт"))
        self.pixel_font_box = QComboBox()
        self.pixel_font_box.setMinimumWidth(180)
        font_row.addWidget(self.pixel_font_box, 1)
        add_font = _button("Добавить файл…", "flat")
        add_font.setToolTip("Скопировать .ttf в папку программы и использовать его")
        add_font.clicked.connect(self._add_font)
        font_row.addWidget(add_font)
        layout.addLayout(font_row)

        self.font_note = QLabel()
        self.font_note.setWordWrap(True)
        self.font_note.setProperty("faint", "true")
        layout.addWidget(self.font_note)

        style_note = QLabel(
            "«Мягкий» — скруглённые карточки и системный шрифт. «Пиксельный» — "
            "прямые углы, моноширинный шрифт и жёсткие рамки. Применяется сразу "
            "после сохранения."
        )
        style_note.setWordWrap(True)
        style_note.setProperty("faint", "true")
        layout.addWidget(style_note)

        self.confirm_check = QCheckBox("Спрашивать подтверждение при отметке «выполнено»")
        layout.addWidget(self.confirm_check)
        self.tray_check = QCheckBox("Сворачивать в трей вместо закрытия")
        layout.addWidget(self.tray_check)
        self.autostart_check = QCheckBox("Запускать при входе в Windows")
        layout.addWidget(self.autostart_check)

        note = QLabel(
            "Автозапуск создаёт обычный ярлык в папке «Автозагрузка» вашего профиля — "
            "права администратора не нужны."
        )
        note.setWordWrap(True)
        note.setProperty("faint", "true")
        layout.addWidget(note)

        layout.addWidget(hline())
        layout.addWidget(section_label("задачи-примеры"))
        demo_row = QHBoxLayout()
        demo_row.setSpacing(8)
        self.demo_button = _button("Добавить задачи-примеры", "flat")
        self.demo_button.clicked.connect(self._add_demo)
        demo_row.addWidget(self.demo_button)
        demo_row.addStretch(1)
        layout.addLayout(demo_row)

        demo_note = QLabel(
            "Несколько задач, показывающих сроки, приоритеты, продукты и плановый "
            "старт. Убрать их можно кнопкой над списком задач."
        )
        demo_note.setWordWrap(True)
        demo_note.setProperty("faint", "true")
        layout.addWidget(demo_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("обновление"))
        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.update_button = _button("Проверить обновления")
        self.update_button.clicked.connect(self._run_update)
        update_row.addWidget(self.update_button)

        self.update_check_box = QCheckBox("Проверять обновления при запуске")
        self.update_check_box.setToolTip("Раз в сутки, в фоне; без интернета просто молчит")
        update_row.addWidget(self.update_check_box)
        update_row.addStretch(1)
        layout.addLayout(update_row)

        self.version_note = QLabel()
        self.version_note.setWordWrap(True)
        self.version_note.setProperty("faint", "true")
        layout.addWidget(self.version_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("ярлыки"))
        shortcut_row = QHBoxLayout()
        shortcut_row.setSpacing(8)
        desktop_button = _button("Ярлык на рабочий стол")
        desktop_button.clicked.connect(lambda: self._make_shortcut(shortcut.DESKTOP))
        shortcut_row.addWidget(desktop_button)
        menu_button = _button("Добавить в меню «Пуск»", "flat")
        menu_button.clicked.connect(lambda: self._make_shortcut(shortcut.START_MENU))
        shortcut_row.addWidget(menu_button)
        folder_button = _button("Ярлык в папке программы", "flat")
        folder_button.setToolTip("Положить ярлык рядом с run.py — запускать оттуда")
        folder_button.clicked.connect(lambda: self._make_shortcut(shortcut.APP_FOLDER))
        shortcut_row.addWidget(folder_button)
        shortcut_row.addStretch(1)
        layout.addLayout(shortcut_row)

        shortcut_note = QLabel(
            "Ярлык запускает программу двойным кликом по значку — без консоли и "
            "без прав администратора."
        )
        shortcut_note.setWordWrap(True)
        shortcut_note.setProperty("faint", "true")
        layout.addWidget(shortcut_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("где лежат данные"))
        path_label = QLabel(str(data_dir()))
        path_label.setFont(theme.mono_font(8))
        path_label.setProperty("dim", "true")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)
        mode = QLabel(
            "Портативный режим включён (файл portable.flag)."
            if is_portable()
            else "Чтобы носить программу с собой, положите рядом с run.py пустой файл portable.flag — "
            "данные переедут в папку приложения."
        )
        mode.setWordWrap(True)
        mode.setProperty("faint", "true")
        layout.addWidget(mode)

        layout.addStretch(1)
        return page

    def _reminders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.setSpacing(10)

        layout.addWidget(section_label("отчёт в конце дня"))
        self.eod_check = QCheckBox("Напоминать заполнить отчёт")
        layout.addWidget(self.eod_check)

        eod_row = QHBoxLayout()
        eod_row.addWidget(QLabel("Время"))
        self.eod_time = QTimeEdit()
        self.eod_time.setDisplayFormat("HH:mm")
        eod_row.addWidget(self.eod_time)
        eod_row.addStretch(1)
        layout.addLayout(eod_row)

        days_row = QHBoxLayout()
        days_row.setSpacing(10)
        days_row.addWidget(QLabel("Дни"))
        self.day_checks: list[QCheckBox] = []
        for index, name in enumerate(WEEKDAY_NAMES):
            box = QCheckBox(name[:2].capitalize())
            self.day_checks.append(box)
            days_row.addWidget(box)
        days_row.addStretch(1)
        layout.addLayout(days_row)

        layout.addWidget(hline())
        layout.addWidget(section_label("недельный отчёт"))
        self.weekly_check = QCheckBox("Составлять отчёт за неделю")
        layout.addWidget(self.weekly_check)

        weekly_row = QHBoxLayout()
        weekly_row.addWidget(QLabel("День"))
        self.weekly_day = QComboBox()
        for index, name in enumerate(WEEKDAY_NAMES):
            self.weekly_day.addItem(name.capitalize(), index)
        weekly_row.addWidget(self.weekly_day)
        weekly_row.addSpacing(14)
        weekly_row.addWidget(QLabel("Время"))
        self.weekly_time = QTimeEdit()
        self.weekly_time.setDisplayFormat("HH:mm")
        weekly_row.addWidget(self.weekly_time)
        weekly_row.addStretch(1)
        layout.addLayout(weekly_row)

        grouping_row = QHBoxLayout()
        grouping_row.addWidget(QLabel("Разрез отчёта"))
        self.grouping_box = QComboBox()
        for key, title in GROUPING_LABELS.items():
            self.grouping_box.addItem(title.capitalize(), key)
        grouping_row.addWidget(self.grouping_box)
        grouping_row.addStretch(1)
        layout.addLayout(grouping_row)

        grouping_note = QLabel(
            "«По дням» — хроника недели: что происходило каждый день. "
            "«По задачам» — сводка по каждой задаче со всеми отметками. "
            "Разрез можно переключить и прямо в окне отчёта."
        )
        grouping_note.setWordWrap(True)
        grouping_note.setProperty("faint", "true")
        layout.addWidget(grouping_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("плановые задачи"))
        self.planning_check = QCheckBox("Предупреждать, когда плановая задача скоро начнётся")
        layout.addWidget(self.planning_check)

        planning_row = QHBoxLayout()
        planning_row.addWidget(QLabel("За сколько дней"))
        self.planning_days = QSpinBox()
        self.planning_days.setRange(1, 60)
        self.planning_days.setSuffix(" дн.")
        planning_row.addWidget(self.planning_days)
        planning_row.addStretch(1)
        layout.addLayout(planning_row)

        planning_note = QLabel(
            "Про каждую задачу предупреждаем один раз — повторно только если "
            "сдвинуть дату начала."
        )
        planning_note.setWordWrap(True)
        planning_note.setProperty("faint", "true")
        layout.addWidget(planning_note)

        note = QLabel(
            "Если в нужный момент программа была закрыта, напоминание появится "
            "при первом запуске в этот день."
        )
        note.setWordWrap(True)
        note.setProperty("faint", "true")
        layout.addWidget(note)

        layout.addStretch(1)
        return page

    def _products_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.setSpacing(10)

        layout.addWidget(section_label("справочник продуктов"))
        intro = QLabel(
            "Продукт — направление, к которому относится задача. Метка видна в списке, "
            "по ней можно фильтровать задачи и она попадает в отчёты."
        )
        intro.setWordWrap(True)
        intro.setProperty("dim", "true")
        layout.addWidget(intro)

        self.products_list = QListWidget()
        self.products_list.itemDoubleClicked.connect(lambda _: self._edit_product())
        layout.addWidget(self.products_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add = _button("Добавить")
        add.clicked.connect(self._add_product)
        buttons.addWidget(add)
        edit = _button("Изменить", "flat")
        edit.clicked.connect(self._edit_product)
        buttons.addWidget(edit)
        remove = _button("Удалить", "flat")
        remove.setProperty("danger", "true")
        remove.clicked.connect(self._remove_product)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.autodetect_check = QCheckBox("Определять продукт по тексту задачи автоматически")
        layout.addWidget(self.autodetect_check)

        note = QLabel(
            "Ключевые слова перечисляются через запятую. Если слово встретилось в "
            "названии или заметках задачи, продукт подставится сам — и его всегда "
            "можно поправить в карточке. Уже проставленные метки при изменении "
            "справочника не теряются."
        )
        note.setWordWrap(True)
        note.setProperty("faint", "true")
        layout.addWidget(note)
        return page

    def _jira_config(self) -> JiraConfig:
        return JiraConfig(
            base_url=self.jira_url.text().strip(),
            email=self.jira_email.text().strip(),
            token=self.jira_token.text().strip(),
            jql=self.jira_jql.text().strip() or DEFAULT_JQL,
            jql_active=self.jira_jql_active.text().strip() or DEFAULT_JQL_ACTIVE,
            enabled=self.jira_check.isChecked(),
            ca_file=self.ca_edit.text().strip(),
            auth=self.jira_auth.currentData() or "auto",
        )

    def _reset_jql(self) -> None:
        self.jira_jql_active.setText(DEFAULT_JQL_ACTIVE)
        self.jira_jql.setText(DEFAULT_JQL)

    def _sync_jira_auth_hint(self) -> None:
        """Подсказка под полями: что именно вводить при выбранном способе."""
        mode = self.jira_auth.currentData()
        if mode == "basic":
            text = (
                "Облачная Jira (адрес вида mycompany.atlassian.net): e-mail учётной "
                "записи и API-токен из id.atlassian.com → Security → API tokens. "
                "Пароль от учётной записи не подойдёт."
            )
        elif mode == "bearer":
            text = (
                "Своя Jira (Server или Data Center): личный токен из профиля Jira — "
                "аватар → Profile → Personal Access Tokens → Create token. Поле "
                "«E-mail или логин» при этом не используется."
            )
        else:
            text = (
                "Программа сама попробует оба способа: сначала пару «e-mail + токен» "
                "(облачная Jira), затем личный токен (своя Jira Server/DC)."
            )
        self.jira_auth_note.setText(text)

    def _check_jira(self) -> None:
        config = self._jira_config()
        if not config.is_configured:
            QMessageBox.information(
                self, "Jira", "Заполните адрес Jira и токен, чтобы проверить связь."
            )
            return
        self.status.setText("Спрашиваю Jira…")
        QApplication.processEvents()

        client = JiraClient(config)
        try:
            name, scheme = client.whoami()
        except JiraError as exc:
            self.status.setText("")
            QMessageBox.warning(self, "Jira", str(exc))
            return

        way = "e-mail и API-токен" if scheme == "basic" else "личный токен"
        try:
            issues = client.search(limit=10)
        except JiraError as exc:
            self.status.setText("Вход выполнен (%s), но фильтр не сработал." % way)
            QMessageBox.warning(self, "Jira", str(exc))
            return

        if not issues:
            self.status.setText(
                "Вошли как %s (%s). Под фильтр не попала ни одна задача." % (name, way)
            )
            return
        self.status.setText(
            "Вошли как %s (%s). Первая задача: %s — %s"
            % (name, way, issues[0].key, issues[0].summary)
        )

    def _sync_integrations(self) -> None:
        """Гасит поля выключенной интеграции, чтобы не сбивали с толку."""
        jira_on = self.jira_check.isChecked()
        for widget in (
            self.jira_url,
            self.jira_auth,
            self.jira_email,
            self.jira_token,
            self.jira_jql,
            self.jira_jql_active,
            self.jira_check_button,
        ):
            widget.setEnabled(jira_on)
        cf_on = self.cf_check.isChecked()
        for widget in (
            self.cf_url,
            self.cf_email,
            self.cf_token,
            self.cf_space,
            self.cf_parent,
            self.cf_check_button,
        ):
            widget.setEnabled(cf_on)

    # --- Продукты -------------------------------------------------------------

    def _fill_products(self) -> None:
        self.products_list.clear()
        for product in self.products:
            keywords = ", ".join(product.keywords)
            item = QListWidgetItem(
                "%s — %s" % (product.name, keywords) if keywords else product.name
            )
            item.setData(Qt.ItemDataRole.UserRole, product.name)
            item.setIcon(self._color_dot(products_module.color_for(self.products, product.name)))
            self.products_list.addItem(item)

    @staticmethod
    def _color_dot(color: str, size: int = 12) -> QIcon:
        """Кружок цвета продукта — тот же, что и на метке в списке задач."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.end()
        return QIcon(pixmap)

    def _selected_product(self) -> int:
        row = self.products_list.currentRow()
        return row if 0 <= row < len(self.products) else -1

    def _add_product(self) -> None:
        dialog = ProductDialog(products_module.Product(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            product = dialog.result_product()
            if not product.name:
                return
            if products_module.find(self.products, product.name) is not None:
                QMessageBox.information(self, "Продукты", "Такой продукт уже есть в списке.")
                return
            self.products.append(product)
            self._fill_products()
            self.products_list.setCurrentRow(len(self.products) - 1)

    def _edit_product(self) -> None:
        index = self._selected_product()
        if index < 0:
            return
        dialog = ProductDialog(self.products[index], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            product = dialog.result_product()
            if product.name:
                self.products[index] = product
                self._fill_products()
                self.products_list.setCurrentRow(index)

    def _remove_product(self) -> None:
        index = self._selected_product()
        if index < 0:
            return
        name = self.products[index].name
        answer = QMessageBox.question(
            self,
            "Удалить продукт",
            "Убрать «%s» из справочника?\nУ задач метка останется — её можно снять в карточке."
            % name,
        )
        if answer == QMessageBox.StandardButton.Yes:
            del self.products[index]
            self._fill_products()

    def _sync_version(self) -> None:
        """Показывает установленную версию — её пишет «Обновить»."""
        from ..config import app_dir, data_dir

        installed = {}
        try:
            marker = data_dir() / "installed.json"
            if marker.exists():
                import json

                installed = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            installed = {}

        if installed.get("sha"):
            text = "Установлена версия %s от %s. " % (
                installed["sha"], installed.get("date", "—")
            )
        else:
            text = "Версия пока не отмечена. "
        self.version_note.setText(
            text + "Обновление скачивает свежие файлы программы с GitHub; задачи, "
            "настройки и шрифты остаются на месте. Программу после обновления "
            "нужно перезапустить."
        )
        self.update_button.setEnabled((app_dir() / "update.py").exists())

    def _run_update(self) -> None:
        """Запускает обновление отдельным окном: файлы меняются вне работающей программы."""
        from ..config import app_dir

        script = app_dir() / "Обновить.cmd"
        if not script.exists():
            QMessageBox.information(
                self, "Обновление",
                "Файл «Обновить.cmd» не найден рядом с программой.",
            )
            return
        try:
            os.startfile(str(script))  # noqa: S606 (штатный запуск в отдельном окне)
        except OSError as exc:
            QMessageBox.warning(self, "Обновление", "Не удалось запустить: %s" % exc)
            return
        self.status.setText(
            "Обновление идёт в отдельном окне. После него закройте программу и "
            "запустите заново."
        )

    def _add_demo(self) -> None:
        if self.storage is None:
            return
        created = demo.seed(self.storage, self.settings)
        self.products = products_module.load(self.settings)
        self._fill_products()
        self._sync_demo_button()
        self.status.setText(
            "Добавлено задач-примеров: %d. Закройте настройки, чтобы увидеть их в списке."
            % len(created)
        )

    def _sync_demo_button(self) -> None:
        if self.storage is None:
            self.demo_button.setEnabled(False)
            self.demo_button.setToolTip("Недоступно вне главного окна")
            return
        already = bool(demo.remaining_ids(self.storage))
        self.demo_button.setEnabled(not already)
        self.demo_button.setText(
            "Примеры уже добавлены" if already else "Добавить задачи-примеры"
        )

    def _make_shortcut(self, kind: str) -> None:
        try:
            path = shortcut.create(kind)
        except OSError as exc:
            QMessageBox.warning(self, "Ярлык", "Не удалось создать ярлык:\n%s" % exc)
            return
        self.status.setText("Ярлык создан: %s" % path)

    def _integrations_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.setSpacing(10)

        layout.addWidget(section_label("jira"))
        self.jira_check = QCheckBox("Использовать Jira")
        self.jira_check.toggled.connect(self._sync_integrations)
        layout.addWidget(self.jira_check)
        self.jira_url = QLineEdit()
        self.jira_url.setPlaceholderText("https://mycompany.atlassian.net")
        layout.addWidget(self.jira_url)
        jira_note = QLabel(
            "Адрес нужен для ссылок «Открыть в Jira». Если выключить интеграцию — из списков, "
            "карточек и отчётов пропадут все упоминания Jira, а ключи у задач сохранятся."
        )
        jira_note.setWordWrap(True)
        jira_note.setProperty("faint", "true")
        layout.addWidget(jira_note)

        jira_form = QFormLayout()
        jira_form.setSpacing(8)
        self.jira_auth = QComboBox()
        for key, title in AUTH_LABELS.items():
            self.jira_auth.addItem(title, key)
        self.jira_auth.currentIndexChanged.connect(self._sync_jira_auth_hint)
        jira_form.addRow("Способ входа", self.jira_auth)
        self.jira_email = QLineEdit()
        self.jira_email.setPlaceholderText("почта учётной записи Atlassian")
        self.jira_token = QLineEdit()
        self.jira_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.jira_jql_active = QLineEdit()
        self.jira_jql_active.setPlaceholderText(DEFAULT_JQL_ACTIVE)
        self.jira_jql = QLineEdit()
        self.jira_jql.setPlaceholderText(DEFAULT_JQL)
        jira_form.addRow("E-mail или логин", self.jira_email)
        jira_form.addRow("API-токен", self.jira_token)
        jira_form.addRow("Актуальные (JQL)", self.jira_jql_active)
        jira_form.addRow("Плановые (JQL)", self.jira_jql)
        layout.addLayout(jira_form)

        jira_check_row = QHBoxLayout()
        self.jira_check_button = _button("Проверить фильтр", "flat")
        self.jira_check_button.clicked.connect(self._check_jira)
        jira_check_row.addWidget(self.jira_check_button)
        reset_jql = _button("Вернуть фильтры по умолчанию", "flat")
        reset_jql.clicked.connect(self._reset_jql)
        jira_check_row.addWidget(reset_jql)
        jira_check_row.addStretch(1)
        layout.addLayout(jira_check_row)

        self.jira_auth_note = QLabel()
        self.jira_auth_note.setWordWrap(True)
        self.jira_auth_note.setProperty("faint", "true")
        layout.addWidget(self.jira_auth_note)

        jql_note = QLabel(
            "Из Jira собираются два списка: «Из Jira: в работе» и «Из Jira: планы». "
            "По умолчанию это назначенные на вас задачи в статусах «В работе» и "
            "«Сделать»; любой фильтр можно заменить своим JQL."
        )
        jql_note.setWordWrap(True)
        jql_note.setProperty("faint", "true")
        layout.addWidget(jql_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("сеть"))
        ca_row = QHBoxLayout()
        ca_row.setSpacing(8)
        self.ca_edit = QLineEdit()
        self.ca_edit.setPlaceholderText("файл корневого сертификата, если он нужен")
        ca_row.addWidget(self.ca_edit, 1)
        ca_browse = _button("Выбрать…", "flat")
        ca_browse.clicked.connect(self._pick_ca_file)
        ca_row.addWidget(ca_browse)
        layout.addLayout(ca_row)

        ca_note = QLabel(
            "Обычно ничего указывать не нужно: программа доверяет сертификатам из "
            "хранилища Windows. Поле пригодится, если трафик проверяет корпоративная "
            "защита, а её корневой сертификат в хранилище не попал — тогда Jira и "
            "Confluence отвечают ошибкой проверки сертификата."
        )
        ca_note.setWordWrap(True)
        ca_note.setProperty("faint", "true")
        layout.addWidget(ca_note)

        layout.addWidget(hline())
        layout.addWidget(section_label("obsidian"))
        vault_row = QHBoxLayout()
        self.vault_edit = QLineEdit()
        self.vault_edit.setPlaceholderText("Путь к хранилищу, например D:\\Obsidian\\Работа")
        vault_row.addWidget(self.vault_edit, 1)
        browse = _button("Выбрать…", "flat")
        browse.clicked.connect(self._pick_vault)
        vault_row.addWidget(browse)
        layout.addLayout(vault_row)

        subdirs = QFormLayout()
        subdirs.setSpacing(8)
        self.daily_subdir = QLineEdit()
        self.weekly_subdir = QLineEdit()
        subdirs.addRow("Папка для дней", self.daily_subdir)
        subdirs.addRow("Папка для недель", self.weekly_subdir)
        layout.addLayout(subdirs)

        layout.addWidget(hline())
        layout.addWidget(section_label("confluence"))
        self.cf_check = QCheckBox("Публиковать отчёты в Confluence")
        self.cf_check.toggled.connect(self._sync_integrations)
        layout.addWidget(self.cf_check)
        form = QFormLayout()
        form.setSpacing(8)
        self.cf_url = QLineEdit()
        self.cf_url.setPlaceholderText("https://mycompany.atlassian.net/wiki")
        self.cf_email = QLineEdit()
        self.cf_token = QLineEdit()
        self.cf_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_space = QLineEdit()
        self.cf_parent = QLineEdit()
        self.cf_parent.setPlaceholderText("ID родительской страницы, необязательно")
        form.addRow("Адрес", self.cf_url)
        form.addRow("E-mail", self.cf_email)
        form.addRow("API-токен", self.cf_token)
        form.addRow("Ключ пространства", self.cf_space)
        form.addRow("Родительская страница", self.cf_parent)
        layout.addLayout(form)

        check_row = QHBoxLayout()
        self.cf_check_button = _button("Проверить связь", "flat")
        self.cf_check_button.clicked.connect(self._check_confluence)
        check_row.addWidget(self.cf_check_button)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        cf_note = QLabel(
            "Токен хранится в settings.json в вашем профиле. Публикация происходит "
            "только по кнопке в окне недельного отчёта — если выключить, кнопка пропадёт."
        )
        cf_note.setWordWrap(True)
        cf_note.setProperty("faint", "true")
        layout.addWidget(cf_note)

        layout.addStretch(1)
        return page

    # --- Данные ---------------------------------------------------------------

    def _load(self) -> None:
        s = self.settings
        self._sync_version()
        self.update_check_box.setChecked(bool(s.get("updates.check_on_start", True)))
        index = self.theme_box.findData(s.get("theme", "dark"))
        self.theme_box.setCurrentIndex(max(index, 0))
        index = self.style_box.findData(s.get("ui_style", theme.STYLE_SOFT))
        self.style_box.setCurrentIndex(max(index, 0))
        self._fill_fonts()
        self.stale_spin.setValue(s.get_int("stale_days", 5))
        self.confirm_check.setChecked(bool(s.get("confirm_done", True)))
        self.tray_check.setChecked(bool(s.get("minimize_to_tray", True)))
        self.autostart_check.setChecked(autostart.is_enabled())

        self.eod_check.setChecked(bool(s.get("eod.enabled", True)))
        hours, minutes = self._split_time(s.get("eod.time", "17:30"), 17, 30)
        self.eod_time.setTime(QTime(hours, minutes))
        active_days = set(s.get("eod.weekdays", [0, 1, 2, 3, 4]) or [])
        for index, box in enumerate(self.day_checks):
            box.setChecked(index in active_days)

        self.weekly_check.setChecked(bool(s.get("weekly.enabled", True)))
        self.weekly_day.setCurrentIndex(s.get_int("weekly.weekday", 4))
        hours, minutes = self._split_time(s.get("weekly.time", "09:30"), 9, 30)
        self.weekly_time.setTime(QTime(hours, minutes))
        index = self.grouping_box.findData(s.get("weekly.grouping", GROUPING_BY_DAYS))
        self.grouping_box.setCurrentIndex(max(index, 0))

        self.planning_check.setChecked(bool(s.get("planning.notify_enabled", True)))
        self.planning_days.setValue(s.get_int("planning.notify_days", 7))
        self._sync_demo_button()
        self.products = products_module.load(s)
        self.autodetect_check.setChecked(bool(s.get("products_autodetect", True)))
        self._fill_products()

        self.jira_check.setChecked(bool(s.get("jira.enabled", True)))
        self.jira_url.setText(s.get("jira.base_url", ""))
        self.ca_edit.setText(s.get("network.ca_file", ""))
        index = self.jira_auth.findData(s.get("jira.auth", "auto"))
        self.jira_auth.setCurrentIndex(max(index, 0))
        self._sync_jira_auth_hint()
        self.jira_email.setText(s.get("jira.email", ""))
        self.jira_token.setText(s.get("jira.token", ""))
        self.jira_jql.setText(s.get("jira.jql", "") or DEFAULT_JQL)
        self.jira_jql_active.setText(s.get("jira.jql_active", "") or DEFAULT_JQL_ACTIVE)
        self.vault_edit.setText(s.get("obsidian.vault_path", ""))
        self.daily_subdir.setText(s.get("obsidian.daily_subdir", ""))
        self.weekly_subdir.setText(s.get("obsidian.weekly_subdir", ""))

        self.cf_url.setText(s.get("confluence.base_url", ""))
        self.cf_email.setText(s.get("confluence.email", ""))
        self.cf_token.setText(s.get("confluence.token", ""))
        self.cf_space.setText(s.get("confluence.space_key", ""))
        self.cf_parent.setText(s.get("confluence.parent_id", ""))
        self.cf_check.setChecked(bool(s.get("confluence.enabled", False)))
        self._sync_integrations()

    @staticmethod
    def _split_time(value: str, default_h: int, default_m: int) -> tuple[int, int]:
        try:
            hours, minutes = str(value).split(":")
            return int(hours), int(minutes)
        except (ValueError, AttributeError):
            return default_h, default_m

    def _fill_fonts(self) -> None:
        """Список шрифтов: свои файлы, найденные системные и «подобрать самим»."""
        from PySide6.QtGui import QFontDatabase

        installed = set(QFontDatabase.families())
        current = self.settings.get("pixel_font", "")

        self.pixel_font_box.clear()
        self.pixel_font_box.addItem("Подобрать автоматически", "")
        own = fonts_module.loaded_families()
        for family in own:
            self.pixel_font_box.addItem("%s — из папки программы" % family, family)
        for family in theme.PIXEL_CANDIDATES:
            if family in installed and family not in own:
                self.pixel_font_box.addItem("%s — из системы" % family, family)
        if current and self.pixel_font_box.findData(current) < 0:
            self.pixel_font_box.addItem("%s — не найден" % current, current)

        index = self.pixel_font_box.findData(current)
        self.pixel_font_box.setCurrentIndex(max(index, 0))

        self.font_note.setText(
            "Вместе с программой идут свободные пиксельные шрифты (Tiny5, Handjet) — "
            "они работают сразу и на любом компьютере. Свой файл можно добавить "
            "кнопкой рядом: он ляжет в папку %s, подключится без установки в Windows "
            "и переживёт обновление." % fonts_module.fonts_dir()
        )

    def _add_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл шрифта", "C:/Windows/Fonts", "Шрифты (*.ttf *.otf *.ttc)"
        )
        if not path:
            return
        family = fonts_module.add_file(path)
        if not family:
            QMessageBox.warning(self, "Шрифт", "Не удалось прочитать файл шрифта.")
            return
        self._fill_fonts()
        index = self.pixel_font_box.findData(family)
        self.pixel_font_box.setCurrentIndex(max(index, 0))
        self.status.setText("Шрифт «%s» добавлен." % family)

    def _pick_ca_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Корневой сертификат",
            self.ca_edit.text().strip(),
            "Сертификаты (*.pem *.crt *.cer);;Все файлы (*)",
        )
        if path:
            self.ca_edit.setText(path)

    def _pick_vault(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Папка хранилища Obsidian", self.vault_edit.text() or str(data_dir())
        )
        if path:
            self.vault_edit.setText(path)

    def _confluence_config(self) -> ConfluenceConfig:
        return ConfluenceConfig(
            base_url=self.cf_url.text().strip(),
            email=self.cf_email.text().strip(),
            token=self.cf_token.text().strip(),
            space_key=self.cf_space.text().strip(),
            parent_id=self.cf_parent.text().strip(),
            ca_file=self.ca_edit.text().strip(),
        )

    def _check_confluence(self) -> None:
        config = self._confluence_config()
        if not config.is_configured:
            self.status.setText("Заполните адрес, e-mail, токен и ключ пространства.")
            return
        self.status.setText("Проверяю доступ…")
        try:
            name = ConfluenceClient(config).check_connection()
        except ConfluenceError as exc:
            self.status.setText("")
            QMessageBox.warning(self, "Confluence", str(exc))
            return
        self.status.setText("Связь есть. Пространство: %s" % name)

    def _open_data_dir(self) -> None:
        path = str(data_dir())
        try:
            os.startfile(path)  # noqa: S606 (штатный способ открыть проводник)
        except (OSError, AttributeError):
            subprocess.Popen(["explorer", path])

    def _save(self) -> None:
        s = self.settings
        s.set("theme", self.theme_box.currentData())
        s.set("ui_style", self.style_box.currentData())
        s.set("pixel_font", self.pixel_font_box.currentData() or "")
        s.set("stale_days", self.stale_spin.value())
        s.set("updates.check_on_start", self.update_check_box.isChecked())
        s.set("confirm_done", self.confirm_check.isChecked())
        s.set("minimize_to_tray", self.tray_check.isChecked())

        s.set("eod.enabled", self.eod_check.isChecked())
        s.set("eod.time", self.eod_time.time().toString("HH:mm"))
        s.set("eod.weekdays", [i for i, box in enumerate(self.day_checks) if box.isChecked()])

        s.set("weekly.enabled", self.weekly_check.isChecked())
        s.set("weekly.weekday", self.weekly_day.currentData())
        s.set("weekly.time", self.weekly_time.time().toString("HH:mm"))
        s.set("weekly.grouping", self.grouping_box.currentData())
        s.set("planning.notify_enabled", self.planning_check.isChecked())
        s.set("planning.notify_days", self.planning_days.value())
        s.set("products_autodetect", self.autodetect_check.isChecked())
        products_module.save(s, self.products)

        s.set("jira.enabled", self.jira_check.isChecked())
        s.set("network.ca_file", self.ca_edit.text().strip())
        s.set("jira.auth", self.jira_auth.currentData() or "auto")
        s.set("jira.email", self.jira_email.text().strip())
        s.set("jira.token", self.jira_token.text().strip())
        s.set("jira.jql", self.jira_jql.text().strip() or DEFAULT_JQL)
        s.set("jira.jql_active", self.jira_jql_active.text().strip() or DEFAULT_JQL_ACTIVE)
        s.set("jira.base_url", self.jira_url.text().strip().rstrip("/"))
        s.set("obsidian.vault_path", self.vault_edit.text().strip())
        s.set("obsidian.daily_subdir", self.daily_subdir.text().strip())
        s.set("obsidian.weekly_subdir", self.weekly_subdir.text().strip())
        s.set("obsidian.enabled", bool(self.vault_edit.text().strip()))

        config = self._confluence_config()
        s.set("confluence.base_url", config.base_url)
        s.set("confluence.email", config.email)
        s.set("confluence.token", config.token)
        s.set("confluence.space_key", config.space_key)
        s.set("confluence.parent_id", config.parent_id)
        # Включённой интеграция считается, только если доступы заполнены.
        s.set("confluence.enabled", self.cf_check.isChecked() and config.is_configured)

        wanted = self.autostart_check.isChecked()
        if wanted != autostart.is_enabled():
            try:
                autostart.apply(wanted)
            except OSError as exc:
                QMessageBox.warning(self, "Автозапуск", "Не удалось изменить автозапуск:\n%s" % exc)
        s.set("autostart", autostart.is_enabled())

        s.save()
        self.accept()


class ProductDialog(QDialog):
    """Маленькая форма продукта: название и ключевые слова для автоопределения."""

    def __init__(self, product: products_module.Product, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Продукт")
        self.setMinimumWidth(520)
        owner = parent.settings if parent is not None and hasattr(parent, "settings") else None
        self.settings_theme = owner.get("theme", "dark") if owner is not None else "dark"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        layout.addWidget(section_label("название"))
        self.name_edit = QLineEdit(product.name)
        self.name_edit.setPlaceholderText("Например: Личный кабинет")
        layout.addWidget(self.name_edit)

        layout.addWidget(section_label("ключевые слова"))
        self.keywords_edit = QLineEdit(", ".join(product.keywords))
        self.keywords_edit.setPlaceholderText("лк, кабинет, профиль — через запятую")
        layout.addWidget(self.keywords_edit)

        layout.addWidget(section_label("цвет метки"))
        self.color = product.color
        self._swatches: dict[str, QPushButton] = {}
        colors_row = QHBoxLayout()
        colors_row.setSpacing(6)

        auto = _button("Авто", "flat")
        auto.setToolTip("Цвет назначится сам, по порядку в справочнике")
        auto.clicked.connect(lambda: self._choose_color(""))
        self._swatches[""] = auto
        colors_row.addWidget(auto)

        for value in products_module.PALETTE:
            swatch = QPushButton()
            swatch.setFixedSize(24, 24)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(value)
            swatch.clicked.connect(lambda _=False, c=value: self._choose_color(c))
            self._swatches[value] = swatch
            colors_row.addWidget(swatch)

        custom = _button("Свой…", "flat")
        custom.clicked.connect(self._pick_custom_color)
        colors_row.addWidget(custom)
        colors_row.addStretch(1)
        layout.addLayout(colors_row)
        self._sync_swatches()

        hint = QLabel(
            "Если слово встретится в названии или заметках задачи, продукт "
            "подставится сам. Само название продукта тоже ищется — его "
            "перечислять не нужно."
        )
        hint.setWordWrap(True)
        hint.setProperty("faint", "true")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = _button("Отмена", "flat")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = _button("Сохранить", "accent")
        save.clicked.connect(self.accept)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.name_edit.setFocus()

    def _choose_color(self, value: str) -> None:
        self.color = value
        self._sync_swatches()

    def _pick_custom_color(self) -> None:
        start = QColor(self.color) if self.color else QColor("#D97757")
        chosen = QColorDialog.getColor(start, self, "Цвет метки продукта")
        if chosen.isValid():
            self._choose_color(chosen.name())

    def _sync_swatches(self) -> None:
        """Обводим выбранный цвет, чтобы было видно, что именно выбрано."""
        for value, button in self._swatches.items():
            if not value:
                button.setProperty("active", "true" if not self.color else "false")
                button.style().unpolish(button)
                button.style().polish(button)
                continue
            selected = value.lower() == (self.color or "").lower()
            button.setStyleSheet(
                "background: %s; border: %s; border-radius: %dpx;"
                % (
                    value,
                    ("2px solid %s" % theme.palette(self.settings_theme)["text"])
                    if selected
                    else "1px solid rgba(0, 0, 0, 60)",
                    theme.radius("small"),
                )
            )

    def result_product(self) -> products_module.Product:
        keywords = [k.strip() for k in self.keywords_edit.text().split(",") if k.strip()]
        return products_module.Product(
            name=self.name_edit.text().strip(), keywords=keywords, color=self.color
        )
