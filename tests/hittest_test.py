"""命中区域回归测试：验证 WM_NCHITTEST 在高 DPI 下的边缘判定。

背景：WM_NCHITTEST 的光标坐标是物理像素，Qt 几何是逻辑坐标，未换算时
150% 缩放屏幕上的缩放判定区会错位到窗口内部，吞掉编辑区的鼠标事件。

本测试按真实流程构造 WM_NCHITTEST 消息（物理坐标）直接调用 nativeEvent，
断言返回的命中码。不依赖真实鼠标。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctypes import wintypes
from shiboken6 import VoidPtr

from PySide6.QtWidgets import QApplication

from note_window import NoteWindow

# WM_NCHITTEST 返回值
HT = {10: "LEFT", 11: "RIGHT", 12: "TOP", 15: "BOTTOM",
      13: "TOPLEFT", 14: "TOPRIGHT", 16: "BOTTOMLEFT", 17: "BOTTOMRIGHT"}

app = QApplication(sys.argv)
win = NoteWindow("__ht__.txt", "<p>ht</p>",
                 {"id": "ht", "opacity": 1.0, "ontop": True,
                  "geometry": [160, 120, 340, 380]})
win.show()
app.processEvents()
win.setGeometry(160, 120, 340, 380)
app.processEvents()

dpr = win.devicePixelRatioF()
r = win.frameGeometry()
left = r.left() * dpr
right = (r.left() + r.width()) * dpr
top = r.top() * dpr
bottom = (r.top() + r.height()) * dpr
cx = (left + right) / 2
cy = (top + bottom) / 2
print(f"dpr={dpr} window physical rect=({left:.0f},{top:.0f})-({right:.0f},{bottom:.0f})")


def hit(x, y):
    msg = wintypes.MSG()
    msg.message = 0x0084  # WM_NCHITTEST
    msg.lParam = (int(y) << 16) | (int(x) & 0xFFFF)
    handled, code = win.nativeEvent(b"windows_generic_MSG", VoidPtr(ctypes.addressof(msg)))
    return code if handled else None


cases = [
    ("编辑区中心（应可输入）", (cx, cy), None),
    ("标题栏内部（应可拖拽）", (cx, top + 20 * dpr), None),
    ("标题栏右上角附近", (right - 12 * dpr, top + 20 * dpr), None),
    ("左边缘", (left + 2, cy), 10),
    ("右边缘", (right - 2, cy), 11),
    ("上边缘", (cx, top + 2), 12),
    ("下边缘", (cx, bottom - 2), 15),
    ("左上角", (left + 2, top + 2), 13),
    ("右上角", (right - 2, top + 2), 14),
    ("左下角", (left + 2, bottom - 2), 16),
    ("右下角", (right - 2, bottom - 2), 17),
]

fail = 0
for name, (x, y), expect in cases:
    got = hit(x, y)
    ok = got == expect
    fail += 0 if ok else 1
    print(f"CASE {name}: got={got if got is None else HT.get(got, got)} "
          f"expect={expect if expect is None else HT.get(expect, expect)} => "
          f"{'OK' if ok else 'FAIL'}")

print("RESULT", "OK" if fail == 0 else "FAIL")
sys.exit(0 if fail == 0 else 1)
