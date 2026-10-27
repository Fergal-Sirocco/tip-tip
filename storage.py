"""存储层：路径解析与便签文件的读写。

- 数据目录：<exe 或源码所在目录>/tiptip/Solve；该目录不可写时自动回退到
  <用户主目录>/tiptip/Solve（例如 exe 被放在 Program Files 等只读位置时）。
- 每个便签一个 .txt：UTF-8 编码的 HTML（图片以 Base64 data URI 内嵌），
  文件末尾附一行 <!--TIPMETA-->json 注释，保存窗口位置、透明度等元数据。
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

META_TAG = "<!--TIPMETA-->"
_META_RE = re.compile(re.escape(META_TAG) + r"(.*)$", re.DOTALL)


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".tiptip_writetest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def preferred_root() -> Path:
    """按规则首选的数据根目录：exe（或源码）所在目录。可能不可写。"""
    if is_frozen():
        # onefile 模式下 sys.executable 是 exe 本身的位置，
        # 而不是解压后的临时目录（sys._MEIPASS），这正是我们需要的。
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_data_root() -> Path:
    """实际使用的数据根目录：首选目录不可写时回退到用户主目录。"""
    candidate = preferred_root()
    return candidate if _is_writable(candidate) else Path.home()


def get_solve_dir() -> Path:
    """tiptip/Solve 目录；不存在时自动创建。"""
    solve = get_data_root() / "tiptip" / "Solve"
    solve.mkdir(parents=True, exist_ok=True)
    return solve


def new_note_id() -> str:
    return uuid.uuid4().hex[:16]


_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_RESERVED_NAMES = ({"CON", "PRN", "AUX", "NUL"}
                   | {f"COM{i}" for i in range(1, 10)}
                   | {f"LPT{i}" for i in range(1, 10)})
MAX_FILENAME_BASE = 80


def sanitize_filename_base(base: str) -> str:
    """清理标题/正文首行中不能作为文件名的字符，返回可用的文件名主干。"""
    base = re.sub(r"[\x00-\x1f​￼]+", " ", base)  # 控制字符、对象占位符
    base = _ILLEGAL_FILENAME.sub("_", base)
    base = base.strip().rstrip(". ")
    if not base:
        return ""
    if not re.search(r"[^\W_]", base):  # 清理后只剩符号（如全非法字符的标题）
        return ""
    if base.upper() in _RESERVED_NAMES:  # Windows 保留设备名
        base = "_" + base
    if len(base) > MAX_FILENAME_BASE:
        base = base[:MAX_FILENAME_BASE].rstrip(". ")
    return base


def derive_filename(title: str, body_text: str, has_images: bool,
                    solve_dir: Path, own_filename: str | None = None) -> str | None:
    """按规则生成文件名（返回含 .txt 的完整文件名）：

    1. 标题非空 → 用标题；2. 标题为空且正文非空 → 用正文第一行；
    3. 只有图片没有文字 → "无标题"；4. 标题与正文全空 → None（不保存）。
    同名文件已存在时自动追加 _1、_2 … 后缀（忽略便签自己当前的文件名）。
    """
    base = ""
    title = (title or "").strip()
    if title:
        base = sanitize_filename_base(title)
    if not base:
        body = (body_text or "").strip()
        first = body.splitlines()[0].strip() if body else ""
        if first:
            base = sanitize_filename_base(first)
        elif has_images:
            base = "无标题"
    if not base:
        return None
    solve_dir = Path(solve_dir)
    existing = {p.name.lower() for p in solve_dir.glob("*.txt") if p.is_file()}
    if own_filename:
        existing.discard(Path(own_filename).name.lower())
    candidate = base + ".txt"
    n = 1
    while candidate.lower() in existing:
        candidate = f"{base}_{n}.txt"
        n += 1
    return candidate


def save_note(filename: str, html: str, meta: dict) -> Path:
    """原子写入（先写临时文件再替换），避免中途断电损坏便签。"""
    path = get_solve_dir() / filename
    meta.setdefault("id", new_note_id())
    payload = html.rstrip("\n") + "\n" + META_TAG + json.dumps(meta, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_all_notes() -> list[tuple[str, str, dict]]:
    """读取 Solve 目录下全部 .txt，返回 [(文件名, html, meta)]；损坏文件跳过。"""
    notes: list[tuple[str, str, dict]] = []
    for path in sorted(get_solve_dir().glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        html, meta = _parse(text)
        notes.append((path.name, html, meta))
    return notes


def _parse(text: str) -> tuple[str, dict]:
    m = _META_RE.search(text)
    meta: dict = {}
    if m:
        html = text[: m.start()].rstrip("\n")
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            pass  # 元数据损坏时忽略，正文仍然可用
    else:
        html = text
    meta.setdefault("id", new_note_id())
    return html, meta
