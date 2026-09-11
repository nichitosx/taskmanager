"""Фоновая проверка обновлений при запуске.

Раз в сутки программа тихо смотрит, не появилась ли новая версия, и если да —
показывает полоску с кнопкой. Проверка идёт в отдельном потоке: ни запуск, ни
работа от неё не тормозят, а без интернета она просто молча заканчивается.

Сравнивается не записанная отметка, а содержимое файлов (см. update.fingerprint):
отметка может быть неверной, если программу поставили из старого архива.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .config import app_dir

LAST_CHECK_KEY = "updates.last_check"


def _load_updater():
    """Подтягивает update.py, который лежит рядом с программой, а не в пакете."""
    path = app_dir() / "update.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("taskmanager_update", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("taskmanager_update", module)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


class UpdateCheck(QThread):
    """Проверяет наличие новой версии, не мешая работе программы."""

    found = Signal(str)   # краткое описание новой версии

    def run(self) -> None:  # noqa: D102 (Qt naming)
        updater = _load_updater()
        if updater is None:
            return
        try:
            info = updater.latest()
            if info is None:
                return
            archive = updater.download()
            if archive is None:
                return
            source = updater.unpack(archive)
            if source is None:
                return
            if updater.fingerprint(Path(app_dir())) == updater.fingerprint(source):
                return
            # Номер версии человеку понятнее отпечатка коммита; если номера в
            # скачанных файлах нет, называем хотя бы дату.
            fresh = ""
            if hasattr(updater, "describe_version"):
                fresh = updater.describe_version(source)
            self.found.emit(fresh or "сборка от %s" % info.get("date", ""))
        except Exception:
            return  # проверка обновлений не должна мешать работать


def due_today(settings) -> bool:
    """Проверяем не чаще раза в сутки — чтобы не дёргать сеть на каждом запуске."""
    return settings.get(LAST_CHECK_KEY, "") != date.today().isoformat()


def mark_checked(settings) -> None:
    settings.set(LAST_CHECK_KEY, date.today().isoformat())
    settings.save()
