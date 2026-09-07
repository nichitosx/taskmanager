"""Иконка приложения. Рисуется кодом — внешних файлов с картинками нет.

Отсюда её берут и окно с треем, и генератор .ico для ярлыков Windows.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = "#D97757"
BACKGROUND = "#131211"
MUTED = "#6B665F"


def make_pixmap(size: int = 64, accent: str = ACCENT, background: str = BACKGROUND) -> QPixmap:
    """Квадратная иконка: скруглённая плашка и три «строки списка»."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    scale = size / 64.0

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    painter.setBrush(QColor(background))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
    painter.setBrush(QColor(accent))
    for index, y in enumerate((18, 32, 46)):
        painter.drawEllipse(16, y - 4, 8, 8)
        width = 26 if index != 2 else 16
        painter.setBrush(QColor(accent if index == 0 else MUTED))
        painter.drawRoundedRect(30, y - 3, width, 6, 3, 3)
        painter.setBrush(QColor(accent))
    painter.end()
    return pixmap


def make_icon(accent: str = ACCENT, background: str = BACKGROUND) -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(make_pixmap(size, accent, background))
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
    sizes = [16, 32, 48, 64, 128, 256]
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
