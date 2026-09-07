"""Ярлыки Windows и системные папки — напрямую через COM, без внешних процессов.

Раньше `.lnk` создавался вызовом `powershell.exe` со скриптом WScript.Shell.
Связка «интерпретатор запускает PowerShell, который пишет ярлык в автозагрузку»
— классическая примета закрепления в системе, и корпоративные средства защиты
(Kaspersky HIPS, Check Point Harmony) на неё реагируют. Здесь то же самое
делается внутри процесса обращением к COM-интерфейсу IShellLink: дочерних
процессов не появляется, PowerShell не запускается.

Всё написано на ctypes, без сторонних библиотек. На не-Windows функции просто
возвращают False/None — вызывающий код падать не должен.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_void_p
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    ole32 = ctypes.oledll.ole32
    shell32 = ctypes.oledll.shell32

    class GUID(ctypes.Structure):
        """Идентификатор COM-класса или интерфейса."""

        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_byte * 8),
        ]

        def __init__(self, text: str) -> None:
            super().__init__()
            ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(self))

    # Идентификаторы из shobjidl.h и shlguid.h.
    CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
    IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
    IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"

    CLSCTX_INPROC_SERVER = 1
    SW_SHOWNORMAL = 1

    # Папки профиля берём у системы: рабочий стол может быть перенесён в OneDrive.
    FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
    FOLDERID_PROGRAMS = "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"
    FOLDERID_STARTUP = "{B97D20BB-F46A-4C97-BA10-5E3608430854}"

    # Порядок методов в таблице интерфейса: первые три — от IUnknown.
    _SHELL_LINK_METHODS = {
        "SetDescription": 7,
        "SetWorkingDirectory": 9,
        "SetArguments": 11,
        "SetShowCmd": 15,
        "SetIconLocation": 17,
        "SetPath": 20,
    }
    _PERSIST_FILE_SAVE = 6
    _RELEASE = 2
    _QUERY_INTERFACE = 0

    def _method(pointer: c_void_p, index: int, *argtypes):
        """Достаёт метод COM-объекта по номеру в таблице виртуальных функций."""
        table = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
        return prototype(table[index])


def known_folder(folder_id: str) -> Optional[Path]:
    """Путь к системной папке по её идентификатору."""
    if not IS_WINDOWS:
        return None
    buffer = ctypes.c_wchar_p()
    try:
        shell32.SHGetKnownFolderPath(byref(GUID(folder_id)), 0, None, byref(buffer))
    except OSError:
        return None
    try:
        return Path(buffer.value) if buffer.value else None
    finally:
        ole32.CoTaskMemFree(buffer)


def desktop_dir() -> Path:
    """Рабочий стол пользователя с учётом переезда в OneDrive."""
    path = known_folder(FOLDERID_DESKTOP) if IS_WINDOWS else None
    if path is not None and path.is_dir():
        return path
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Desktop"


def start_menu_dir() -> Path:
    """Папка «Программы» в меню «Пуск» текущего пользователя."""
    path = known_folder(FOLDERID_PROGRAMS) if IS_WINDOWS else None
    if path is not None and path.is_dir():
        return path
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def startup_dir() -> Path:
    """Папка «Автозагрузка» текущего пользователя."""
    path = known_folder(FOLDERID_STARTUP) if IS_WINDOWS else None
    if path is not None and path.is_dir():
        return path
    return start_menu_dir() / "Startup"


def create_shortcut(
    path: Path,
    target: str,
    arguments: str = "",
    working_dir: str = "",
    icon: str = "",
    description: str = "",
) -> bool:
    """Создаёт .lnk через COM. False — если не получилось (вызывающий решает, что дальше)."""
    if not IS_WINDOWS:
        return False

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    initialized = False
    link = c_void_p()
    persist = c_void_p()
    try:
        try:
            ole32.CoInitialize(None)
            initialized = True
        except OSError:
            # COM уже инициализирован в этом потоке — это нормально.
            pass

        ole32.CoCreateInstance(
            byref(GUID(CLSID_SHELL_LINK)),
            None,
            CLSCTX_INPROC_SERVER,
            byref(GUID(IID_SHELL_LINK_W)),
            byref(link),
        )

        _method(link, _SHELL_LINK_METHODS["SetPath"], ctypes.c_wchar_p)(link, target)
        if arguments:
            _method(link, _SHELL_LINK_METHODS["SetArguments"], ctypes.c_wchar_p)(
                link, arguments
            )
        if working_dir:
            _method(link, _SHELL_LINK_METHODS["SetWorkingDirectory"], ctypes.c_wchar_p)(
                link, working_dir
            )
        if description:
            _method(link, _SHELL_LINK_METHODS["SetDescription"], ctypes.c_wchar_p)(
                link, description[:255]
            )
        if icon:
            _method(
                link, _SHELL_LINK_METHODS["SetIconLocation"], ctypes.c_wchar_p, ctypes.c_int
            )(link, icon, 0)
        _method(link, _SHELL_LINK_METHODS["SetShowCmd"], ctypes.c_int)(link, SW_SHOWNORMAL)

        _method(link, _QUERY_INTERFACE, c_void_p, c_void_p)(
            link, byref(GUID(IID_PERSIST_FILE)), byref(persist)
        )
        _method(persist, _PERSIST_FILE_SAVE, ctypes.c_wchar_p, wintypes.BOOL)(
            persist, str(path), True
        )
    except (OSError, AttributeError, ValueError):
        return False
    finally:
        for pointer in (persist, link):
            if pointer:
                try:
                    _method(pointer, _RELEASE)(pointer)
                except OSError:
                    pass
        if initialized:
            try:
                ole32.CoUninitialize()
            except OSError:
                pass

    return path.exists()
