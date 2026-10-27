"""文件名生成规则测试（纯逻辑，不依赖窗口）。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage


def check(name, got, expect):
    ok = got == expect
    print(f"CASE {name}: got={got!r} expect={expect!r} => {'OK' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="tiptip_rules_"))
    ok = True
    ok &= check("标题优先", storage.derive_filename("待办", "正文第一行", False, tmp), "待办.txt")
    ok &= check("标题为空取首行", storage.derive_filename("", "第一行\n第二行", False, tmp), "第一行.txt")
    ok &= check("标题与正文全空", storage.derive_filename("", "", False, tmp), None)
    ok &= check("纯图片无文字", storage.derive_filename("", "", True, tmp), "无标题.txt")
    ok &= check("非法字符清理", storage.derive_filename("a/b:c*d?", "", False, tmp), "a_b_c_d_.txt")
    ok &= check("只有非法字符的标题回退首行", storage.derive_filename("///", "正文", False, tmp), "正文.txt")
    (tmp / "待办.txt").write_text("x", encoding="utf-8")
    ok &= check("重名加后缀", storage.derive_filename("待办", "", False, tmp), "待办_1.txt")
    (tmp / "待办_1.txt").write_text("x", encoding="utf-8")
    ok &= check("后缀继续递增", storage.derive_filename("待办", "", False, tmp), "待办_2.txt")
    ok &= check("忽略自己当前文件", storage.derive_filename("待办", "", False, tmp, "待办.txt"), "待办.txt")
    ok &= check("Windows保留名加前缀", storage.derive_filename("CON", "", False, tmp), "_CON.txt")
    ok &= check("长标题截断", storage.derive_filename("标" * 120, "", False, tmp), "标" * 80 + ".txt")
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    print("RESULT", "OK" if ok else "FAIL")
    sys.exit(0 if ok else 1)
