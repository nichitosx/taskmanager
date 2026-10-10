"""Мелкие визуальные элементы: строка задачи, «пилюли», заголовки секций."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import (
    QAbstractAnimation,
    QByteArray,
    QEvent,
    QObject,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QPointF,
    QRectF,
    QSize,
    Property,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QScrollArea,
    QLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..horizons import start_text
from ..recurrence import describe as describe_repeat
from ..reminders import describe_when
from ..models import (
    JIRA_NOT_NEEDED,
    PRIORITY_LABELS,
    PRIORITY_LEVELS,
    Task,
)
from . import theme
from .terminal import (
    ROW_PAD,
    ElidedLabel,
    FillGlyph,
    cell_width,
    column_widths,
)


def wrapped_height(label: QLabel, width: int) -> int:
    """Высота надписи с переносом при такой ширине — по метрикам шрифта.

    Саму надпись не спрашиваем: её heightForWidth не опускается ниже уже
    назначенной минимальной высоты, и после первого расчёта строка перестала
    бы уменьшаться при расширении окна. Метрики шрифта дают тот же результат,
    но без памяти о прошлом размере.
    """
    if width <= 0:
        return label.sizeHint().height()
    metrics = QFontMetrics(label.font())
    return metrics.boundingRect(
        0, 0, width, 100000, Qt.TextFlag.TextWordWrap, label.text()
    ).height()


def fit_title(label: QLabel, width: int) -> None:
    """Выдаёт надписи ровно ту высоту, которая нужна её тексту.

    Вложенные раскладки Qt считают ширину неточно и отмеряют меньше строк,
    чем нужно, — последняя строка длинного названия оказывалась срезанной.
    """
    if width <= 0:
        return
    needed = wrapped_height(label, width)
    if label.height() != needed:
        label.setFixedHeight(needed)


class FlowLayout(QLayout):
    """Ряд, который переносит не поместившиеся элементы на следующую строку.

    Метки задачи (срок, приоритет, продукт, теги) в узком окне переставали
    помещаться в одну строку и обрезались; теперь они просто переходят ниже.
    """

    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # --- Обязательный минимум QLayout ----------------------------------------

    def addItem(self, item) -> None:  # noqa: N802 (Qt naming)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt naming)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt naming)
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt naming)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    # --- Раскладка ------------------------------------------------------------

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def pixel_corner_path(rect: QRectF, radius: int = 6, step: int = 2) -> QPainterPath:
    """Прямоугольник со ступенчатыми углами — скругление в духе пиксель-арта.

    Обычный border-radius даёт гладкую сглаженную дугу, которая в пиксельном
    оформлении выглядит чужеродно. Здесь угол набирается из квадратных шагов.
    """
    path = QPainterPath()
    left, top = rect.x(), rect.y()
    right, bottom = rect.x() + rect.width(), rect.y() + rect.height()
    steps = max(1, int(radius / step))
    size = radius / steps

    def staircase(x: float, y: float, dx: float, dy: float) -> None:
        """Лесенка длиной radius: чередуем шаг по горизонтали и по вертикали."""
        for index in range(steps):
            path.lineTo(x + dx * size * (index + 1), y + dy * size * index)
            path.lineTo(x + dx * size * (index + 1), y + dy * size * (index + 1))

    path.moveTo(left + radius, top)
    path.lineTo(right - radius, top)
    staircase(right - radius, top, 1, 1)          # правый верхний
    path.lineTo(right, bottom - radius)
    staircase(right, bottom - radius, -1, 1)      # правый нижний
    path.lineTo(left + radius, bottom)
    staircase(left + radius, bottom, -1, -1)      # левый нижний
    path.lineTo(left, top + radius)
    staircase(left, top + radius, 1, -1)          # левый верхний
    path.closeSubpath()
    return path


def card_path(rect: QRectF) -> QPainterPath:
    """Контур карточки: гладкий в мягком стиле, прямоугольный в пиксельном."""
    path = QPainterPath()
    if theme.is_pixel():
        # Приборная панель: честный прямоугольник, а углы отмечают скобки.
        path.addRect(rect)
        return path
    path.addRoundedRect(rect, theme.radius("card"), theme.radius("card"))
    return path


# Длина уголка-скобки и его толщина: короткий штрих, который читается как
# «здесь угол панели» и не превращается во вторую рамку.
BRACKET_LENGTH = 9
BRACKET_WIDTH = 2


def paint_brackets(painter: QPainter, rect: QRectF, color: str) -> None:
    """Рисует по уголку в каждом углу — как на приборных панелях."""
    length = min(float(theme.px(BRACKET_LENGTH)), rect.width() / 3, rect.height() / 3)
    if length < 3:
        return
    pen = QPen(QColor(color), BRACKET_WIDTH)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    for x, y, dx, dy in (
        (rect.left(), rect.top(), 1, 1),
        (rect.right(), rect.top(), -1, 1),
        (rect.left(), rect.bottom(), 1, -1),
        (rect.right(), rect.bottom(), -1, -1),
    ):
        painter.drawLine(QPointF(x, y), QPointF(x + dx * length, y))
        painter.drawLine(QPointF(x, y), QPointF(x, y + dy * length))


class Card(QFrame):
    """Карточка, которая рисует себя сама.

    Своя отрисовка нужна ради пиксельных углов, а заодно даёт единый вид
    наведения и выделения без возни с таблицами стилей.
    """

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._bg = colors["bg"]
        self._border = colors["border_soft"]
        self._hover_bg = colors["surface_hover"]
        self._bar = ""
        self._hover = False
        # Уголки на углах панели: обычно чуть ярче рамки, у выделенного —
        # акцентные. По ним видно границы блока даже там, где рамка едва видна.
        self._corner = colors["text_faint"]
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_card_colors(
        self, bg: str = "", border: str = "", hover_bg: str = "", corner: str = ""
    ) -> None:
        self._bg = bg or self._bg
        self._border = border or self._border
        self._hover_bg = hover_bg or self._hover_bg
        self._corner = corner or self._corner
        self.update()

    def set_bar(self, color: str) -> None:
        """Цветная полоска у левого края (приоритет задачи)."""
        self._bar = color
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Терминал: прямоугольник в линию толщиной в пиксель шрифта, без
        # скруглений и уголков. Полоса слева — клетка цвета состояния.
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, theme.qcolor(self._hover_bg if self._hover else self._bg))
        if self._bar:
            painter.fillRect(0, 0, theme.px(3), rect.height(), theme.qcolor(self._bar))
        line = max(1, theme.px(2))
        border = theme.qcolor(self._border)
        painter.fillRect(0, 0, rect.width(), line, border)
        painter.fillRect(0, rect.height() - line, rect.width(), line, border)
        painter.fillRect(0, 0, line, rect.height(), border)
        painter.fillRect(rect.width() - line, 0, line, rect.height(), border)
        painter.end()


def fit_to_screen(window, width: int, height: int, margin: float = 0.92) -> None:
    """Задаёт размер окна, не выходя за пределы экрана.

    На ноутбуке с невысоким экраном (или при системном масштабе 125%) окно с
    жёстко заданным минимумом вылезает за край: кнопки «Сохранить» оказываются
    под нижней границей и до них не добраться. Поэтому желаемый размер
    ограничивается доступной областью экрана, а минимум ставится совсем
    небольшим — окно всегда можно сжать руками.
    """
    from PySide6.QtGui import QGuiApplication

    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        window.resize(width, height)
        return

    available = screen.availableGeometry()
    limit_width = int(available.width() * margin)
    limit_height = int(available.height() * margin)

    window.setMinimumSize(min(width, limit_width, 420), min(height, limit_height, 320))
    window.setMaximumHeight(available.height())
    window.resize(min(width, limit_width), min(height, limit_height))


def move_onto_screen(window) -> None:
    """Возвращает окно в видимую область, если оно вылезло за край.

    Так бывает после смены монитора или разрешения: сохранённые координаты
    указывают туда, где экрана уже нет, и окно оказывается недоступным.
    """
    from PySide6.QtGui import QGuiApplication

    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()

    geometry = window.frameGeometry()
    width = min(geometry.width(), available.width())
    height = min(geometry.height(), available.height())
    x = min(max(geometry.x(), available.x()), available.right() - width)
    y = min(max(geometry.y(), available.y()), available.bottom() - height)
    window.resize(width, height)
    window.move(x, y)


class _GeometryKeeper(QObject):
    """Запоминает размер и положение окна при закрытии."""

    def __init__(self, window, settings, key: str) -> None:
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.key = "windows.%s" % key

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        if event.type() in (QEvent.Type.Close, QEvent.Type.Hide):
            self.save()
        return False

    def save(self) -> None:
        if self.settings is None:
            return
        try:
            raw = bytes(self.window.saveGeometry().toBase64()).decode()
            self.settings.set(self.key, raw)
            self.settings.save()
        except Exception:
            pass  # не смогли запомнить размер — не повод мешать работе


def manage_window(window, settings, key: str, width: int, height: int) -> None:
    """Окно подстраивается под экран, помнит свой размер и остаётся видимым.

    Вызывается в конце сборки окна: сначала размер по содержимому, потом —
    сохранённый пользователем, если он есть и помещается на экран.
    """
    fit_to_screen(window, width, height)

    saved = settings.get("windows.%s" % key, "") if settings is not None else ""
    if saved:
        try:
            window.restoreGeometry(QByteArray.fromBase64(saved.encode()))
        except Exception:
            pass
    move_onto_screen(window)

    keeper = _GeometryKeeper(window, settings, key)
    window.installEventFilter(keeper)
    window._geometry_keeper = keeper  # держим ссылку, иначе фильтр соберёт сборщик


class SectionLabel(QLabel):
    """Подпись раздела: «── Когда ──────» — линия до правого края.

    Так раздел читается как строка текстового экрана, а не как случайное
    слово над списком: взгляд цепляется за линию и понимает, где кончается
    группа. Линии набраны тем же знаком «─», что и рамки, — они ложатся в сетку.
    """

    LEAD = "\u2500\u2500 "

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.mono_font())
        self.setMinimumWidth(0)
        self._sync_margin()

    def _sync_margin(self) -> None:
        self.setContentsMargins(self.fontMetrics().horizontalAdvance(self.LEAD), 0, 0, 0)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.Type.FontChange:
            self._sync_margin()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().paintEvent(event)
        metrics = self.fontMetrics()
        dash = "\u2500"
        step = max(1, metrics.horizontalAdvance(dash))
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(theme.qcolor(theme.colors()["faint"]))
        painter.drawText(0, baseline, dash * 2)
        start = self.contentsMargins().left() + text_width(self, self.text()) + step
        count = (self.width() - start) // step
        if count > 0:
            painter.drawText(start, baseline, dash * count)
        painter.end()


def clear_background(widget: QWidget) -> QWidget:
    """Прозрачный фон только у самого контейнера.

    Голое «background: transparent» в стилях контейнера наследуют все его
    дети, и оно перебивает общую таблицу стилей: главная кнопка внутри
    теряла заливку, а тёмный текст на ней пропадал на тёмном фоне.
    """
    if not widget.objectName():
        widget.setObjectName("clear%d" % id(widget))
    widget.setStyleSheet("#%s { background: transparent; }" % widget.objectName())
    return widget


def section_label(text: str) -> QLabel:
    """Подпись раздела с заглавной буквы: «── Подпункты ───»."""
    label = SectionLabel(text[:1].upper() + text[1:])
    label.setProperty("section", "true")
    return label


def hline() -> QFrame:
    line = QFrame()
    line.setProperty("hline", "true")
    line.setFixedHeight(1)
    return line


def headline() -> QFrame:
    """Разделитель под шапкой — с акцентным началом, чтобы окно не было серым."""
    line = QFrame()
    line.setProperty("headline", "true")
    line.setFixedHeight(1)
    return line


class CheckCircle(QAbstractButton):
    """Круглая отметка «выполнено».

    Рисуется вручную: системный QCheckBox даже со стилями выглядит инородно —
    квадратная галочка не ложится в остальной интерфейс. При наведении внутри
    круга проступает бледная галочка, чтобы было понятно, что сюда можно нажать.
    """

    # Крупный бледный круг спорил с текстом задачи, поэтому отметка компактная.
    SIZE = 16
    ANIMATION_MS = 170

    def __init__(self, checked: bool, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Отметить выполненной")
        self._hover = False
        # 0 — пусто, 1 — залито: промежуточные значения рисует анимация.
        self._fill = 1.0 if checked else 0.0
        self._animation: QPropertyAnimation | None = None
        self.toggled.connect(self._animate)

    def _get_fill(self) -> float:
        return self._fill

    def _set_fill(self, value: float) -> None:
        self._fill = max(0.0, min(1.0, float(value)))
        self.update()

    fill = Property(float, _get_fill, _set_fill)

    def set_checked_silently(self, checked: bool) -> None:
        """Меняет отметку без сигнала и без анимации — для отката действия."""
        # Анимацию от прошлого клика обязательно останавливаем: иначе она
        # доиграет и снова закрасит кружок, который мы только что сбросили.
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._fill = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked: bool) -> None:
        animation = QPropertyAnimation(self, b"fill", self)
        animation.setDuration(self.ANIMATION_MS)
        animation.setStartValue(self._fill)
        animation.setEndValue(1.0 if checked else 0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._animation = animation

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def set_ink(self, color: str) -> None:
        """Цвет отметки поверх инверсной строки — там обычный тусклый не виден."""
        self._ink = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Квадрат терминала: рамка в два пикселя, отметка — сплошная клетка
        # с галочкой из тех же квадратных пикселей. Сглаживания нет нарочно.
        c = self.colors
        ink = getattr(self, "_ink", "")
        painter = QPainter(self)
        unit = self.SIZE / 16.0
        line = max(1, round(2 * unit))
        frame = QColor(ink or (c["bright"] if self._hover else c["text_dim"]))
        size = self.SIZE
        painter.fillRect(0, 0, size, line, frame)
        painter.fillRect(0, size - line, size, line, frame)
        painter.fillRect(0, 0, line, size, frame)
        painter.fillRect(size - line, 0, line, size, frame)

        grown = max(0.0, min(1.0, self._fill))
        if grown > 0.01:
            inset = line + round((1.0 - grown) * (size / 2 - line))
            painter.fillRect(inset, inset, size - inset * 2, size - inset * 2,
                             QColor(ink or c["accent"]))
        if grown > 0.6 or (self._hover and grown <= 0.01):
            if grown > 0.6:
                tick = QColor(c["accent"] if ink else c["slab_ink"])
            else:
                tick = QColor(c["text_dim"])
            # Галочка из квадратиков: ступень вниз, три вверх.
            step = max(1, round(2 * unit))
            for x, y in ((4, 8), (6, 10), (8, 8), (10, 6), (12, 4)):
                painter.fillRect(round(x * unit) - step // 2, round(y * unit) - step // 2,
                                 step, step, tick)
        painter.end()


PILL_HEIGHT = 20

# Отступ от текста до рамки метки — одинаковый у всех меток, включая продукт.
PILL_PADDING = 6


def elide_text(metrics, text: str, width: int) -> str:
    """Обрезает текст под ширину.

    Стандартное многоточие есть не во всяком пиксельном шрифте, поэтому если
    его нет — дописываем две точки, они рисуются любым шрифтом.
    """
    if metrics.horizontalAdvance(text) <= width:
        return text
    # Многоточие в пиксельных шрифтах либо отсутствует, либо рисуется странно —
    # там честнее две точки.
    suffix = ".." if theme.is_pixel() else "…"
    while text and metrics.horizontalAdvance(text + suffix) > width:
        text = text[:-1]
    return text.rstrip() + suffix


def text_width(widget, text: str) -> int:
    """Ширина текста у уже стилизованного виджета.

    QLabel не учитывает отступы из таблицы стилей в подсказке размера, а сама
    таблица может подменить шрифт и межбуквенный интервал — поэтому меряем после
    ensurePolished и берём большее из двух измерений.
    """
    widget.ensurePolished()
    metrics = widget.fontMetrics()
    return max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width())


class Pill(QLabel):
    """Компактная метка: срок, ключ Jira, приоритет, продукт, простой.

    Метку можно сделать кнопкой: тогда по ней кликают, чтобы что-то заполнить —
    например, вписать ключ Jira прямо из списка.

    Высота фиксированная, текст по центру: у моноширинных шрифтов запас под
    нижние выносные элементы разный, и без этого надпись съезжает вниз.
    """

    def __init__(
        self,
        text: str,
        color: str,
        strong: bool = False,
        left_padding: int = PILL_PADDING,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self.setFont(theme.small_font())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(theme.px(PILL_HEIGHT))
        # В пиксельном стиле метка — рамка в нитку почти без заливки: так она
        # читается как подпись на приборе, а не как цветная наклейка.
        pixel = theme.is_pixel()
        self.setStyleSheet(
            "color: %s; background: %s; border: 1px solid %s;"
            "border-radius: %dpx; padding-left: %dpx; padding-right: %dpx; %s"
            % (
                color,
                theme.tint(color, (0.10 if strong else 0.04) if pixel
                           else (0.20 if strong else 0.12)),
                theme.tint(color, 0.70 if pixel else 0.34),
                theme.radius("pill"),
                left_padding,
                PILL_PADDING,
                theme.small_font_css(),
            )
        )
        self.setFixedWidth(text_width(self, text) + left_padding + PILL_PADDING + 4)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    clicked = Signal()

    def make_clickable(self, tooltip: str = "") -> "Pill":
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        return self

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)


class ProductPill(Pill):
    """Метка продукта: та же «пилюля», но с цветным кружком слева.

    Кружок рисуется, а не кладётся в раскладку: так расстояние от него до текста
    одинаково у любого названия, а отступы совпадают с обычными метками.
    """

    DOT = 6
    DOT_GAP = 6

    def __init__(self, name: str, color: str, parent=None) -> None:
        self._dot_color = color
        super().__init__(
            name,
            color,
            left_padding=PILL_PADDING + self.DOT + self.DOT_GAP,
            parent=parent,
        )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not theme.is_pixel())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._dot_color))
        top = (self.height() - self.DOT) / 2.0
        box = QRectF(PILL_PADDING + 1, top, self.DOT, self.DOT)
        if theme.is_pixel():
            painter.drawRect(box)
        else:
            painter.drawEllipse(box)
        painter.end()


WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


class DueField(QWidget):
    """Срок задачи: дата из календаря, «как можно скорее» или без срока.

    Раньше срок задавался безымянной галочкой и полем даты, а календарь
    открывался только по крошечной стрелке. Теперь дата — кнопка, по которой
    сразу всплывает календарь; рядом быстрые даты, а под ними две подписанные
    галочки: ASAP и «без срока». Три режима друг друга исключают.
    """

    changed = Signal()

    # Быстрые даты: подпись и сдвиг от сегодня; «пт» — ближайшая пятница.
    QUICK = (("сегодня", 0), ("завтра", 1), ("пт", "friday"), ("+неделя", 7))

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QPushButton

        self.colors = colors
        self._date = date.today()
        self._popup = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.date_button = QPushButton()
        self.date_button.setToolTip("Выбрать дату в календаре")
        self.date_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.date_button.clicked.connect(self.open_calendar)
        top.addWidget(self.date_button, 1)
        self.quick_buttons = []
        for caption, shift in self.QUICK:
            button = QPushButton(caption)
            button.setProperty("flat", "true")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, s=shift: self.set_date(self.quick_date(s)))
            self.quick_buttons.append(button)
            top.addWidget(button)
        layout.addLayout(top)

        modes = QHBoxLayout()
        modes.setSpacing(18)
        self.asap_check = QCheckBox("ASAP — как можно скорее")
        self.asap_check.setToolTip("Без даты, но срочнее любой задачи со сроком")
        self.none_check = QCheckBox("Без срока")
        modes.addWidget(self.asap_check)
        modes.addWidget(self.none_check)
        modes.addStretch(1)
        layout.addLayout(modes)

        self.asap_check.toggled.connect(self._asap_toggled)
        self.none_check.toggled.connect(self._none_toggled)
        self._sync()

    # --- Значение ------------------------------------------------------------------

    @staticmethod
    def quick_date(shift, today: date | None = None) -> date:
        today = today or date.today()
        if shift == "friday":
            return today + timedelta(days=(4 - today.weekday()) % 7)
        return today + timedelta(days=int(shift))

    def mode(self) -> str:
        if self.asap_check.isChecked():
            return "asap"
        if self.none_check.isChecked():
            return "none"
        return "date"

    def value(self) -> tuple[date | None, bool]:
        """Срок и признак ASAP — ровно то, что ляжет в задачу."""
        mode = self.mode()
        return (self._date if mode == "date" else None), mode == "asap"

    def set_value(self, due: date | None, asap: bool = False) -> None:
        if due is not None:
            self._date = due
        for check, state in ((self.asap_check, asap), (self.none_check, not asap and due is None)):
            check.blockSignals(True)
            check.setChecked(state)
            check.blockSignals(False)
        self._sync()

    def set_date(self, day: date) -> None:
        """Выбрали дату — значит, режим «дата»: галочки снимаются."""
        self._date = day
        for check in (self.asap_check, self.none_check):
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self._sync()
        self.changed.emit()

    # --- Режимы --------------------------------------------------------------------

    def _asap_toggled(self, on: bool) -> None:
        if on:
            self.none_check.blockSignals(True)
            self.none_check.setChecked(False)
            self.none_check.blockSignals(False)
        self._sync()
        self.changed.emit()

    def _none_toggled(self, on: bool) -> None:
        if on:
            self.asap_check.blockSignals(True)
            self.asap_check.setChecked(False)
            self.asap_check.blockSignals(False)
        self._sync()
        self.changed.emit()

    def _sync(self) -> None:
        mode = self.mode()
        if mode == "asap":
            text = "ASAP"
        elif mode == "none":
            text = "без срока"
        else:
            text = "%s %s" % (WEEKDAYS_SHORT[self._date.weekday()], self._date.strftime("%d.%m.%Y"))
        self.date_button.setText(text + "  ▾")

    # --- Календарь -----------------------------------------------------------------

    def open_calendar(self) -> None:
        """Календарь всплывает прямо под кнопкой; выбор даты закрывает его."""
        from PySide6.QtCore import QDate, QPoint
        from PySide6.QtWidgets import QCalendarWidget

        popup = QFrame(self, Qt.WindowType.Popup)
        popup.setObjectName("duePopup")
        popup.setStyleSheet(
            "#duePopup { background: %s; border: 1px solid %s; }"
            % (self.colors["surface"], self.colors["border"])
        )
        box = QVBoxLayout(popup)
        box.setContentsMargins(6, 6, 6, 6)
        calendar = QCalendarWidget(popup)
        calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        calendar.setGridVisible(False)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar.setSelectedDate(QDate(self._date.year, self._date.month, self._date.day))

        def picked(day) -> None:
            self.set_date(day.toPython())
            popup.close()

        calendar.clicked.connect(picked)
        calendar.activated.connect(picked)
        box.addWidget(calendar)
        popup.adjustSize()
        popup.move(self.date_button.mapToGlobal(QPoint(0, self.date_button.height() + 2)))
        popup.show()
        calendar.setFocus()
        self._popup = popup
        self._calendar = calendar


def _due_text(task: Task) -> str:
    days = task.days_to_due
    if days is None:
        return ""
    if days < 0:
        return "просрочено на %d дн." % (-days)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return "до %s" % task.due_date.strftime("%d.%m")


def table_due(task: Task) -> str:
    """Срок в колонке таблицы — коротко и капслоком там, где горит."""
    if task.is_done:
        return ("вып %s" % task.done_at.strftime("%d.%m")) if task.done_at else "выполнена"
    if task.is_planned:
        return "старт %s" % task.start_date.strftime("%d.%m")
    if task.is_asap:
        return "ASAP"
    days = task.days_to_due
    if days is None:
        return "\u2014"
    if days < 0:
        return "!ПРОСР %d ДН" % (-days)
    if days == 0:
        return "СЕГОДНЯ"
    if days == 1:
        return "завтра"
    return "%s %s" % (WEEKDAYS_SHORT[task.due_date.weekday()], task.due_date.strftime("%d.%m"))


class ClickLabel(ElidedLabel):
    """Ячейка таблицы, по которой можно щёлкнуть: «jira?», продукт, тревога."""

    clicked = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._active = False

    def make_clickable(self, tooltip: str = "") -> "ClickLabel":
        self._active = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        return self

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._active and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TaskRow(QFrame):
    """Строка таблицы задач: [ ] · ключ · задача · продукт · срок · важность.

    Одна строка — одна задача, как в списке файлов старых оболочек. Выбранная
    строка — инверсия: тёмный текст на светлой плашке. Просроченное горит
    тревожным цветом, ASAP — ярким. Двойной клик открывает карточку задачи.
    """

    toggled = Signal(int, bool)
    activated = Signal(int)
    clicked = Signal(int)
    log_requested = Signal(int)
    jira_requested = Signal(int)      # кликнули по «jira?»
    product_requested = Signal(int)   # кликнули по продукту
    priority_requested = Signal(int, int)  # задача и уровень, выбранный на шкале
    warning_clicked = Signal(int)     # кликнули по тревожной метке

    def __init__(
        self,
        task: Task,
        colors: dict[str, str],
        stale_days: int,
        product_color: str = "",
        show_jira: bool = True,
        subtasks: tuple[int, int] = (0, 0),
        warning: str = "",
        worked_today: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.colors = colors
        self.task = task
        self.stale_days = stale_days
        self.product_color = product_color
        self.show_jira = show_jira
        self.subtasks = subtasks
        # Сегодня по задаче уже отмечали работу — такую строку видно сразу.
        self.worked_today = worked_today
        # Короткая тревожная метка вроде «закрой в jira!»: её ставит тот, кто
        # знает о задаче больше самой строки.
        self.warning = warning
        self._hover = False
        self._selected = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFont(theme.mono_font())
        self._build()
        self._apply_style()

    # --- Построение -----------------------------------------------------------

    def _build(self) -> None:
        c = self.colors
        task = self.task
        cell = cell_width(self.font())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.px(6), theme.px(ROW_PAD), theme.px(6), theme.px(ROW_PAD))
        layout.setSpacing(cell)

        self.check = CheckCircle(task.is_done, c)
        self.check.toggled.connect(lambda state: self.toggled.emit(task.id, state))
        self.check_cell = QWidget()
        self.check_cell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        holder = QHBoxLayout(self.check_cell)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        holder.addStretch(1)
        layout.addWidget(self.check_cell)

        self.mark = QLabel(self._mark_text())
        self.mark.setFont(theme.mono_font())
        if self.worked_today and not task.is_done:
            self.mark.setToolTip("Сегодня по задаче уже была работа")
        layout.addWidget(self.mark)

        self.key = ClickLabel(self._key_text())
        self.key.setFont(theme.mono_font())
        if self._asks_jira():
            self.key.make_clickable("Указать ключ Jira")
            self.key.clicked.connect(lambda: self.jira_requested.emit(task.id))
        layout.addWidget(self.key)

        self.title_cell = QWidget()
        self.title_cell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        title_row = QHBoxLayout(self.title_cell)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(cell)
        self.title = ElidedLabel(task.title)
        title_font = theme.title_font()
        title_font.setStrikeOut(task.is_done)
        self.title.setFont(title_font)
        title_row.addWidget(self.title, 1)
        self.extras = QLabel(self._extras_text())
        self.extras.setFont(theme.mono_font())
        self.extras.setVisible(bool(self.extras.text()))
        title_row.addWidget(self.extras)
        layout.addWidget(self.title_cell, 1)
        self.setToolTip(self._tooltip())

        self.product = ClickLabel(task.product.upper() if task.product else "\u2014")
        self.product.setFont(theme.mono_font())
        self.product.make_clickable("Сменить продукт")
        self.product.clicked.connect(lambda: self.product_requested.emit(task.id))
        layout.addWidget(self.product)

        self.due = ClickLabel(self.warning.upper() if self.warning else table_due(task))
        self.due.setFont(theme.mono_font())
        if self.warning:
            self.due.setText("!ЗАКРОЙ JIRA")
            self.due.make_clickable("Открыть задачу в Jira")
            self.due.clicked.connect(lambda: self.warning_clicked.emit(task.id))
        layout.addWidget(self.due)

        self.priority_bars = None
        if not task.is_done:
            bars = self.priority_bars = PriorityBars(task.priority, c)
            bars.picked.connect(
                lambda level, task_id=task.id: self.priority_requested.emit(task_id, level)
            )
            self.prio_cell = bars
        else:
            self.prio_cell = QLabel("")
        layout.addWidget(self.prio_cell)
        self._fit_columns()

    def _asks_jira(self) -> bool:
        task = self.task
        return (
            self.show_jira and not task.jira_key and not task.is_done
            and task.jira_state != JIRA_NOT_NEEDED
        )

    def _key_text(self) -> str:
        if self.task.jira_key:
            return self.task.jira_key
        if self._asks_jira():
            return "jira?"
        return "\u00b7" * 8

    def _mark_text(self) -> str:
        if self.warning:
            return "!"
        if self.worked_today and not self.task.is_done:
            return "\u221a"
        return ""

    def _extras_text(self) -> str:
        """То, что раньше было метками: подпункты, повтор, тишина."""
        task = self.task
        parts = []
        done, total = self.subtasks
        if total:
            parts.append("%d/%d" % (done, total))
        if task.repeat and not task.is_done and describe_repeat(task.repeat):
            parts.append("\u21bb")
        if not task.is_done and task.is_stale(self.stale_days):
            parts.append("тишина %dд" % task.days_since_activity)
        # Теги в таблицу не идут: место нужнее названию, а теги видны в карточке.
        return " ".join(parts)

    def _tooltip(self) -> str:
        task = self.task
        lines = [task.title]
        details = []
        if self.worked_today and not task.is_done:
            details.append("сегодня была работа")
        due = _due_text(task)
        if due and not task.is_done:
            details.append(due)
        if task.is_asap:
            details.append("ASAP — как можно скорее")
        repeat = describe_repeat(task.repeat)
        if repeat:
            details.append("повтор: " + repeat)
        if task.tags:
            details.append(" ".join("#" + tag for tag in task.tags))
        if details:
            lines.append(" · ".join(details))
        return "\n".join(lines)

    # --- Размеры --------------------------------------------------------------

    def _fit_columns(self) -> None:
        """Ширины колонок — по ширине строки, как у шапки таблицы."""
        layout = self.layout()
        margins = layout.contentsMargins()
        width = self.width() if self.width() > 0 else theme.px(640)
        widths = column_widths(
            width - margins.left() - margins.right(), cell_width(self.font())
        )
        for name, widget in (
            ("check", self.check_cell), ("mark", self.mark), ("key", self.key),
            ("product", self.product), ("due", self.due), ("prio", self.prio_cell),
        ):
            if widths[name] <= 0:
                widget.hide()
            else:
                widget.setFixedWidth(widths[name])
                widget.show()

    def line_height(self) -> int:
        return max(self.fontMetrics().height(), self.check.SIZE)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(theme.px(320), self.line_height() + theme.px(ROW_PAD) * 2)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return False

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        return self.sizeHint().height()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._fit_columns()

    def reset_priority(self) -> None:
        """Возвращает шкалу к уровню задачи: выбор не подтвердили."""
        if self.priority_bars is not None:
            self.priority_bars.set_level(self.task.priority)

    # --- Оформление и события -------------------------------------------------

    def base_color(self) -> str:
        """Цвет строки: тревога, яркий ASAP, тусклые плановые и выполненные."""
        c = self.colors
        task = self.task
        if self.warning:
            return c["danger"]
        if task.is_done:
            return c["text_faint"]
        if task.is_overdue:
            return c["danger"]
        if task.is_planned:
            return c["text_dim"]
        if task.is_asap:
            return c["bright"]
        return c["text"]

    def _apply_style(self, selected: bool = False) -> None:
        c = self.colors
        self._selected = selected
        base = self.base_color()
        if selected:
            ink = c["slab_ink"]
            colors = {name: ink for name in ("mark", "key", "title", "extras", "product", "due")}
        else:
            colors = {
                "mark": c["danger"] if self.warning else c["bright"],
                "key": (c["bright"] if self._asks_jira()
                        else (base if self.task.jira_key else c["faint"])),
                "title": base,
                "extras": c["text_dim"] if not self.task.is_done else c["text_faint"],
                "product": base if self.task.product else c["faint"],
                "due": (c["bright"] if (self.task.days_to_due == 0 and not self.task.is_done
                                        and not self.task.is_overdue) else base),
            }
        for name in colors:
            widget = getattr(self, name)
            widget.setStyleSheet("color: %s; background: transparent;" % colors[name])
        self.check.set_ink(c["slab_ink"] if selected else "")
        if self.priority_bars is not None:
            self.priority_bars.set_ink(c["slab_ink"] if selected else "")
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._apply_style(selected)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not (self._selected or self._hover):
            return
        painter = QPainter(self)
        color = self.colors["accent"] if self._selected else self.colors["ghost"]
        painter.fillRect(self.rect(), theme.qcolor(color))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self.task.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.task.id)
        super().mouseDoubleClickEvent(event)


# Шпаргалка быстрой записи: пара «что написать» — «что получится».
QUICK_HELP = [
    ("!!", "высокий приоритет"),
    ("!!!", "критично"),
    ("@завтра  @пт  @25.12", "срок"),
    ("@кмес", "конец месяца"),
    ("@asap", "как можно скорее"),
    (">15.10  >+14", "начать позже"),
    ("#тег", "метка"),
    ("PROJ-142", "ключ Jira"),
]


class HintPopup(QFrame):
    """Всплывающее окно со шпаргалкой — отдельным окошком, поверх интерфейса."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("hintPopup")
        self.setStyleSheet(
            "#hintPopup { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (colors["surface_alt"], colors["border"], theme.radius("card"))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 12)
        layout.setSpacing(8)

        caption = section_label("шпаргалка быстрой записи")
        layout.addWidget(caption)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(theme.line_extra() + 4)
        layout.addLayout(grid)

        for row, (token, meaning) in enumerate(QUICK_HELP):
            left = QLabel(token)
            left.setFont(theme.mono_font(8))
            left.setStyleSheet("color: %s; background: transparent;" % colors["accent"])
            grid.addWidget(left, row, 0)

            right = QLabel(meaning)
            right.setFont(theme.mono_font(8))
            right.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
            grid.addWidget(right, row, 1)

        note = QLabel("Всё это можно писать прямо в строке новой задачи.")
        note.setFont(theme.mono_font(8))
        note.setWordWrap(True)
        note.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(note)


class HintTrigger(QFrame):
    """Строка «шпаргалка ввода»: занимает одну строку, раскрывается по наведению."""

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setObjectName("hintTrigger")
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._popup: HintPopup | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(8)

        badge = QLabel("?")
        badge.setFont(theme.accent_font(9, bold=True))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(16, 16)
        badge.setStyleSheet(
            "color: %s; background: %s; border-radius: %dpx;"
            % (colors["accent"], theme.tint(colors["accent"], 0.16),
               0 if theme.is_pixel() else 8)
        )
        layout.addWidget(badge)

        title = QLabel("шпаргалка ввода")
        title.setFont(theme.mono_font(8))
        title.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(title)
        layout.addStretch(1)

        self._apply_style(False)

    def _apply_style(self, hover: bool) -> None:
        c = self.colors
        self.setStyleSheet(
            "#hintTrigger { background: %s; border-radius: %dpx; }"
            % (c["surface_alt"] if hover else "transparent", theme.radius("nav"))
        )

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._apply_style(True)
        self.show_popup()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._apply_style(False)
        self.hide_popup()
        super().leaveEvent(event)

    def show_popup(self) -> None:
        if self._popup is None:
            self._popup = HintPopup(self.colors, self)
        popup = self._popup
        popup.adjustSize()
        # Показываем справа от панели, выравнивая по нижнему краю строки.
        corner = self.mapToGlobal(self.rect().topRight())
        popup.move(corner.x() + 10, max(10, corner.y() - popup.height() + self.height()))
        popup.show()
        popup.raise_()

    def hide_popup(self) -> None:
        if self._popup is not None:
            self._popup.hide()


class SubtaskRow(QWidget):
    """Строка чек-листа: отметка, название с правкой на месте и удаление."""

    toggled = Signal(int, bool)
    renamed = Signal(int, str)
    removed = Signal(int)
    moved = Signal(int, int)

    def __init__(self, subtask, colors: dict[str, str], compact: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.subtask = subtask
        self.colors = colors
        self.compact = compact
        clear_background(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.check = CheckCircle(subtask.done, colors)
        self.check.setToolTip("Отметить подпункт")
        self.check.toggled.connect(lambda state: self.toggled.emit(subtask.id, state))
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title = QLineEdit(subtask.title)
        self.title.setProperty("seamless", "true")
        self.title.setFont(theme.ui_font(10))
        # Длинное название иначе показывается «с хвоста»: поле прокручено вправо.
        self.title.setCursorPosition(0)
        # Разрешаем полю сжиматься: иначе в узкой панели строка не помещается.
        self.title.setMinimumWidth(60)
        self.title.setToolTip(subtask.title)
        self.title.editingFinished.connect(self._rename)
        self._apply_done_style()
        layout.addWidget(self.title, 1)

        # В узкой боковой панели стрелки не помещаются — порядок меняют в карточке.
        for text, tip, step in ()  if compact else (("↑", "Выше", -1), ("↓", "Ниже", 1)):
            button = QPushButton(text)
            button.setProperty("tiny", "true")
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, s=step: self.moved.emit(subtask.id, s))
            layout.addWidget(button)

        remove = QPushButton("×")
        remove.setProperty("tiny", "true")
        remove.setToolTip("Удалить подпункт")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda: self.removed.emit(subtask.id))
        layout.addWidget(remove)

    def _apply_done_style(self) -> None:
        c = self.colors
        font = self.title.font()
        font.setStrikeOut(self.subtask.done)
        self.title.setFont(font)
        self.title.setStyleSheet(
            "color: %s; background: transparent;"
            % (c["text_faint"] if self.subtask.done else c["text"])
        )

    def _rename(self) -> None:
        text = self.title.text().strip()
        if text and text != self.subtask.title:
            self.subtask.title = text
            self.title.setToolTip(text)
            self.renamed.emit(self.subtask.id, text)
        elif not text:
            self.title.setText(self.subtask.title)


class SubtaskList(QWidget):
    """Чек-лист подпунктов задачи.

    Умеет работать и до того, как задача сохранена: тогда подпункты копятся в
    памяти, а после создания задачи переносятся в базу методом ``flush``.
    """

    changed = Signal()

    def __init__(self, storage, colors: dict[str, str], task_id=None,
                 compact: bool = False, scroll_height: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.colors = colors
        self.task_id = task_id
        self.compact = compact
        self._pending: list[str] = []
        clear_background(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(section_label("подпункты"))
        head.addStretch(1)
        self.progress = QLabel("")
        self.progress.setFont(theme.accent_font(8))
        self.progress.setStyleSheet(
            "color: %s; background: transparent;" % colors["text_faint"]
        )
        head.addWidget(self.progress)
        layout.addLayout(head)

        rows_host = QWidget()
        clear_background(rows_host)
        self.rows_box = QVBoxLayout(rows_host)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(theme.line_extra() + 3)

        self._area = None
        self._scroll_height = scroll_height
        if scroll_height:
            # Прокручиваем только строки: заголовок со счётчиком и поле ввода
            # должны оставаться на виду, сколько бы подпунктов ни было.
            self._area = QScrollArea()
            self._area.setWidgetResizable(True)
            self._area.setFrameShape(QFrame.Shape.NoFrame)
            self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            clear_background(self._area)
            self._area.setWidget(rows_host)
            layout.addWidget(self._area)
        else:
            layout.addWidget(rows_host)

        self.adder = QLineEdit()
        self.adder.setPlaceholderText("Добавить подпункт — Enter")
        self.adder.setFont(theme.ui_font(10))
        self.adder.returnPressed.connect(self._add)
        layout.addWidget(self.adder)

        self.reload()

    # --- Данные ---------------------------------------------------------------

    def set_task(self, task_id) -> None:
        self.task_id = task_id
        self._pending = []
        self.reload()

    def items(self) -> list:
        """Текущие подпункты: из базы либо ещё не сохранённые."""
        if self.task_id is None:
            from ..models import Subtask

            return [
                Subtask(id=-index - 1, title=title, position=index)
                for index, title in enumerate(self._pending)
            ]
        return self.storage.list_subtasks(self.task_id)

    def flush(self, task_id: int) -> None:
        """Переносит накопленные подпункты в только что созданную задачу."""
        for title in self._pending:
            self.storage.add_subtask(task_id, title)
        self._pending = []
        self.task_id = task_id
        self.reload()

    def reload(self) -> None:
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        items = self.items()
        done = sum(1 for item in items if item.done)
        self.progress.setText("%d из %d" % (done, len(items)) if items else "")

        for subtask in items:
            row = SubtaskRow(subtask, self.colors, self.compact)
            row.toggled.connect(self._toggle)
            row.renamed.connect(self._rename)
            row.removed.connect(self._remove)
            row.moved.connect(self._move)
            self.rows_box.addWidget(row)
        self._fit_area(len(items))

    def _fit_area(self, count: int) -> None:
        """Подгоняет высоту области под число строк, но не выше предела.

        Без явной высоты раскладка сжимает список до двух строк, а с фиксированной
        у короткого чек-листа оставалась бы пустота.
        """
        if self._area is None:
            return
        row_height = 26
        first = self.rows_box.itemAt(0)
        if first is not None and first.widget() is not None:
            row_height = max(row_height, first.widget().sizeHint().height())
        spacing = self.rows_box.spacing()
        wanted = count * row_height + max(0, count - 1) * spacing + 4
        self._area.setFixedHeight(max(28, min(self._scroll_height, wanted)))

    # --- Действия -------------------------------------------------------------

    def _add(self) -> None:
        title = self.adder.text().strip()
        if not title:
            return
        if self.task_id is None:
            self._pending.append(title)
        else:
            self.storage.add_subtask(self.task_id, title)
        self.adder.clear()
        self.reload()
        self.changed.emit()

    def _toggle(self, subtask_id: int, done: bool) -> None:
        if self.task_id is None:
            return  # у несохранённой задачи отмечать ещё нечего
        self.storage.set_subtask_done(subtask_id, done)
        self.reload()
        self.changed.emit()

    def _rename(self, subtask_id: int, title: str) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            if 0 <= index < len(self._pending):
                self._pending[index] = title
        else:
            self.storage.rename_subtask(subtask_id, title)
        self.changed.emit()

    def _remove(self, subtask_id: int) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            if 0 <= index < len(self._pending):
                self._pending.pop(index)
        else:
            self.storage.delete_subtask(subtask_id)
        self.reload()
        self.changed.emit()

    def _move(self, subtask_id: int, step: int) -> None:
        if self.task_id is None:
            index = -subtask_id - 1
            target = index + step
            if 0 <= index < len(self._pending) and 0 <= target < len(self._pending):
                self._pending[index], self._pending[target] = (
                    self._pending[target],
                    self._pending[index],
                )
        else:
            self.storage.move_subtask(subtask_id, step)
        self.reload()
        self.changed.emit()


class NavItem(QFrame):
    """Пункт меню разделов: «► Все активные ........ 19».

    Выбранный пункт — инверсия во всю ширину, как подсвеченная строка в
    текстовом меню; просроченное горит тревожным цветом.
    """

    clicked = Signal()

    def __init__(self, title: str, colors: dict[str, str], accent: str = "",
                 tint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.accent = accent
        # Свой цвет названия: им выделены разделы, которые важнее прочих.
        self.tint = tint
        self._active = False
        self._alert = False
        self._hover = False
        self.setObjectName("navItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        horizontal, vertical = theme.nav_padding()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(horizontal, vertical, horizontal, vertical)
        layout.setSpacing(theme.px(6))

        self.mark = QLabel(" ")
        self.mark.setFont(theme.mono_font())
        self.mark.setFixedWidth(cell_width(self.mark.font()))
        layout.addWidget(self.mark)

        self.title = ElidedLabel(title)
        self.title.setFont(theme.mono_font())
        self.title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.title, 0)

        self.leader = FillGlyph(".", colors["faint"], 0.45)
        layout.addWidget(self.leader, 1)

        self.count = QLabel("")
        self.count.setFont(theme.mono_font())
        layout.addWidget(self.count)

        self.set_active(False)

    def set_count(self, value: int) -> None:
        self.count.setText(str(value) if value else "")

    def set_alert(self, alert: bool) -> None:
        """Тревожный цвет — у раздела, где что-то горит (просрочка)."""
        if alert != self._alert:
            self._alert = alert
            self._restyle()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._restyle()

    def is_active(self) -> bool:
        return self._active

    def _restyle(self) -> None:
        c = self.colors
        if self._active:
            ink = c["slab_ink"]
        elif self._alert:
            ink = c["danger"]
        else:
            ink = self.tint or c["text"]
        self.mark.setText("\u25ba" if self._active else " ")
        for label in (self.mark, self.title, self.count):
            label.setStyleSheet("color: %s; background: transparent;" % ink)
        self.leader.set_color(ink)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not (self._active or self._hover):
            return
        painter = QPainter(self)
        color = self.colors["accent"] if self._active else self.colors["ghost"]
        painter.fillRect(self.rect(), theme.qcolor(color))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)


class StatChip(QWidget):
    """Счётчик в шапке: крупное число и подпись капслоком."""

    clicked = Signal()

    def __init__(self, caption: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.value = QLabel("0")
        self.value.setFont(theme.mono_font(13, bold=True))
        self.value.setStyleSheet("color: %s; background: transparent;" % colors["text"])
        layout.addWidget(self.value)

        self.caption = QLabel(caption.upper())
        self.caption.setFont(theme.mono_font(7, spacing=1.2))
        self.caption.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(self.caption)

        self.underline = QFrame()
        self.underline.setFixedHeight(2)
        self.underline.setStyleSheet("background: transparent; border-radius: 1px;")
        layout.addWidget(self.underline)

        self._color = colors["text"]

    def set_value(self, value: int, highlight: str = "") -> None:
        self.value.setText(str(value))
        self._color = highlight or self.colors["text"]
        color = self._color if value else self.colors["text_faint"]
        self.value.setStyleSheet("color: %s; background: transparent;" % color)

    def set_active(self, active: bool) -> None:
        """Подчёркиванием показываем, что список отфильтрован по этому счётчику."""
        self.underline.setStyleSheet(
            "background: %s; border-radius: 1px;" % (self._color if active else "transparent")
        )
        self.caption.setStyleSheet(
            "color: %s; background: transparent;"
            % (self.colors["text_dim"] if active else self.colors["text_faint"])
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)


class ReminderRow(Card):
    """Напоминание в списке: отметка, текст и время.

    Отдельно от задач: напоминание не работа, отчитываться по нему не нужно,
    поэтому ни важности, ни продукта, ни Jira у него нет.
    """

    toggled = Signal(int, bool)
    activated = Signal(int)
    clicked = Signal(int)     # выбрать напоминание — подробности справа

    def __init__(self, reminder, colors: dict[str, str], parent=None) -> None:
        super().__init__(colors, parent)
        self.reminder = reminder
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if reminder.is_past and not reminder.done:
            self.set_bar(colors["accent"])

        inner = QHBoxLayout(self)
        gap = theme.line_extra()
        inner.setContentsMargins(16, 11 + gap // 2, 14, 11 + gap // 2)
        inner.setSpacing(12)

        self.check = CheckCircle(reminder.done, colors)
        self.check.toggled.connect(lambda state: self.toggled.emit(reminder.id, state))
        inner.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(7 + theme.line_extra())
        inner.addLayout(column, 1)

        self.title = QLabel(reminder.title)
        self.title.setWordWrap(True)
        font = theme.title_font()
        font.setStrikeOut(reminder.done)
        self.title.setFont(font)
        self.title.setStyleSheet(
            "color: %s; background: transparent; %s"
            % (colors["text_faint"] if reminder.done else colors["text"],
               theme.title_css())
        )
        column.addWidget(self.title)

        self.meta = FlowLayout(spacing=6)
        when = describe_when(reminder.at)
        overdue = reminder.is_past and not reminder.done
        self.meta.addWidget(
            Pill(when, colors["accent"] if overdue else colors["text_dim"], strong=overdue)
        )
        if reminder.event_id:
            self.meta.addWidget(Pill("в календаре", colors["info"]))
        if reminder.notes.strip():
            note = " ".join(reminder.notes.split())
            self.meta.addWidget(
                Pill(note[:40] + ("…" if len(note) > 40 else ""), colors["text_faint"])
            )
        column.addLayout(self.meta)

    # --- Размеры --------------------------------------------------------------

    def _text_width(self, width: int) -> int:
        layout = self.layout()
        margins = layout.contentsMargins()
        return (
            width - margins.left() - margins.right()
            - self.check.width() - layout.spacing()
        )

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        text_width = self._text_width(width)
        if text_width <= 0:
            return super().heightForWidth(width)
        column = wrapped_height(self.title, text_width)
        column += self.layout().spacing() + self.meta.heightForWidth(text_width)
        margins = self.layout().contentsMargins()
        return margins.top() + max(column, self.check.height()) + margins.bottom()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        fit_title(self.title, self._text_width(self.width()))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self.reminder.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.reminder.id)
        super().mouseDoubleClickEvent(event)


class GoalCard(Card):
    """Цель квартала над списком задач.

    Жёлтая — чтобы её нельзя было спутать с задачей и чтобы взгляд цеплялся:
    задача про сегодня, цель про весь квартал.
    """

    activated = Signal(int)   # открыть цель
    clicked = Signal(int)     # выбрать цель — подробности уйдут в правую панель
    toggled = Signal(int, bool)

    def __init__(self, goal, colors: dict[str, str], progress: tuple[int, int] = (0, 0),
                 parent=None) -> None:
        super().__init__(colors, parent)
        self.goal = goal
        self.progress = progress
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_bar(colors["warning"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        # Тот же зазор, что у задачи между названием и метками, плюс пара
        # пикселей: заголовок цели крупнее и жирнее, и вплотную к меткам он
        # выглядел склеенным.
        layout.setSpacing(9 + theme.line_extra())

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)

        self.check = CheckCircle(goal.is_done, colors)
        self.check.toggled.connect(lambda state: self.toggled.emit(goal.id, state))
        head.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        self.title = QLabel(goal.title)
        self.title.setWordWrap(True)
        font = theme.title_font(bold=True)
        font.setStrikeOut(goal.is_done)
        self.title.setFont(font)
        self.title.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.title.setStyleSheet(
            "color: %s; background: transparent; %s"
            % (colors["text_faint"] if goal.is_done else colors["warning"],
               theme.title_css(bold=True))
        )
        head.addWidget(self.title, 1)
        layout.addLayout(head)

        done, total = progress
        self.meta = FlowLayout(spacing=6)
        self.meta.addWidget(Pill("цель квартала", colors["warning"], strong=True))
        if total:
            self.meta.addWidget(
                Pill(
                    "%d/%d" % (done, total),
                    colors["success"] if done >= total else colors["text_dim"],
                    strong=done >= total,
                )
            )
        layout.addLayout(self.meta)

        self.note = None
        if goal.comment.strip():
            # Комментарий к цели бывает длинным, а карточка — вывеска: первые
            # полторы строки и есть то, что нужно увидеть сразу.
            text = " ".join(goal.comment.split())
            if len(text) > 140:
                text = text[:139].rstrip() + "…"
            self.note = QLabel(text)
            self.note.setWordWrap(True)
            self.note.setFont(theme.mono_font(8))
            self.note.setStyleSheet(
                "color: %s; background: transparent;" % colors["text_dim"]
            )
            self.note.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            layout.addWidget(self.note)

    # --- Размеры --------------------------------------------------------------

    def _text_width(self, width: int) -> int:
        """Сколько остаётся тексту после полей и круглой отметки."""
        layout = self.layout()
        margins = layout.contentsMargins()
        return width - margins.left() - margins.right()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        """Высота карточки при такой ширине.

        Считаем сами: у цели длинное название переносится на две-три строки,
        а вложенная раскладка отмеряла ему одну — текст обрезался.
        """
        text_width = self._text_width(width)
        if text_width <= 0:
            return super().heightForWidth(width)
        layout = self.layout()
        margins = layout.contentsMargins()
        # В первой строке рядом с названием стоит отметка.
        head = max(
            wrapped_height(self.title, text_width - self.check.width() - 10),
            self.check.height(),
        )
        total = head + layout.spacing() + self.meta.heightForWidth(text_width)
        if self.note is not None:
            total += layout.spacing() + wrapped_height(self.note, text_width)
        return margins.top() + total + margins.bottom()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        fit_title(self.title, self._text_width(self.width()) - self.check.width() - 10)
        if self.note is not None:
            fit_title(self.note, self._text_width(self.width()))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit(self.goal.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.goal.id)
        super().mouseDoubleClickEvent(event)


class GoalResultList(QWidget):
    """Контрольные результаты цели — тот же чек-лист, что у подпунктов задачи."""

    changed = Signal()

    def __init__(self, storage, colors: dict[str, str], goal_id=None, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.colors = colors
        self.goal_id = goal_id
        self._pending: list[str] = []
        clear_background(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(section_label("контрольные результаты"))
        head.addStretch(1)
        self.progress = QLabel("")
        self.progress.setFont(theme.accent_font(8))
        self.progress.setStyleSheet(
            "color: %s; background: transparent;" % colors["text_faint"]
        )
        head.addWidget(self.progress)
        layout.addLayout(head)

        rows_host = QWidget()
        clear_background(rows_host)
        self.rows_box = QVBoxLayout(rows_host)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(theme.line_extra() + 3)
        layout.addWidget(rows_host)

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Что должно получиться — и Enter")
        self.input.returnPressed.connect(self._add)
        add_row.addWidget(self.input, 1)
        layout.addLayout(add_row)

        self.reload()

    # --- Данные ---------------------------------------------------------------

    def items(self) -> list:
        if self.goal_id is None:
            return []
        return self.storage.list_goal_results(self.goal_id)

    def flush(self, goal_id: int) -> None:
        """Переносит в базу то, что набрали до сохранения новой цели."""
        self.goal_id = goal_id
        for title in self._pending:
            self.storage.add_goal_result(goal_id, title)
        self._pending.clear()
        self.reload()

    def reload(self) -> None:
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        rows = self.items()
        if self.goal_id is None:
            for position, title in enumerate(self._pending):
                self.rows_box.addWidget(self._pending_row(position, title))
            done, total = 0, len(self._pending)
        else:
            for result in rows:
                self.rows_box.addWidget(self._row(result))
            done = sum(1 for r in rows if r.done)
            total = len(rows)

        self.progress.setText("%d/%d" % (done, total) if total else "")

    # --- Строки ---------------------------------------------------------------

    def _row(self, result) -> QWidget:
        holder = QWidget()
        clear_background(holder)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        mark = CheckCircle(result.done, self.colors)
        mark.toggled.connect(
            lambda state, rid=result.id: self._set_done(rid, state)
        )
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)

        label = QLabel(result.title)
        label.setWordWrap(True)
        font = theme.ui_font(10)
        font.setStrikeOut(result.done)
        label.setFont(font)
        label.setStyleSheet(
            "color: %s; background: transparent;"
            % (self.colors["text_faint"] if result.done else self.colors["text"])
        )
        row.addWidget(label, 1)

        remove = QPushButton("×")
        remove.setProperty("flat", "true")
        remove.setFixedWidth(26)
        remove.setToolTip("Убрать результат")
        remove.clicked.connect(lambda _=False, rid=result.id: self._delete(rid))
        row.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        return holder

    def _pending_row(self, position: int, title: str) -> QWidget:
        holder = QWidget()
        clear_background(holder)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        label = QLabel("• " + title)
        label.setWordWrap(True)
        label.setFont(theme.ui_font(10))
        label.setStyleSheet(
            "color: %s; background: transparent;" % self.colors["text_dim"]
        )
        row.addWidget(label, 1)

        remove = QPushButton("×")
        remove.setProperty("flat", "true")
        remove.setFixedWidth(26)
        remove.clicked.connect(lambda _=False, index=position: self._forget(index))
        row.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        return holder

    # --- Действия -------------------------------------------------------------

    def _add(self) -> None:
        title = self.input.text().strip()
        if not title:
            return
        if self.goal_id is None:
            self._pending.append(title)
        else:
            self.storage.add_goal_result(self.goal_id, title)
        self.input.clear()
        self.reload()
        self.changed.emit()

    def _set_done(self, result_id: int, done: bool) -> None:
        self.storage.set_goal_result_done(result_id, done)
        self.reload()
        self.changed.emit()

    def _delete(self, result_id: int) -> None:
        self.storage.delete_goal_result(result_id)
        self.reload()
        self.changed.emit()

    def _forget(self, index: int) -> None:
        if 0 <= index < len(self._pending):
            self._pending.pop(index)
            self.reload()
            self.changed.emit()


class JiraIssueRow(Card):
    """Строка задачи, прочитанной из Jira: ключ, название, статус, срок.

    Это не наша задача, а зеркало чужой: отметить выполненной её нельзя, зато
    можно открыть в браузере или взять к себе в список.
    """

    activated = Signal(str)   # ключ — открыть в браузере
    take = Signal(str)        # ключ — завести локальную задачу

    def __init__(self, issue, colors: dict[str, str], already: bool = False, parent=None) -> None:
        super().__init__(colors, parent)
        self.issue = issue
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(7)

        self.title = QLabel(issue.summary or issue.key)
        self.title.setWordWrap(True)
        self.title.setFont(theme.title_font())
        # Шрифт прописан и в стилях метки: иначе общая таблица стилей нарисует
        # текст шире, чем посчитана высота строки, и вторая строка обрежется.
        self.title.setStyleSheet(
            "color: %s; background: transparent; %s" % (colors["text"], theme.title_css())
        )
        layout.addWidget(self.title)

        # Переносимый ряд, а не жёсткая строка: в узком окне метки уходили за
        # край вместе с кнопкой.
        self.meta = FlowLayout(spacing=6)
        self.meta.addWidget(Pill(issue.key, colors["info"]))
        if issue.status:
            self.meta.addWidget(Pill(issue.status.lower(), colors["text_dim"]))
        if issue.due_date:
            overdue = issue.due_date < date.today()
            self.meta.addWidget(
                Pill(
                    "срок %s" % issue.due_date.strftime("%d.%m"),
                    colors["danger"] if overdue else colors["text_dim"],
                    strong=overdue,
                )
            )
        if issue.priority:
            self.meta.addWidget(Pill(issue.priority.lower(), colors["text_faint"]))
        if issue.resolved:
            self.meta.addWidget(
                Pill("закрыта %s" % issue.resolved.strftime("%d.%m"), colors["success"])
            )

        closed = bool(issue.resolved) or (issue.status_category or "").lower() == "done"
        button = QPushButton("Отметить у себя" if closed else "Взять в работу")
        button.setToolTip(
            "Завести задачу сразу выполненной" if closed
            else "Завести такую же задачу в своём списке"
        )
        button.setProperty("flat", "true")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.take.emit(issue.key))
        self.meta.addWidget(button)
        layout.addLayout(self.meta)

    # --- Размеры --------------------------------------------------------------

    def _text_width(self, width: int) -> int:
        margins = self.layout().contentsMargins()
        return width - margins.left() - margins.right()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        text_width = self._text_width(width)
        if text_width <= 0:
            return super().heightForWidth(width)
        layout = self.layout()
        margins = layout.contentsMargins()
        body = (
            wrapped_height(self.title, text_width)
            + layout.spacing()
            + self.meta.heightForWidth(text_width)
        )
        return margins.top() + body + margins.bottom()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        fit_title(self.title, self._text_width(self.width()))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.activated.emit(self.issue.key)
        super().mouseDoubleClickEvent(event)


class PriorityBars(QWidget):
    """Важность задачи пятью клетками: «███░░» — заполнено столько, сколько горит.

    Полные блоки читаются издалека; пустые клетки только намечены, чтобы было
    видно, докуда можно дотянуть. Клик по клетке задаёт уровень, но саму
    задачу не меняет: строка лишь сообщает о желании, а спрашивает и
    сохраняет уже окно.
    """

    picked = Signal(int)   # выбранный уровень, 0..PRIORITY_LEVELS - 1

    FULL = "\u2588"
    EMPTY = "\u2591"

    def __init__(self, level: int, colors: dict[str, str], editable: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.level = max(0, min(PRIORITY_LEVELS - 1, int(level)))
        self.editable = editable
        self._hover = -1
        self._ink = ""
        self.setFont(theme.mono_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(PRIORITY_LEVELS * self.cell(), self.fontMetrics().height())
        marks = "%d из %d" % (self.level + 1, PRIORITY_LEVELS)
        name = PRIORITY_LABELS.get(self.level, "")
        if editable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMouseTracking(True)
            self.setToolTip(
                "Важность: %s (%s). Кликните по клетке, чтобы изменить" % (name, marks)
            )
        else:
            self.setToolTip("Важность: %s (%s)" % (name, marks))

    def cell(self) -> int:
        return max(1, self.fontMetrics().horizontalAdvance(self.FULL))

    def set_level(self, level: int) -> None:
        self.level = max(0, min(PRIORITY_LEVELS - 1, int(level)))
        self.update()

    def set_ink(self, color: str) -> None:
        """Один цвет для всех клеток — поверх инверсной строки."""
        self._ink = color
        self.update()

    def filled(self) -> int:
        """Сколько клеток закрашено сейчас (с учётом наведения)."""
        shown = self._hover if self._hover >= 0 else self.level
        return shown + 1

    def text(self) -> str:
        """Шкала знаками — так её удобно проверять."""
        filled = self.filled()
        return self.FULL * filled + self.EMPTY * (PRIORITY_LEVELS - filled)

    def _index_at(self, x: int) -> int:
        return max(0, min(PRIORITY_LEVELS - 1, int(x) // self.cell()))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        shown = self._hover if self._hover >= 0 else self.level
        color = theme.qcolor(self._ink or c[theme.PRIORITY_COLOR_KEYS.get(shown, "text")])
        metrics = self.fontMetrics()
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        filled = shown + 1
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(color)
        painter.drawText(0, baseline, self.FULL * filled)
        empty = QColor(color)
        empty.setAlphaF(0.35)
        painter.setPen(empty)
        painter.drawText(filled * self.cell(), baseline, self.EMPTY * (PRIORITY_LEVELS - filled))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self._index_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.editable:
            index = self._index_at(event.position().x())
            if index != self._hover:
                self._hover = index
                self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._hover >= 0:
            self._hover = -1
            self.update()
        super().leaveEvent(event)


# --- ASCII по клеткам ---------------------------------------------------------
# Пиксельные шрифты не моноширинные: у «#» и пробела разная ширина, и любой
# рисунок из символов расползается. Поэтому символы расставляются по клеткам
# вручную — так ASCII держит строй в любом шрифте.

ASCII_FULL = "#"      # запасные знаки на случай, если в системе нет ни одного
ASCII_HALF = ":"      # шрифта с рамками и столбиками
ASCII_BASE = "_"


def chart_glyphs() -> tuple[str, str, str]:
    """Полная клетка, половинка и основание — лучшее, что нашлось в системе."""
    return theme.glyph("full"), theme.glyph("half"), theme.glyph("base")


def ascii_chart(values: list[int], rows: int = 4) -> list[str]:
    """Столбиковая диаграмма из символов: один столбец — одно значение.

    Последняя строка — основание: без него столбики висят в воздухе и ряд
    пустых дней не читается.
    """
    full, half, base = chart_glyphs()
    width = len(values)
    top = max(values) if values else 0
    if width == 0:
        return []
    if top <= 0:
        return [" " * width for _ in range(rows)] + [base * width]

    lines = []
    for row in range(rows, 0, -1):
        line = ""
        for value in values:
            height = value / top * rows
            if height >= row:
                line += full
            elif height >= row - 0.5:
                line += half
            else:
                line += " "
        lines.append(line)
    lines.append(base * width)
    return lines


def ascii_readout(label: str, value: str, width: int) -> str:
    """Строка сводки: подпись, отточие и число у правого края."""
    label, value = label.upper(), str(value)
    dots = max(1, width - len(label) - len(value) - 2)
    return "%s %s %s" % (label, theme.glyph("dot") * dots, value)


def ascii_frame(lines: list[str], width: int = 0) -> list[str]:
    """Обводит текст рамкой: линиями, если шрифт их знает, иначе плюсами."""
    width = max([width] + [len(line) for line in lines])
    horizontal = theme.glyph("line_h") * (width + 2)
    vertical = theme.glyph("line_v")
    top = theme.glyph("corner_tl") + horizontal + theme.glyph("corner_tr")
    bottom = theme.glyph("corner_bl") + horizontal + theme.glyph("corner_br")
    body = [
        "%s %-*s %s" % (vertical, width, line, vertical) for line in lines
    ]
    return [top] + body + [bottom]


class GridText(QWidget):
    """Текст по сетке, как на терминале: каждый символ в своей клетке.

    Цвет можно задать и всей строке, и отдельным символам — так столбики
    диаграммы горят акцентом, а основание остаётся тихой линией.
    """

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._lines: list[tuple[str, str]] = []
        self._ink: dict[str, str] = {}
        self._fonts: dict[str, QFont] = {}
        self.setFont(theme.mono_font(8))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Размер считается по сетке: раскладка не должна ни растягивать рисунок,
        # ни обрезать последнюю строку.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_ink(self, ink: dict[str, str]) -> None:
        """Свой цвет для отдельных символов: {«#»: акцент, «_»: рамка}."""
        self._ink = dict(ink)
        self.update()

    def set_lines(self, lines: list[tuple[str, str]]) -> None:
        self._lines = list(lines)
        self._fit()

    def _fit(self) -> None:
        """Просит у раскладки ровно столько места, сколько занимает сетка."""
        self._fonts.clear()
        self.setMinimumSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Шрифт виджету достаётся дважды: сначала свой, потом из таблицы
        # стилей. Со вторым меняется размер клетки — его надо пересчитать,
        # иначе у рисунка обрезается то правый край, то нижняя строка.
        if event.type() == QEvent.Type.FontChange:
            self._fit()
        super().changeEvent(event)

    def text(self) -> str:
        """Весь рисунок одной строкой — так его удобно проверять."""
        return "\n".join(line for line, _ in self._lines)

    def cell_width(self) -> int:
        """Ширина клетки — по самому широкому символу рисунка.

        Кириллица в пиксельных шрифтах шире латиницы: если мерить по «_»,
        широкие буквы вылезают за свою клетку, и правый край обрезается.
        """
        used = {char for line, _ in self._lines for char in line}
        widths = [self.fontMetrics().horizontalAdvance("0")]
        for char in used:
            widths.append(QFontMetrics(self._font_for(char)).horizontalAdvance(char))
        return max(widths)

    def line_height(self) -> int:
        return self.fontMetrics().height() + theme.line_extra()

    def columns(self) -> int:
        return max([0] + [len(line) for line, _ in self._lines])

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(
            self.columns() * self.cell_width(),
            max(1, len(self._lines)) * self.line_height(),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return self.sizeHint()

    def _font_for(self, char: str) -> QFont:
        """Шрифт для знака: свой, а для рамок и столбиков — запасной."""
        if char not in self._fonts:
            family = theme.glyph_family(char, self.font().family())
            if family == self.font().family():
                self._fonts[char] = self.font()
            else:
                font = QFont(self.font())
                font.setFamily(family)
                self._fonts[char] = font
        return self._fonts[char]

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self._lines:
            return
        painter = QPainter(self)
        metrics = self.fontMetrics()
        cell, step = self.cell_width(), self.line_height()
        baseline = metrics.ascent() + theme.line_extra() // 2
        for row, (line, color) in enumerate(self._lines):
            y = row * step + baseline
            for column, char in enumerate(line):
                if char == " ":
                    continue
                font = self._font_for(char)
                painter.setFont(font)
                # Цвет строки может быть списком — тогда у каждой клетки свой.
                if isinstance(color, (list, tuple)):
                    ink = color[column] if column < len(color) else color[-1]
                else:
                    ink = self._ink.get(char, color)
                painter.setPen(theme.qcolor(ink))
                shift = (cell - QFontMetrics(font).horizontalAdvance(char)) // 2
                painter.drawText(column * cell + shift, y, char)
        painter.end()


class DayProgress(QWidget):
    """Пиксельная шкала: сколько задач сегодня уже отмечено."""

    SEGMENTS = 8
    BLOCK = 7
    GAP = 3

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._filled = 0
        self._complete = False
        self.block, self.gap = theme.px(self.BLOCK), theme.px(self.GAP)
        self.setFixedSize(
            self.SEGMENTS * self.block + (self.SEGMENTS - 1) * self.gap, theme.px(12)
        )

    def set_values(self, done: int, total: int, complete: bool = False) -> None:
        share = 0.0 if total <= 0 else min(1.0, done / total)
        # Хотя бы один сегмент, если работа была: иначе прогресс не видно.
        self._filled = self.SEGMENTS if complete else (
            max(1, round(share * self.SEGMENTS)) if done else 0
        )
        self._complete = complete
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        c = self.colors
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        active = QColor(c["success"] if self._complete else c["accent"])
        empty = QColor(c["border"])
        for index in range(self.SEGMENTS):
            x = index * (self.block + self.gap)
            painter.setBrush(active if index < self._filled else empty)
            painter.drawRect(x, 1, self.block, self.height() - 2)
        painter.end()


class DayIndicator(QWidget):
    """Шапка: дата, время и то, как идёт работа за сегодня."""

    clicked = Signal()

    def __init__(self, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Открыть отчёт за день")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.date = QLabel()
        self.date.setFont(theme.mono_font(8))
        self.date.setStyleSheet("color: %s; background: transparent;" % colors["text_faint"])
        layout.addWidget(self.date)

        self.time = QLabel()
        self.time.setFont(theme.accent_font(12, bold=True))
        self.time.setStyleSheet("color: %s; background: transparent;" % colors["accent"])
        layout.addWidget(self.time)

        self.progress = DayProgress(colors)
        layout.addWidget(self.progress)

        self.caption = QLabel()
        self.caption.setFont(theme.mono_font(8))
        self.caption.setStyleSheet("color: %s; background: transparent;" % colors["text_dim"])
        layout.addWidget(self.caption)

        # Подписи не должны сжиматься: в узкой шапке они обрезались бы.
        for label in (self.date, self.time, self.caption):
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.caption.setMinimumWidth(
            self.caption.fontMetrics().horizontalAdvance("отмечено 00 из 00") + 4
        )

    def set_clock(self, moment) -> None:
        weekday = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][moment.weekday()]
        self.date.setText("%s %s" % (weekday, moment.strftime("%d.%m")))
        self.time.setText(moment.strftime("%H:%M"))

    def set_day(self, done: int, total: int, report_saved: bool) -> None:
        self.progress.set_values(done, total, report_saved)
        if report_saved:
            self.caption.setText("отчёт готов")
            color = self.colors["success"]
        elif done:
            self.caption.setText("отмечено %d из %d" % (done, max(total, done)))
            color = self.colors["text_dim"]
        else:
            self.caption.setText("пока пусто")
            color = self.colors["text_faint"]
        self.caption.setStyleSheet("color: %s; background: transparent;" % color)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.clicked.emit()
        super().mousePressEvent(event)
