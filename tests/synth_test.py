"""交互回归测试：合成事件验证拖拽、关闭流程（三选项）、置顶开关。

运行：python tests/synth_test.py
不依赖真实鼠标，验证 Qt 事件层逻辑。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton

import storage
from note_window import NoteWindow

SOLVE = storage.get_solve_dir()


def mouse(type_, target, local, button, buttons):
    ev = QMouseEvent(type_, QPointF(local), QPointF(target.mapToGlobal(local)),
                     button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, ev)


def find_close_btn(win):
    return next(b for b in win.findChildren(QToolButton) if b.text() == "✕")


def patch_question(btn):
    QMessageBox.question = lambda *a, **k: btn


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else None


# ---------- 拖拽 ----------

def run_drag_case(label, pick, button):
    win = NoteWindow("__synthtest__.txt", f"<p>{label}</p>",
                     {"id": "s", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    if pick == "title-edit":
        target = win.title_edit
    elif pick == "bar":
        target = win.title_bar
    else:
        target = win.editor.viewport()
    pos0 = win.pos()
    local = QPoint(target.width() // 2, target.height() // 2) \
        if pick != "bar" else QPoint(10, 15)
    mouse(QEvent.Type.MouseButtonPress, target, local, button, button)
    mouse(QEvent.Type.MouseMove, target, local + QPoint(100, 60), Qt.MouseButton.NoButton, button)
    mouse(QEvent.Type.MouseButtonRelease, target, local + QPoint(100, 60), button,
          Qt.MouseButton.NoButton)
    pos1 = win.pos()
    ok = pos1 == pos0 + QPoint(100, 60)
    print(f"CASE drag-{label}: ({pos0.x()},{pos0.y()})->({pos1.x()},{pos1.y()}) "
          f"expect +100/+60 => {'OK' if ok else 'FAIL'}")
    win._quitting = True  # 静默关闭，跳过确认框
    win.close()
    return ok


# ---------- 已储存便签的关闭流程 ----------

def run_stored_unchanged():
    """内容未变 → 不弹框，静默保存（文件已存在时仅更新状态）后关闭。"""
    called = []
    QMessageBox.question = lambda *a, **k: (called.append(1), QMessageBox.StandardButton.Cancel)[1]
    f = SOLVE / "__stored__.txt"
    f.write_text("<p>same</p>", encoding="utf-8")  # 模拟磁盘上已存在的便签
    win = NoteWindow("__stored__.txt", "<p>same</p>",
                     {"id": "u", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    ok = (not win.isVisible()) and not called and f.exists() and "same" in read(f)
    print(f"CASE stored-unchanged: closed={not win.isVisible()} no-dialog={not called} "
          f"kept={ok} => {'OK' if ok else 'FAIL'}")
    f.unlink(missing_ok=True)
    return ok


def run_stored_save_rename():
    """已修改 + 保存：写新标题文件，旧文件删除。"""
    patch_question(QMessageBox.StandardButton.Save)
    f_old = SOLVE / "__stored__.txt"
    f_old.write_text("<p>orig</p>", encoding="utf-8")
    win = NoteWindow("__stored__.txt", "<p>orig</p>",
                     {"id": "sr", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    win.title_edit.setText("改名后")
    win.editor.append("<p>extra</p>")
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    f_new = SOLVE / "改名后.txt"
    ok = ((not win.isVisible()) and f_new.exists() and "extra" in read(f_new)
          and not f_old.exists())
    print(f"CASE stored-save-rename: closed={not win.isVisible()} new={f_new.exists()} "
          f"old-deleted={not f_old.exists()} => {'OK' if ok else 'FAIL'}")
    f_new.unlink(missing_ok=True)
    return ok


def run_stored_discard_revert():
    """已修改 + 不保存：还原原始标题/正文与原始文件名（改名文件被删除）。"""
    patch_question(QMessageBox.StandardButton.Discard)
    f = SOLVE / "__stored__.txt"
    f.write_text("<p>orig</p>", encoding="utf-8")
    win = NoteWindow("__stored__.txt", "<p>orig</p>",
                     {"id": "d", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    win.title_edit.setText("改名了")
    win.editor.append("<p>dirty</p>")
    win.save_now()  # 模拟防抖自动保存已把文件改名
    f_renamed = SOLVE / "改名了.txt"
    renamed_existed = f_renamed.exists() and not f.exists()
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    ok = ((not win.isVisible()) and renamed_existed and f.exists()
          and "orig" in read(f) and "dirty" not in read(f) and not f_renamed.exists())
    print(f"CASE stored-discard-revert: renamed={renamed_existed} reverted={f.exists()} "
          f"renamed-deleted={not f_renamed.exists()} => {'OK' if ok else 'FAIL'}")
    f.unlink(missing_ok=True)
    return ok


def run_stored_cancel():
    """已修改 + 取消：窗口保持打开，文件保持原样。"""
    patch_question(QMessageBox.StandardButton.Cancel)
    f = SOLVE / "__stored__.txt"
    f.write_text("<p>orig</p>", encoding="utf-8")
    win = NoteWindow("__stored__.txt", "<p>orig</p>",
                     {"id": "c", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    win.editor.append("<p>dirty</p>")
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    ok = win.isVisible() and f.exists() and "orig" in read(f)
    print(f"CASE stored-cancel: still-open={win.isVisible()} file-untouched={ok} "
          f"=> {'OK' if ok else 'FAIL'}")
    win._quitting = True
    win.close()
    f.unlink(missing_ok=True)
    return ok


# ---------- 新建便签的关闭流程（沿用原有逻辑） ----------

def run_new_close_save():
    """新建有内容 + 是 → 保存并关闭。"""
    patch_question(QMessageBox.StandardButton.Yes)
    win = NoteWindow(None, "<p>close me</p>", {"id": "ns", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    f = SOLVE / "close me.txt"
    ok = (not win.isVisible()) and f.exists() and "close me" in read(f)
    print(f"CASE new-close-save: closed={not win.isVisible()} saved={f.exists()} => "
          f"{'OK' if ok else 'FAIL'}")
    f.unlink(missing_ok=True)
    return ok


def run_new_close_discard():
    """新建有内容 + 否 → 不保存，删除已有文件并销毁。"""
    patch_question(QMessageBox.StandardButton.No)
    win = NoteWindow(None, "<p>do not keep</p>", {"id": "nd", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    win.save_now()
    f = SOLVE / "do not keep.txt"
    existed = f.exists()
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    ok = existed and (not win.isVisible()) and (not f.exists())
    print(f"CASE new-close-discard: existed={existed} closed={not win.isVisible()} "
          f"deleted={not f.exists()} => {'OK' if ok else 'FAIL'}")
    f.unlink(missing_ok=True)
    return ok


def run_blank_close():
    """标题与正文全空 → 不弹确认框，直接销毁，不生成文件。"""
    called = []

    def boom(*a, **k):
        called.append(1)
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = boom
    win = NoteWindow(None, "", {"id": "blank", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    before = set(SOLVE.glob("*.txt"))
    QTest.mouseClick(find_close_btn(win), Qt.MouseButton.LeftButton)
    app.processEvents()
    after = set(SOLVE.glob("*.txt"))
    ok = (not win.isVisible()) and not called and after == before
    print(f"CASE blank-close: closed={not win.isVisible()} no-dialog={not called} "
          f"no-new-file={after == before} => {'OK' if ok else 'FAIL'}")
    return ok


def run_pin_toggle():
    """置顶开关：取消置顶后窗口必须保持可见，且仅移除 WindowStaysOnTopHint。"""
    win = NoteWindow(None, "<p>pin</p>", {"id": "pin", "opacity": 1.0, "ontop": True})
    win.show()
    app.processEvents()
    win._set_on_top(False)
    flags = win.windowFlags()
    ok_off = (win.isVisible()
              and not (flags & Qt.WindowType.WindowStaysOnTopHint)
              and bool(flags & Qt.WindowType.Window)
              and bool(flags & Qt.WindowType.FramelessWindowHint))
    win._set_on_top(True)
    ok_on = win.isVisible() and bool(win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    ok = ok_off and ok_on
    print(f"CASE pin-toggle: off-visible={ok_off} on-visible={ok_on} => {'OK' if ok else 'FAIL'}")
    win._quitting = True
    win.close()
    return ok


if __name__ == "__main__":
    app = QApplication(sys.argv)
    results = [
        run_drag_case("title-edit-left", "title-edit", Qt.MouseButton.LeftButton),
        run_drag_case("titlebar-grip-left", "bar", Qt.MouseButton.LeftButton),
        run_drag_case("editor-middle", "editor", Qt.MouseButton.MiddleButton),
        run_stored_unchanged(),
        run_stored_save_rename(),
        run_stored_discard_revert(),
        run_stored_cancel(),
        run_new_close_save(),
        run_new_close_discard(),
        run_blank_close(),
        run_pin_toggle(),
    ]
    # 清理测试可能留下的文件
    for name in ("__synthtest__", "__stored__", "close me", "do not keep",
                 "改名后", "改名了", "pin"):
        for p in SOLVE.glob(f"{name}*.txt"):
            p.unlink(missing_ok=True)
    print("RESULT", "OK" if all(results) else "FAIL")
    sys.exit(0 if all(results) else 1)
