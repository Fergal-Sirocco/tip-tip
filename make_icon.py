"""生成 tiptip.ico（多尺寸图标），供 PyInstaller --icon 使用。可选步骤。"""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice

from icon import render_icon_image


def build_ico(path: Path, sizes=(16, 32, 48, 64, 128, 256)) -> None:
    """把各尺寸的 PNG 打包成多尺寸 ICO 文件（Vista+ 均支持 PNG 条目）。"""
    png_blobs = []
    for s in sizes:
        img = render_icon_image(s)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        png_blobs.append(bytes(buf.data()))
        buf.close()

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(png_blobs)))  # ICONDIR
        offset = 6 + 16 * len(png_blobs)
        for s, data in zip(sizes, png_blobs):
            dim = 0 if s >= 256 else s  # ICO 中 256 用 0 表示
            f.write(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset))
            offset += len(data)
        for data in png_blobs:
            f.write(data)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "tiptip.ico"
    build_ico(out)
    print("icon written:", out)
