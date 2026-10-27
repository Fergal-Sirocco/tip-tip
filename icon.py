"""程序图标：代码绘制，不依赖任何外部资源文件，打包时无需附带图片。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF

NOTE_COLOR = QColor("#FFD54F")
BORDER_COLOR = QColor("#D4A017")


def render_icon_image(size: int = 256) -> QImage:
    """绘制便签图标（圆角方块 + 右上折角），返回带透明通道的 QImage。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m = max(1.0, size * 0.05)
    body = QRectF(m, m, size - 2 * m, size - 2 * m)
    p.setPen(QPen(BORDER_COLOR, max(1.0, size * 0.025)))
    p.setBrush(NOTE_COLOR)
    p.drawRoundedRect(body, size * 0.18, size * 0.18)
    # 右上折角
    fold = size * 0.28
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 215))
    p.drawPolygon(QPolygonF([
        QPointF(body.right() - fold, body.top()),
        QPointF(body.right(), body.top()),
        QPointF(body.right(), body.top() + fold),
    ]))
    p.end()
    return img


def make_app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render_icon_image(s)))
    return icon
