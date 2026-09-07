"""Точка входа TaskManager.

Запуск:  python run.py           — обычное окно
         pythonw run.py --tray   — стартовать свёрнутым в трей (автозагрузка)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QByteArray, QTimer  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from taskmanager.config import Settings  # noqa: E402
from taskmanager.storage import Storage  # noqa: E402
from taskmanager.ui import theme  # noqa: E402
from taskmanager.ui.main_window import MainWindow  # noqa: E402

SERVER_NAME = "TaskManager.SingleInstance"


def _already_running() -> bool:
    """Не даём запустить вторую копию — иначе две базы и два напоминания."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True
    return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TaskManager")
    app.setOrganizationName("TaskManager")
    app.setQuitOnLastWindowClosed(False)

    if _already_running():
        return 0

    settings = Settings()
    try:
        storage = Storage()
    except Exception as exc:  # база недоступна — работать дальше нельзя
        QMessageBox.critical(
            None, "TaskManager", "Не удалось открыть базу задач:\n%s" % exc
        )
        return 1

    app.setStyleSheet(
        theme.stylesheet(settings.get("theme", "dark"), settings.get("ui_style", "soft"))
    )

    window = MainWindow(storage, settings)
    geometry = settings.get("window_geometry", "")
    if geometry:
        window.restoreGeometry(QByteArray.fromBase64(geometry.encode()))

    # Сервер для перехвата повторного запуска: показываем уже открытое окно.
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer(app)
    server.listen(SERVER_NAME)
    server.newConnection.connect(lambda: QTimer.singleShot(0, window._restore))

    if "--tray" in sys.argv:
        window.hide()
    else:
        window.show()

    exit_code = app.exec()
    storage.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
