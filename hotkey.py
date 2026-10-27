"""全局快捷键 Ctrl+T（Windows）。

用 ctypes 直接调用 Win32 RegisterHotKey，通过一个永不显示的 Qt 原生窗口接收
WM_HOTKEY 消息，不依赖 pywin32 等额外包；注册失败（被其他程序占用）时只报告
失败，不抛异常，不影响程序继续运行；程序退出时释放快捷键。
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000  # 按住不放只触发一次，避免连续弹窗
VK_T = ord("T")

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _kernel32 = ctypes.windll.kernel32
    _kernel32.GetLastError.restype = wintypes.DWORD
else:
    _user32 = None
    _kernel32 = None


class _HotkeyWindow(QWidget):
    """永不显示的隐藏窗口，只用来接收 WM_HOTKEY。"""

    pressed = Signal()

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.pressed.emit()
                return True, 0
        return super().nativeEvent(eventType, message)


class GlobalHotkey(QObject):
    """负责 Ctrl+T 的注册与释放。registered 为 False 表示注册失败（冲突）。"""

    HOTKEY_ID = 0x5449
    pressed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._window = _HotkeyWindow()
        self._window.pressed.connect(self.pressed)
        self._window.winId()  # 强制创建原生窗口句柄（窗口本身不显示）
        self._registered = False
        self._last_error = 0

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> bool:
        if self._registered:
            return True
        if sys.platform != "win32":
            return False
        hwnd = int(self._window.winId())
        ok = _user32.RegisterHotKey(hwnd, self.HOTKEY_ID, MOD_CONTROL | MOD_NOREPEAT, VK_T)
        self._registered = bool(ok)
        if not ok:
            self._last_error = int(_kernel32.GetLastError())  # 1409 = 已被注册
        return self._registered

    def unregister(self) -> None:
        if self._registered:
            _user32.UnregisterHotKey(int(self._window.winId()), self.HOTKEY_ID)
            self._registered = False
