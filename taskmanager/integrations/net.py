"""Общие сетевые настройки: доверие сертификатам и понятные ошибки TLS.

В корпоративной сети трафик часто проверяет средство защиты (Check Point
Harmony, Kaspersky и подобные): оно подменяет сертификат сайта своим, а свой
корневой сертификат кладёт в хранилище Windows. Python на Windows это хранилище
читает сам, но бывает, что нужный корень туда не попал или помечен так, что
стандартный фильтр его отбрасывает. Поэтому здесь:

* контекст собирается из стандартного, дополненного хранилищами Windows;
* можно указать свой файл корневого сертификата в настройках;
* ошибка проверки превращается в текст, из которого понятно, что делать.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

# Назначение «проверка подлинности сервера»: только такие корни имеют смысл.
SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"

CERT_HINT = (
    "Похоже, трафик проверяет корпоративное средство защиты, а его корневой "
    "сертификат программе не виден. Попросите администратора установить "
    "сертификат в хранилище Windows либо укажите файл сертификата в "
    "«Настройки → Интеграции → Корневой сертификат»."
)


def _add_windows_certs(context: ssl.SSLContext) -> int:
    """Досыпает в контекст корни из хранилищ Windows. Возвращает, сколько добавил."""
    if sys.platform != "win32":
        return 0
    added = 0
    for store in ("ROOT", "CA"):
        try:
            certificates = ssl.enum_certificates(store)
        except (AttributeError, OSError, PermissionError):
            continue
        for cert, encoding, trust in certificates:
            if encoding != "x509_asn":
                continue
            # trust True означает «годен для всего»; иначе смотрим на назначение.
            if trust is not True and SERVER_AUTH_OID not in (trust or ()):
                continue
            try:
                context.load_verify_locations(cadata=cert)
                added += 1
            except ssl.SSLError:
                continue  # битый или дублирующийся сертификат просто пропускаем
    return added


def ssl_context(ca_file: str = "") -> ssl.SSLContext:
    """Контекст TLS с проверкой сертификата и корпоративными корнями."""
    context = ssl.create_default_context()
    _add_windows_certs(context)

    path = (ca_file or "").strip()
    if path:
        try:
            context.load_verify_locations(cafile=str(Path(path)))
        except (OSError, ssl.SSLError):
            # Неверный файл не должен ломать соединение: остаются системные корни.
            pass
    return context


def context_from_settings(settings) -> ssl.SSLContext:
    return ssl_context(settings.get("network.ca_file", "") if settings else "")


def is_certificate_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    text = str(exc).lower()
    return "certificate verify failed" in text or "certificate_verify_failed" in text


def describe(exc: BaseException) -> str:
    """Человеческое объяснение сетевой ошибки."""
    if is_certificate_error(exc):
        return "Сертификат сервера не прошёл проверку. " + CERT_HINT
    return str(exc)
