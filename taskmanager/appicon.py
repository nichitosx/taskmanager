"""Иконка приложения. Рисуется кодом — внешних файлов с картинками нет.

Отсюда её берут и окно с треем, и генератор .ico для ярлыков Windows.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = "#D97757"
BACKGROUND = "#131211"
MUTED = "#6B665F"


def _rounded(painter: QPainter, x, y, w, h, radius) -> None:
    painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)


def make_pixmap(size: int = 64, accent: str = ACCENT, background: str = BACKGROUND) -> QPixmap:
    """Иконка приложения: плашка со списком и галочкой.

    Для мелких размеров рисуем по пиксельной сетке без сглаживания — иначе на
    16×16 всё превращается в мутное пятно. Крупные рисуем векторно.
    """
    if size <= 32:
        return make_pixel_pixmap(size, accent, background)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64.0, size / 64.0)
    painter.setPen(Qt.PenStyle.NoPen)

    # Плашка с тонкой акцентной обводкой — иконка не сливается с тёмным фоном.
    painter.setBrush(QColor(background))
    _rounded(painter, 2, 2, 60, 60, 14)
    painter.setPen(QPen(QColor(accent), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _rounded(painter, 3, 3, 58, 58, 13)
    painter.setPen(Qt.PenStyle.NoPen)

    # Две строки списка и крупная галочка поверх — узнаётся даже мелко.
    painter.setBrush(QColor(MUTED))
    _rounded(painter, 14, 20, 22, 5, 2.5)
    _rounded(painter, 14, 31, 14, 5, 2.5)

    check = QPainterPath()
    check.moveTo(15, 44)
    check.lineTo(25, 53)
    check.lineTo(50, 20)
    pen = QPen(QColor(accent), 7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(check)
    painter.end()
    return pixmap


def make_pixel_pixmap(size: int = 64, accent: str = ACCENT, background: str = BACKGROUND) -> QPixmap:
    """Пиксель-арт вариант: рисуем в сетке 16×16 и увеличиваем без сглаживания."""
    base = QPixmap(16, 16)
    base.fill(Qt.GlobalColor.transparent)
    painter = QPainter(base)
    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(QColor(background))
    painter.drawRect(0, 0, 16, 16)
    painter.setBrush(QColor(accent))
    for x, y, w, h in ((1, 0, 14, 1), (1, 15, 14, 1), (0, 1, 1, 14), (15, 1, 1, 14)):
        painter.drawRect(x, y, w, h)

    painter.setBrush(QColor(MUTED))
    painter.drawRect(3, 4, 7, 2)
    painter.drawRect(3, 8, 4, 2)

    # Галочка по клеткам: три ступеньки вниз и четыре вверх.
    painter.setBrush(QColor(accent))
    for x, y in ((3, 10), (4, 11), (5, 12), (6, 11), (7, 10), (8, 9), (9, 8), (10, 7), (11, 6)):
        painter.drawRect(x, y, 2, 2)
    painter.end()

    return base.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def make_icon(
    accent: str = ACCENT, background: str = BACKGROUND, pixel: bool = False
) -> QIcon:
    draw = make_pixel_pixmap if pixel else make_pixmap
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw(size, accent, background))
    return icon


def write_check(path: Path, color: str = "#FFFFFF", size: int = 16) -> Path:
    """Рисует галочку в PNG — её подставляет таблица стилей в QCheckBox.

    Qt не умеет рисовать «птичку» в стилизованном чекбоксе сам: без картинки
    отметка выглядит просто залитым квадратом.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 16.0, size / 16.0)
    pen = QPen(QColor(color), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    path_ = QPainterPath()
    path_.moveTo(3.6, 8.4)
    path_.lineTo(6.6, 11.4)
    path_.lineTo(12.4, 4.8)
    painter.drawPath(path_)
    painter.end()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    return path


def _png_bytes(size: int, accent: str, background: str) -> bytes:
    # QBuffer без аргумента держит данные внутри себя: передавать сюда временный
    # QByteArray нельзя — он будет уничтожен раньше буфера.
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    make_pixmap(size, accent, background).save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


def write_ico(path: Path, accent: str = ACCENT, background: str = BACKGROUND) -> Path:
    """Собирает .ico из PNG-кадров вручную.

    Qt не гарантирует запись .ico на всех сборках, а формат простой: заголовок,
    таблица кадров и сами PNG подряд. Windows понимает PNG внутри .ico начиная
    с Vista, так что этого достаточно.
    """
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [(size, _png_bytes(size, accent, background)) for size in sizes]

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    for size, blob in frames:
        dimension = 0 if size >= 256 else size  # 0 в формате означает 256
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(blob), offset
        )
        offset += len(blob)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(blob for _, blob in frames))
    return path


def write_pattern(path: Path, base: str, ink: str, alpha: int = 12) -> Path:
    """Плитка фона для пиксельного стиля: тонкие горизонтальные полоски.

    Раньше здесь была сетка из крестиков — на большом окне она читалась как шум.
    Полоска раз в четыре пикселя даёт ту же «не плоскую» поверхность, но глаз за
    неё не цепляется.
    """
    tile = QPixmap(4, 4)
    tile.fill(QColor(base))
    painter = QPainter(tile)
    line = QColor(ink)
    line.setAlpha(max(0, min(255, alpha)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(line)
    painter.drawRect(0, 0, 4, 1)
    painter.end()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tile.save(str(path), "PNG")
    return path


def make_watermark(size: int = 120, color: str = MUTED, alpha: int = 46) -> QPixmap:
    """Крупный полупрозрачный пиксель-рисунок для пустых экранов.

    Планшет со списком и галочкой: рисуется в сетке 16×16 и увеличивается без
    сглаживания, поэтому остаётся честным пиксель-артом на любом размере.
    """
    grid = QPixmap(16, 16)
    grid.fill(Qt.GlobalColor.transparent)
    painter = QPainter(grid)
    painter.setPen(Qt.PenStyle.NoPen)

    ink = QColor(color)
    ink.setAlpha(max(0, min(255, alpha)))
    soft = QColor(color)
    soft.setAlpha(max(0, min(255, int(alpha * 0.55))))

    painter.setBrush(ink)
    # Рамка планшета.
    painter.drawRect(3, 2, 10, 1)
    painter.drawRect(3, 13, 10, 1)
    painter.drawRect(3, 2, 1, 12)
    painter.drawRect(12, 2, 1, 12)
    # Ушко сверху.
    painter.drawRect(6, 1, 4, 1)
    # Строки списка.
    painter.setBrush(soft)
    for y in (5, 8, 11):
        painter.drawRect(5, y, 6, 1)
    # Галочка на первой строке.
    painter.setBrush(ink)
    painter.drawRect(5, 5, 1, 1)
    painter.drawRect(6, 6, 1, 1)
    painter.drawRect(7, 4, 1, 1)
    painter.end()

    return grid.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
