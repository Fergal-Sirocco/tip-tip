"""便签窗口：无边框、可拖拽移动/缩放、置顶开关、透明度调节、富文本编辑。

- 顶部标题框：单击正常编辑标题；按住并拖动超过阈值则移动整个窗口。
  也可抓标题栏空白/手柄（⠿），或按住中键在便签任意位置拖动。
- 缩放：Windows 下通过 WM_NCHITTEST 让系统接管四边/四角的原生缩放；
  其他平台用右下角 QSizeGrip 兜底。
- 图片：可粘贴剪贴板图片、把图片文件拖入便签、或右键菜单选图插入；
  保存时统一转成 Base64 data URI 内嵌进 HTML，保证一个便签只有一个 .txt。
- 文件名：标题非空 → 【标题】.txt；标题为空 → 【正文第一行】.txt；
  同名自动追加 _1/_2 后缀；标题与正文全空不生成文件。
- 保存：内容/标题修改、移动、缩放后 1.2 秒防抖自动保存。
- 关闭：已储存便签——加载时记录原始标题/正文，内容未变化直接关闭；
  已修改时弹三选项（保存 / 不保存·还原原始状态 / 取消继续编辑）。
  新建便签——空则直接销毁，有内容询问保存/丢弃；程序退出时静默保存。
"""
from __future__ import annotations

import base64
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]

from PySide6.QtCore import (QByteArray, QBuffer, QEvent, QIODevice, QPoint,
                            QRect, QRectF, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QActionGroup, QColor, QGuiApplication, QImage,
                           QPainter, QPen, QPixmap, QTextDocument)
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QMessageBox, QSizeGrip,
                               QTextEdit, QToolButton, QVBoxLayout, QWidget)

import storage

# ---------- 外观与行为常量 ----------
NOTE_BG = QColor("#FFF8DC")   # 便签底色（暖黄，接近纸张）
RADIUS = 10                   # 圆角半径
TITLE_HEIGHT = 30             # 标题栏高度
EDGE = 6                      # 边缘缩放判定宽度
MIN_W, MIN_H = 240, 150
MAX_IMG_W = 1200              # 插入图片超过该宽度时等比缩小，控制文件体积
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico", ".tif", ".tiff"}
_IMG_SRC_RE = re.compile(r'<img[^>]*src="([^"]+)"[^>]*>')

# WM_NCHITTEST 返回值
HT_LEFT, HT_RIGHT, HT_TOP, HT_BOTTOM = 10, 11, 12, 15
HT_TOPLEFT, HT_TOPRIGHT, HT_BOTTOMLEFT, HT_BOTTOMRIGHT = 13, 14, 16, 17

QSS = """
QWidget#titleBar { background: transparent; }
QLabel#gripLabel { color: #b3a67f; font-size: 14px; }
QLineEdit#titleEdit {
    background: transparent; border: none; color: #7a6a42;
    font-size: 13px; font-weight: 600; padding: 0 4px;
}
QToolButton {
    border: none; background: transparent; border-radius: 4px;
    color: #9a8a5a; font-size: 13px;
}
QToolButton:hover { background: rgba(0, 0, 0, 0.07); }
QToolButton:checked { background: rgba(255, 183, 0, 0.35); }
QToolButton#closeButton:hover { background: #e5533d; color: #ffffff; }
QTextEdit { background: transparent; border: none; color: #3a3a3a; font-size: 14px; }
"""


class _TitleBar(QWidget):
    """标题栏：左键按住拖拽移动整个便签窗口（手动实现，可靠且跨平台）。"""

    def __init__(self, note_window: "NoteWindow"):
        super().__init__(note_window)
        self._note = note_window
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLE_HEIGHT)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._note.begin_manual_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._note.is_dragging():
            self._note.drag_to(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._note.is_dragging() and event.button() == Qt.MouseButton.LeftButton:
            self._note.end_manual_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _DragTitleEdit(QLineEdit):
    """标题输入框：单击正常编辑；按住并拖动超过系统阈值则移动整个便签窗口。"""

    def __init__(self, note_window: "NoteWindow", parent=None):
        super().__init__(parent)
        self._note = note_window
        self._press_global = None
        self._drag_started = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is not None and not self._drag_started:
            delta = event.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._drag_started = True
                self.deselect()  # 清除拖拽起点可能产生的选区
                self._note.begin_manual_drag(self._press_global)
                self._note.drag_to(event.globalPosition().toPoint())  # 立即应用到当前点
                return
        if self._drag_started:
            self._note.drag_to(event.globalPosition().toPoint())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_started and event.button() == Qt.MouseButton.LeftButton:
            self._note.end_manual_drag()
            self._drag_started = False
            self._press_global = None
            return
        self._press_global = None
        super().mouseReleaseEvent(event)


class _NoteEditor(QTextEdit):
    """富文本编辑区：支持拖入图片文件；按住中键可拖拽整个便签窗口。

    注意：QTextEdit 是滚动区域，文本区上的鼠标事件实际投递给 viewport
    子控件（不会走本类的 mousePressEvent），因此用事件过滤器在 viewport
    上拦截中键拖拽。
    """

    imageDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            win = self.window()
            is_note = isinstance(win, NoteWindow)
            if event.type() == QEvent.Type.MouseButtonPress \
                    and event.button() == Qt.MouseButton.MiddleButton and is_note:
                win._begin_editor_drag(self, event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and is_note and win.is_dragging():
                win.drag_to(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and is_note \
                    and win.is_dragging() \
                    and event.button() == Qt.MouseButton.MiddleButton:
                win._end_editor_drag(self)
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if self._first_image_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        path = self._first_image_path(event.mimeData())
        if path:
            self.imageDropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    @staticmethod
    def _first_image_path(mime) -> str | None:
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile():
                p = url.toLocalFile()
                if Path(p).suffix.lower() in IMAGE_EXTS:
                    return p
        return None


class NoteWindow(QWidget):
    closed_signal = Signal(object)

    def __init__(self, filename: str, html: str, meta: dict,
                 on_new_note=None, on_quit=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._filename = filename  # 可能为 None（新建、尚未保存）
        self.note_id = str(meta.get("id") or storage.new_note_id())
        self.on_new_note = on_new_note
        self.on_quit = on_quit
        self._ready = False      # 初始化完成前不触发自动保存
        self._deleted = False
        self._quitting = False   # 程序退出时静默保存，不弹关闭确认框
        self._dragging = False   # 手动拖拽状态
        self._drag_offset = QPoint()
        self._editor_cursor = None
        self._last_geo = QRect(160, 120, 340, 380)
        self._grip: QSizeGrip | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self.save_now)

        self._build_ui()
        self._apply_meta(meta)
        if filename:
            # 启动恢复：文件名填入标题框，正文由下面的 setHtml 加载
            self.title_edit.setText(Path(filename).stem)
        self.editor.setHtml(html)
        # 原始状态记录：仅对从磁盘恢复的已储存便签生效（新建便签为 None）
        if filename:
            self.original_filename = filename
            self.original_title = self.title_edit.text().strip()
            self.original_content = self.editor.toHtml()
        else:
            self.original_filename = None
            self.original_title = None
            self.original_content = None
        self._last_geo = self.geometry()
        self._ready = True
        self._schedule_save()

    # ---------- 界面构建 ----------

    def _build_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(MIN_W, MIN_H)

        # 标题栏（左键拖拽移动，右键打开菜单）
        bar = _TitleBar(self)
        self.title_bar = bar

        grip_label = QLabel("⠿", bar)
        grip_label.setObjectName("gripLabel")
        grip_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        grip_label.setCursor(Qt.CursorShape.OpenHandCursor)

        self.title_edit = _DragTitleEdit(self, bar)
        self.title_edit.setObjectName("titleEdit")
        self.title_edit.setPlaceholderText("标题")
        self.title_edit.textChanged.connect(self._on_title_changed)

        self.pin_btn = QToolButton(bar)
        self.pin_btn.setObjectName("pinButton")
        self.pin_btn.setText("📌")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("置顶显示")
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setFixedSize(22, 22)
        self.pin_btn.toggled.connect(self._on_pin_toggled)

        close_btn = QToolButton(bar)
        close_btn.setObjectName("closeButton")
        close_btn.setText("✕")
        close_btn.setToolTip("关闭便签（弹出保存确认）")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.close)

        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 0, 6, 0)
        bar_layout.setSpacing(4)
        bar_layout.addWidget(grip_label)
        bar_layout.addWidget(self.title_edit, 1)
        bar_layout.addWidget(self.pin_btn)
        bar_layout.addWidget(close_btn)

        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(
            lambda pos: self._popup_menu(bar.mapToGlobal(pos), include_edit=False))

        # 编辑区
        self.editor = _NoteEditor(self)
        self.editor.setAcceptRichText(True)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.viewport().setAutoFillBackground(False)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._on_editor_menu)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.imageDropped.connect(self.insert_image_file)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.editor, 1)

        # 非 Windows 平台的缩放兜底
        if sys.platform != "win32":
            self._grip = QSizeGrip(self)

        self.setStyleSheet(QSS)

    def _apply_meta(self, meta: dict):
        rect = QRect(160, 120, 340, 380)
        geo = meta.get("geometry")
        if isinstance(geo, (list, tuple)) and len(geo) == 4:
            try:
                rect = QRect(int(geo[0]), int(geo[1]), int(geo[2]), int(geo[3]))
            except (TypeError, ValueError):
                rect = QRect(160, 120, 340, 380)
            rect = self._ensure_on_screen(rect)
        self.setGeometry(rect)
        self.setWindowOpacity(float(meta.get("opacity", 1.0)))
        self._set_on_top(bool(meta.get("ontop", True)))

    @staticmethod
    def _ensure_on_screen(rect: QRect) -> QRect:
        """窗口连标题栏都不在任何屏幕内时（换了显示器/分辨率），移到主屏居中。"""
        strip = QRect(rect.x(), rect.y(), rect.width(), min(rect.height(), TITLE_HEIGHT * 2))
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(strip):
                return rect
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return rect
        rect.moveCenter(screen.availableGeometry().center())
        return rect

    # ---------- 窗口行为：缩放 / 置顶 / 透明度 ----------

    def nativeEvent(self, eventType, message):
        # Windows：通过 WM_NCHITTEST 让系统接管四边/四角的原生缩放
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                code = self._hit_test_code(msg)
                if code is not None:
                    return True, code
        return super().nativeEvent(eventType, message)

    def _hit_test_code(self, msg) -> int | None:
        # WM_NCHITTEST 的光标坐标是物理像素，而 Qt 的窗口几何是逻辑坐标；
        # 高 DPI（如 150% 缩放）下不换算的话，边缘判定区域会错位到窗口内部，
        # 把大半个编辑区当成缩放区，导致点击被系统吞掉、无法拖拽和输入。
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        dpr = self.devicePixelRatioF()
        r = self.frameGeometry()
        edge = EDGE * dpr
        left = r.left() * dpr
        right = (r.left() + r.width()) * dpr
        top = r.top() * dpr
        bottom = (r.top() + r.height()) * dpr
        is_left = x < left + edge
        is_right = x >= right - edge
        is_top = y < top + edge
        is_bottom = y >= bottom - edge
        if is_top and is_left:
            return HT_TOPLEFT
        if is_top and is_right:
            return HT_TOPRIGHT
        if is_bottom and is_left:
            return HT_BOTTOMLEFT
        if is_bottom and is_right:
            return HT_BOTTOMRIGHT
        if is_left:
            return HT_LEFT
        if is_right:
            return HT_RIGHT
        if is_top:
            return HT_TOP
        if is_bottom:
            return HT_BOTTOM
        return None

    def _set_on_top(self, on: bool):
        """切换总在最前。

        已知 Bug 修复：setWindowFlags 会因内部重新挂接原生窗口而把窗口隐藏，
        因此必须先 show() 强制确保窗口可见，设置标志后再无条件 show() 恢复
        显示；否则取消置顶时窗口会意外消失。重新设置标志时只增减
        WindowStaysOnTopHint，同时保留 Window 与 FramelessWindowHint。
        """
        self.show()  # 先强制确保窗口可见
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()  # setWindowFlags 会再次隐藏窗口，必须重新显示
        self.pin_btn.setChecked(on)

    def _on_pin_toggled(self, on: bool):
        self._set_on_top(on)
        self._schedule_save()

    def _is_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    # ---------- 手动拖拽（标题栏左键 / 编辑区中键共用） ----------

    def begin_manual_drag(self, global_pos: QPoint):
        self._dragging = True
        self._drag_offset = self.pos() - global_pos
        self.title_bar.setCursor(Qt.CursorShape.ClosedHandCursor)

    def is_dragging(self) -> bool:
        return self._dragging

    def drag_to(self, global_pos: QPoint):
        if self._dragging:
            self.move(global_pos + self._drag_offset)

    def end_manual_drag(self):
        if not self._dragging:
            return
        self._dragging = False
        self.title_bar.setCursor(Qt.CursorShape.OpenHandCursor)

    def _begin_editor_drag(self, editor: QTextEdit, global_pos: QPoint):
        self._editor_cursor = editor.cursor()
        editor.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.begin_manual_drag(global_pos)

    def _end_editor_drag(self, editor: QTextEdit):
        editor.setCursor(getattr(self, "_editor_cursor", Qt.CursorShape.IBeamCursor))
        self.end_manual_drag()

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(0, 0, 0, 45)))
        painter.setBrush(NOTE_BG)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
        painter.setPen(QPen(QColor(0, 0, 0, 16)))
        painter.drawLine(rect.left() + 2, rect.top() + TITLE_HEIGHT,
                         rect.right() - 2, rect.top() + TITLE_HEIGHT)
        super().paintEvent(event)

    # ---------- 图片 ----------

    def insert_image_file(self, path: str):
        img = QImage(str(path))
        if img.isNull():
            QMessageBox.warning(self, "tiptip", f"无法读取图片：\n{path}")
            return
        self._insert_image(img)

    def _insert_image(self, img: QImage):
        if img.width() > MAX_IMG_W:
            img = img.scaledToWidth(MAX_IMG_W, Qt.TransformationMode.SmoothTransformation)
        name = f"tiptip_img_{uuid4().hex[:8]}"
        doc = self.editor.document()
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
        cursor = self.editor.textCursor()
        cursor.insertHtml(f'<img src="{name}" />')
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._schedule_save()

    def _choose_image_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "插入图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.ico *.tif *.tiff)")
        if path:
            self.insert_image_file(path)

    # ---------- 保存 ----------

    def _on_text_changed(self):
        self._schedule_save()

    def _on_title_changed(self, text):
        self._schedule_save()

    def _schedule_save(self):
        if not self._ready:
            return
        if not self.isMinimized():
            self._last_geo = self.geometry()
        self._save_timer.start()

    def save_now(self):
        if not self._ready:
            return
        self._save_timer.stop()
        images = self._document_images()
        new_name = storage.derive_filename(
            self.title_edit.text(), self.editor.toPlainText(), bool(images),
            storage.get_solve_dir(), self._filename)
        if new_name is None:
            self._discard_file()  # 标题与正文全空：不生成文件
            return
        storage.save_note(new_name, self._html_with_images(images), self._collect_meta())
        if self._filename and self._filename != new_name:
            # 标题/正文首行变化导致文件名改变：删除旧文件
            (storage.get_solve_dir() / self._filename).unlink(missing_ok=True)
        self._filename = new_name

    def _collect_meta(self) -> dict:
        geo = self._last_geo
        if geo.isEmpty():
            geo = self.geometry()
        return {
            "id": self.note_id,
            "title": self.title_edit.text().strip(),
            "geometry": [geo.x(), geo.y(), geo.width(), geo.height()],
            "opacity": round(self.windowOpacity(), 2),
            "ontop": self._is_on_top(),
            "modified": datetime.now().isoformat(timespec="seconds"),
        }

    def _html_with_images(self, images: list[QImage] | None = None) -> str:
        """把文档里的图片全部转为 Base64 data URI 后再序列化成 HTML。"""
        html = self.editor.toHtml()
        images = images if images is not None else self._document_images()
        if not images:
            return html

        def replace_src(match: re.Match) -> str:
            tag, src = match.group(0), match.group(1)
            if src.startswith("data:"):  # 已经是内嵌图片
                return tag
            if images:
                return tag.replace(f'src="{src}"', f'src="{self._to_data_uri(images.pop(0))}"', 1)
            return tag

        return _IMG_SRC_RE.sub(replace_src, html)

    def _document_images(self) -> list[QImage]:
        """按文档顺序取出所有图片（来自 QTextDocument 内部资源）。"""
        result: list[QImage] = []
        doc = self.editor.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fmt = it.fragment().charFormat()
                if fmt.isImageFormat():
                    img = None
                    # Qt6 中图片数据以资源形式存放在 QTextDocument 上（QPixmap 或 QImage）
                    res = doc.resource(QTextDocument.ResourceType.ImageResource,
                                       QUrl(fmt.toImageFormat().name()))
                    if isinstance(res, QImage):
                        img = res
                    elif isinstance(res, QPixmap):
                        img = res.toImage()
                    if img is not None and not img.isNull():
                        result.append(img)
                it += 1
            block = block.next()
        return result

    @staticmethod
    def _to_data_uri(img: QImage) -> str:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buffer, "PNG")
        buffer.close()
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")

    # ---------- 右键菜单 ----------

    def _on_editor_menu(self, pos):
        self._popup_menu(self.editor.viewport().mapToGlobal(pos), include_edit=True)

    def _popup_menu(self, global_pos, include_edit: bool):
        menu = QMenu(self)
        if include_edit:
            menu.addMenu(self.editor.createStandardContextMenu()).setTitle("编辑")
            menu.addSeparator()

        act_img = menu.addAction("插入图片…")
        menu.addSeparator()
        act_top = menu.addAction("置顶显示")
        act_top.setCheckable(True)
        act_top.setChecked(self._is_on_top())
        opacity_menu = menu.addMenu("透明度")
        opacity_actions: dict = {}
        group = QActionGroup(opacity_menu)
        for v in (100, 90, 80, 70, 60, 50, 40):
            a = opacity_menu.addAction(f"{v}%")
            a.setCheckable(True)
            a.setChecked(abs(self.windowOpacity() * 100 - v) < 1.5)
            group.addAction(a)
            opacity_actions[a] = v
        menu.addSeparator()
        act_new = menu.addAction("新建便签\tCtrl+T")
        act_del = menu.addAction("删除便签")
        menu.addSeparator()
        act_quit = menu.addAction("退出程序")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_img:
            self._choose_image_file()
        elif chosen is act_top:
            self._set_on_top(act_top.isChecked())
            self._schedule_save()
        elif chosen in opacity_actions:
            self.setWindowOpacity(opacity_actions[chosen] / 100)
            self._schedule_save()
        elif chosen is act_new and self.on_new_note is not None:
            self.on_new_note()
        elif chosen is act_del:
            self.delete_note()
        elif chosen is act_quit and self.on_quit is not None:
            self.on_quit()

    # ---------- 删除 / 关闭 ----------

    def _is_blank(self) -> bool:
        """标题与正文（含图片）全空。"""
        return (not self.title_edit.text().strip()
                and not self.editor.toPlainText().strip()
                and not self._document_images())

    def _is_modified(self) -> bool:
        """变更检测：已储存便签的标题或正文（含格式与图片）是否发生变化。"""
        if self.original_title is None:
            return False  # 新建便签没有原始状态，不走此判断
        return (self.title_edit.text().strip() != self.original_title
                or self.editor.toHtml() != self.original_content)

    def _revert_to_original(self):
        """不保存：把标题、正文和磁盘文件还原为加载时的原始状态。"""
        self._save_timer.stop()
        self._ready = False  # 还原期间不触发防抖自动保存
        try:
            self.title_edit.setText(self.original_title)
            self.editor.setHtml(self.original_content)
        finally:
            self._ready = True
        # 若自动保存已把文件改名（标题变化），删除改名后的文件
        if self._filename and self._filename != self.original_filename:
            (storage.get_solve_dir() / self._filename).unlink(missing_ok=True)
        meta = self._collect_meta()
        meta["title"] = self.original_title
        storage.save_note(self.original_filename, self.original_content, meta)
        self._filename = self.original_filename

    def _discard_file(self):
        """废弃便签对应的本地文件（如果有）。"""
        if self._filename:
            (storage.get_solve_dir() / self._filename).unlink(missing_ok=True)

    def delete_note(self):
        answer = QMessageBox.question(
            self, "删除便签", "确定删除这个便签吗？\n对应的 .txt 文件也会从磁盘移除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._deleted = True
        self._discard_file()
        self.close()

    def closeEvent(self, event):
        if not self._quitting and not self._deleted:
            if self.original_title is None:
                # 新建便签（无原始状态）：沿用原有逻辑——
                # 标题与正文全空直接销毁；有内容询问保存/丢弃
                if self._is_blank():
                    self._discard_file()
                else:
                    answer = QMessageBox.question(
                        self, "关闭便签",
                        "要保存这个便签吗？\n\n是：保存正文并关闭\n否：不保存，丢弃该便签",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes)
                    if answer == QMessageBox.StandardButton.Yes:
                        self.save_now()
                    else:
                        self._discard_file()
            elif self._is_modified():
                # 已储存便签且被修改：三选项提示框
                answer = QMessageBox.question(
                    self, "关闭便签",
                    "便签已修改，是否保存？\n\n"
                    "保存：写入当前修改并关闭\n"
                    "不保存：还原为原始内容并关闭\n"
                    "取消：返回继续编辑",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save)
                if answer == QMessageBox.StandardButton.Save:
                    self.save_now()  # 标题变化时自动改名并删除旧文件
                elif answer == QMessageBox.StandardButton.Discard:
                    self._revert_to_original()
                else:  # Cancel
                    event.ignore()  # 取消关闭，继续编辑
                    return
            else:
                # 内容未变化：不弹提示，静默保存（仅持久化窗口位置等状态）
                self.save_now()
        self.closed_signal.emit(self)
        super().closeEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._grip is not None:
            self._grip.move(self.width() - self._grip.width() - 1,
                            self.height() - self._grip.height() - 1)
        self._schedule_save()
