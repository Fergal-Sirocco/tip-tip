"""启动流程测试：单实例锁与首次启动"使用指南"生成。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

import main as tiptip_main
import storage

app = QApplication(sys.argv)

# ---------- 单实例锁 ----------
ok_lock = True
lock1 = tiptip_main.acquire_single_instance_lock()
ok_lock &= lock1 is not None
lock2 = tiptip_main.acquire_single_instance_lock()
ok_lock &= lock2 is None  # 模拟第二个实例：应获取失败
lock1.unlock()  # 释放后应能再次获取
lock3 = tiptip_main.acquire_single_instance_lock()
ok_lock &= lock3 is not None
lock3.unlock()
print("CASE single-instance:", "OK" if ok_lock else "FAIL")

# ---------- 首次启动"使用指南" ----------
tmp = Path(tempfile.mkdtemp(prefix="tiptip_guide_"))
real_get_solve = storage.get_solve_dir
storage.get_solve_dir = lambda: tmp
try:
    ok_guide = True
    ok_guide &= tiptip_main.is_first_launch() is True
    created = tiptip_main.create_guide_note()
    ok_guide &= created is not None and created.exists() and created.name == "使用指南.txt"
    text = created.read_text(encoding="utf-8")
    ok_guide &= all(k in text for k in ("使用指南", "Ctrl", "+&nbsp;T", "save", "Discard", "Cancel"))
    ok_guide &= tiptip_main.is_first_launch() is False
    ok_guide &= tiptip_main.create_guide_note() is None  # 已存在便签文件：不再生成
    # 恢复路径验证：load_all_notes 能读回标题与正文
    notes = storage.load_all_notes()
    loaded_html = next((h for f, h, _ in notes if f == "使用指南.txt"), None)
    ok_guide &= loaded_html is not None and "保存" in loaded_html
    print("CASE first-launch-guide:", "OK" if ok_guide else "FAIL")
finally:
    storage.get_solve_dir = real_get_solve
    shutil.rmtree(tmp, ignore_errors=True)

print("RESULT", "OK" if (ok_lock and ok_guide) else "FAIL")
sys.exit(0 if (ok_lock and ok_guide) else 1)
