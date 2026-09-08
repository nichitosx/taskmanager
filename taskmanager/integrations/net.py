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

import socket
import ssl
import sys
import urllib.error
import urllib.request
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


def normalize_proxy(address: str) -> str:
    """Приводит адрес прокси к виду, который понимает urllib."""
    address = (address or "").strip()
    if not address:
        return ""
    if "://" not in address:
        address = "http://" + address
    return address.rstrip("/")


def opener(ca_file: str = "", proxy: str = "") -> urllib.request.OpenerDirector:
    """Открыватель запросов: сертификаты и прокси в одном месте.

    Без указанного прокси остаются системные настройки Windows — их urllib
    читает сам. Явный адрес нужен там, где браузер ходит через прокси по
    автонастройке (PAC): её urllib не умеет, и адрес приходится назвать руками.
    """
    handlers: list = [urllib.request.HTTPSHandler(context=ssl_context(ca_file))]
    address = normalize_proxy(proxy)
    if address:
        handlers.insert(0, urllib.request.ProxyHandler({"http": address, "https": address}))
    return urllib.request.build_opener(*handlers)


def opener_from_settings(settings) -> urllib.request.OpenerDirector:
    if settings is None:
        return opener()
    return opener(settings.get("network.ca_file", ""), settings.get("network.proxy", ""))


def is_certificate_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    text = str(exc).lower()
    return "certificate verify failed" in text or "certificate_verify_failed" in text


VPN_HINT = (
    "Внутренний адрес виден только из рабочей сети, поэтому из дома нужен VPN."
)


def describe(exc: BaseException, host: str = "") -> str:
    """Человеческое объяснение сетевой ошибки."""
    if is_certificate_error(exc):
        return "Сертификат сервера не прошёл проверку. " + CERT_HINT

    where = "«%s»" % host if host else "этот адрес"
    if isinstance(exc, socket.gaierror):
        # Имя не превратилось в адрес: опечатка либо DNS рабочей сети недоступен.
        return (
            "Не нашёл в сети имя %s. Проверьте адрес на опечатку и подключение "
            "к рабочей сети. %s" % (where, VPN_HINT)
        )
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return (
            "Адрес %s найден, но не ответил вовремя. %s" % (where, VPN_HINT)
        )
    if isinstance(exc, ConnectionRefusedError):
        return (
            "Адрес %s есть, но соединение отклонено: проверьте порт в адресе."
            % where
        )
    text = str(exc)
    if "tunnel" in text.lower() or "cannot connect to proxy" in text.lower():
        # Прокси есть, но не пропускает: обычно так выглядит доступ извне.
        return (
            "Прокси не пропустил соединение с %s. %s" % (where, VPN_HINT)
        )
    return text
