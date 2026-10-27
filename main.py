"""tiptip — 极简桌面便签。程序入口。

- 单实例运行：QLockFile 锁（用户目录 .tiptip/app.lock），重复启动提示后退出；
- 首次启动（tiptip/Solve 下无任何 .txt）自动生成"使用指南"便签；
- 启动时读取 tiptip/Solve 下的所有 .txt 恢复便签窗口；
- 注册全局快捷键 Ctrl+T 一键新建便签；
- 托盘图标常驻（关闭全部便签后程序仍在后台，Ctrl+T 依然可用）；
- 退出时保存所有便签并释放全局快捷键。

自检：`python main.py --smoke`（打包后同样支持：tiptip.exe --smoke），
不做界面显示，验证存储读写、图片内嵌与快捷键注册。
"""
from __future__ import annotations

import html
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QPoint, QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import storage
from hotkey import GlobalHotkey
from icon import make_app_icon
from note_window import NoteWindow

CASCADE_MAX = 8  # 连续新建便签时的级联偏移次数，之后回到起点

# ---------- 首次启动"使用指南" ----------

GUIDE_TITLE = "使用指南"
GUIDE_BODY = (
    "使用 Ctrl + T 生成新便签\n"
    "请牢记：save：保存\n"
    "                Discard：不保存\n"
    "                Cancel：取消"
)

# ---------- 单实例锁 ----------

LOCK_DIR = Path.home() / ".tiptip"
LOCK_PATH = LOCK_DIR / "app.lock"


def acquire_single_instance_lock() -> QLockFile | None:
    """单实例检测。

    在用户可写目录创建锁文件目录后调用 tryLock()：
    - 成功：返回 QLockFile 对象，调用方必须保持其存活直到程序退出，
      否则锁会被提前释放；
    - 失败（已有一个实例在运行）：返回 None。
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(LOCK_PATH))
    if lock.tryLock(0):
        return lock
    return None


def is_first_launch() -> bool:
    """首次启动判断：tiptip/Solve 目录下不存在任何 .txt 文件。"""
    return not any(storage.get_solve_dir().glob("*.txt"))


def create_guide_note() -> Path | None:
    """生成"使用指南"便签（仅首次启动时调用，幂等）。

    标题为"使用指南"，正文为预设内容；空格转 &nbsp; 以保持排版。
    直接写入 .txt 文件，窗口由随后的恢复逻辑加载显示。
    """
    if not is_first_launch():
        return None
    lines = [html.escape(line).replace(" ", "&nbsp;") for line in GUIDE_BODY.splitlines()]
    note_html = "".join(f"<p>{line}</p>" for line in lines)
    meta = {
        "id": storage.new_note_id(),
        "title": GUIDE_TITLE,
        "geometry": [160, 120, 340, 380],
        "opacity": 1.0,
        "ontop": True,
    }
    return storage.save_note(f"{GUIDE_TITLE}.txt", note_html, meta)


class TiptipApp(QObject):
    """应用外壳：窗口管理、托盘、全局快捷键、退出时收尾。"""

    def __init__(self, app: QApplication, single_instance_lock: QLockFile):
        super().__init__(app)
        self.app = app
        # 持有单实例锁直到程序退出，避免锁被提前释放
        self._single_instance_lock = single_instance_lock
        self.windows: list[NoteWindow] = []
        self._cascade = 0
        self.tray: QSystemTrayIcon | None = None

        self.hotkey = GlobalHotkey(self)
        self.hotkey.pressed.connect(self.new_note)

        self._setup_tray()
        create_guide_note()  # 首次启动自动生成"使用指南"
        self._restore_notes()

        if storage.get_data_root() != storage.preferred_root():
            QMessageBox.information(
                None, "tiptip",
                "程序所在目录不可写，便签数据将保存到：\n"
                + str(storage.get_solve_dir()))

        if not self.hotkey.register():
            QMessageBox.warning(
                None, "tiptip",
                "全局快捷键 Ctrl+T 注册失败，可能已被其他程序占用。\n"
                "仍可通过系统托盘图标或便签的右键菜单新建便签。")

        app.aboutToQuit.connect(self._on_quit)

    # ---------- 便签窗口管理 ----------

    def _restore_notes(self):
        seen_ids: set = set()
        for filename, html, meta in storage.load_all_notes():
            nid = meta.get("id")
            if nid in seen_ids:  # 文件被复制过导致 id 重复：重新分配
                meta["id"] = storage.new_note_id()
            seen_ids.add(meta["id"])
            self._add_window(filename, html, meta)
        if not self.windows:
            self.new_note()

    def _next_cascade_pos(self) -> QPoint:
        base = QPoint(160, 120)
        pos = base + QPoint(36, 36) * (self._cascade % CASCADE_MAX)
        self._cascade += 1
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            pos.setX(min(max(pos.x(), geo.left() + 8), geo.right() - 360))
            pos.setY(min(max(pos.y(), geo.top() + 8), geo.bottom() - 420))
        return pos

    def _default_meta(self) -> dict:
        pos = self._next_cascade_pos()
        return {
            "id": storage.new_note_id(),
            "geometry": [pos.x(), pos.y(), 340, 380],
            "opacity": 1.0,
            "ontop": True,
            "created": datetime.now().isoformat(timespec="seconds"),
        }

    def _add_window(self, filename: str | None, html: str, meta: dict) -> NoteWindow:
        win = NoteWindow(filename, html, meta,
                         on_new_note=self.new_note, on_quit=self.app.quit)
        win.closed_signal.connect(self._on_window_closed)
        self.windows.append(win)
        win.show()
        return win

    def new_note(self):
        win = self._add_window(None, "", self._default_meta())
        win.raise_()
        win.activateWindow()
        win.editor.setFocus()

    def _on_window_closed(self, win: NoteWindow):
        if win in self.windows:
            self.windows.remove(win)
        win.deleteLater()

    # ---------- 托盘 ----------

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(make_app_icon(), self)
        tray.setToolTip("tiptip 桌面便签\n双击新建便签，Ctrl+T 全局新建")
        menu = QMenu()
        act_new = menu.addAction("新建便签\tCtrl+T")
        act_new.triggered.connect(self.new_note)
        menu.addSeparator()
        if sys.platform == "win32":
            act_dir = menu.addAction("打开数据文件夹")
            act_dir.triggered.connect(self._open_data_dir)
        menu.addSeparator()
        act_quit = menu.addAction("退出程序")
        act_quit.triggered.connect(self.app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self.tray = tray

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.new_note()

    @staticmethod
    def _open_data_dir():
        os.startfile(str(storage.get_solve_dir()))  # type: ignore[attr-defined]

    # ---------- 退出 ----------

    def _on_quit(self):
        self.hotkey.unregister()
        for win in self.windows:
            win._quitting = True  # 退出时静默保存，不弹关闭确认框
            win.save_now()


# ---------- 无界面自检 ----------

_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _run_smoke() -> int:
    app = QApplication(sys.argv)
    offscreen = QGuiApplication.platformName() == "offscreen"
    probe_html = f"<p>你好 tiptip</p><img src='{_TINY_PNG}' />"

    # 1) 存储读写（含元数据）
    storage.save_note("__smoke__.txt", probe_html, {"id": "smoke", "ontop": True})
    saved = next((h for f, h, _ in storage.load_all_notes() if f == "__smoke__.txt"), None)
    ok_storage = (saved is not None and "你好 tiptip" in saved
                  and "<img" in saved and "data:image/png;base64" in saved)
    print("SMOKE storage:", "OK" if ok_storage else "FAIL")

    # 2) 便签窗口 → 保存（覆盖两类图片：data URI 加载 + 程序内插入图片）
    win = NoteWindow("__smoke2__.txt", probe_html,
                     {"id": "smoke2", "opacity": 1.0, "ontop": True})
    gen = QImage(4, 4, QImage.Format.Format_ARGB32)
    gen.fill(QColor("#336699"))
    win._insert_image(gen)  # 模拟粘贴/拖入图片的插入路径
    win.save_now()
    saved2 = next((h for f, h, _ in storage.load_all_notes() if f == "__smoke2__.txt"), None)
    ok_note = (saved2 is not None and saved2.count("<img") == 2
               and saved2.count("data:image/png;base64") == 2)
    print("SMOKE note-save:", "OK" if ok_note else "FAIL")

    # 3) 渲染路径（仅在离屏模式下走一遍 paintEvent，屏幕上无窗口）
    if offscreen:
        win.show()
        app.processEvents()
        win.hide()

    # 4) 全局快捷键注册（离屏平台没有真实 HWND，跳过）
    ok_hotkey = None
    if not offscreen and sys.platform == "win32":
        hk = GlobalHotkey()
        ok_hotkey = hk.register()
        print("SMOKE hotkey:", "OK" if ok_hotkey else "FAIL")
        hk.unregister()

    for name in ("__smoke__.txt", "__smoke2__.txt"):
        (storage.get_solve_dir() / name).unlink(missing_ok=True)

    ok = ok_storage and ok_note and (ok_hotkey is None or ok_hotkey)
    print("SMOKE", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--smoke" in sys.argv:
        return _run_smoke()

    app = QApplication(sys.argv)
    app.setApplicationName("tiptip")
    app.setApplicationDisplayName("tiptip")
    app.setQuitOnLastWindowClosed(False)  # 全部便签关闭后程序仍在后台，Ctrl+T 可用
    app.setWindowIcon(make_app_icon())

    # 单实例检测：程序已在运行则提示并退出当前实例
    lock = acquire_single_instance_lock()
    if lock is None:
        QMessageBox.information(None, "tiptip", "便签已在运行中，请勿重复打开。")
        return 0

    TiptipApp(app, lock)  # 以 app 为父对象，随应用存活；锁由应用持有直到退出
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
