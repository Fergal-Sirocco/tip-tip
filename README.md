# tiptip — 极简桌面便签

基于 PySide6 (Qt for Python) 的轻量桌面便签工具：无边框窗口、全局快捷键一键新建、内容（含图片）单文件保存，可用 PyInstaller 打包成 Windows 单文件 exe 便携运行。

## 功能特性

- 极简无边框窗口：顶部有单行标题框（单击编辑、按住拖动可移动窗口），抓标题栏空白/手柄（⠿）或在便签任意位置按住鼠标中键拖拽移动；右上角 ✕ 关闭（弹出保存确认）；Windows 下拖拽任意边缘/角落原生缩放（其他平台用右下角 QSizeGrip 兜底）。
- 标题即文件名：文件名 = 标题框内容（标题为空时自动取正文第一行，全空但有图片时用"无标题"）；同名文件自动追加 _1/_2 后缀；标题与正文全空不生成文件。
- 关闭确认（变更还原）：已储存便签在加载时记录原始标题/正文——内容未变化直接关闭；已修改时弹三选项：保存（写入修改，标题变化自动改名并删除旧文件）、不保存（标题、正文与文件还原为加载时的原始状态）、取消（继续编辑）。新建便签不受影响：空则直接销毁，有内容询问保存/丢弃。
- 窗口置顶：默认总在最前，标题栏 📌 按钮或右键菜单随时开关。
- 半透明：右键菜单 → 透明度，可选 40% ~ 100%。
- 富文本便签：基于 QTextEdit，支持插入图片，三种方式：
  - 复制图片后 Ctrl+V 粘贴；
  - 直接把图片文件拖进便签；
  - 右键菜单 → 插入图片…。
- 全局快捷键 Ctrl+T：无论焦点在哪个程序，立即新建空白便签。基于 Win32 RegisterHotKey + ctypes，不依赖 pywin32；被其他程序占用时自动降级并弹窗提示，不会崩溃；退出时自动释放。
- 单文件存储：每个便签保存为 tiptip/Solve 下的一个 .txt；图片以 Base64 内嵌在 HTML 中，文字图片同文件，便于迁移和恢复。
- 实时保存：内容修改/移动/缩放后 1.2 秒防抖自动保存，关闭时立即落盘；启动时自动恢复全部便签（含位置、透明度、置顶状态）。
- 系统托盘：双击托盘图标新建便签；右键菜单可新建 / 打开数据文件夹 / 退出。关闭所有便签窗口后程序仍在后台运行，Ctrl+T 依然可用。
- 单实例运行：基于 QLockFile（锁文件 %USERPROFILE%\.tiptip\app.lock），重复启动会提示「便签已在运行中」并自动退出。
- 首次启动指南：tiptip/Solve 目录为空时自动生成一张标题为「使用指南」的便签（介绍 Ctrl+T 新建与保存/不保存/取消三个关闭选项），已有便签文件时不再生成。

## 目录结构

| 文件 | 说明 |
| --- | --- |
| main.py | 程序入口：应用外壳、窗口管理、托盘、退出时保存、--smoke 自检 |
| note_window.py | 便签窗口类：拖拽/缩放/置顶/透明度/富文本与图片内嵌 |
| hotkey.py | 全局快捷键 Ctrl+T（注册/冲突检测/释放） |
| storage.py | 路径解析与 .txt 读写（exe 目录优先，只读时回退用户目录） |
| icon.py / make_icon.py | 代码绘制程序图标 / 生成多尺寸 tiptip.ico |
| tests/synth_test.py | 交互回归测试（合成事件验证拖拽与关闭按钮） |
| build.bat | 一键打包脚本 |
| requirements.txt | 依赖清单（PySide6-Essentials + pyinstaller） |

## 源码运行

bash
python -m pip install -r requirements.txt
python main.py


## 数据存储

- 保存目录：程序（exe 或源码）所在目录下的 tiptip/Solve/，不存在时自动创建。
- 若 exe 所在目录不可写（如 C:\Program Files），自动回退到 %USERPROFILE%\tiptip\Solve，并在启动时弹窗提示实际使用的目录。
- 文件名由便签内容决定：标题非空用【标题】，否则用【正文第一行】（同名自动加 _1/_2 后缀，标题变化时自动改名并删除旧文件）。每个 .txt 是 UTF-8 编码的 HTML（图片为 Base64 data URI），文件末尾一行 <!--TIPMETA-->… 注释保存窗口位置、透明度、置顶等元数据。
- 迁移/备份：把整个数据目录拷贝到新位置即可，所有便签（含图片）原样恢复。

## 打包为 Windows 单文件 exe

一键打包（自动装依赖、生成图标、PyInstaller 打包、自检验证）：

bat
build.bat


等价的手动命令：

bat
python -m pip install -r requirements.txt
python make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name tiptip --icon tiptip.ico main.py


产物在 dist\tiptip.exe。

### 打包注意事项

1. --noconsole：不出现黑色控制台窗口（程序输出全部走 Qt，无命令行需求）。
2. 单文件启动慢：onefile 模式启动时会把 Python 运行时解压到 %TEMP%，首次启动约 1~3 秒属正常；介意可去掉 --onefile 改用 onedir（目录版，启动快但文件多）。
3. 路径完全动态：数据目录基于 sys.executable（exe 位置）或源码位置解析，没有硬编码绝对路径。注意 onefile 模式下 sys.executable 是 exe 本身的位置（而不是解压后的临时目录 sys._MEIPASS），因此数据始终落在 exe 旁边。exe 放到任意可写目录都能正常工作，便携使用建议放在自己的文件夹（如 D:\tiptip\dist）。
4. 杀软误报：PyInstaller onefile 产物偶尔被 Defender/360 等误报，添加信任即可；改用 onedir 模式或做代码签名可以缓解。
5. 依赖体积：使用 PySide6-Essentials（QtWidgets 核心部分）控制体积，无需 QtWebEngine；若本机已装完整 PySide6 同样兼容。
6. 重新打包：升级 PySide6/PyInstaller 后打包异常，先删掉 build/ 和 .spec 再打包（--clean 已包含大部分清理）。
7. 打包后自检：运行 dist\tiptip.exe --smoke，输出 SMOKE OK 表示存储读写、图片内嵌、快捷键注册全部正常（自检不显示任何窗口）。
8. 多开冲突：同一时间只应运行一个实例；第二个实例会提示 Ctrl+T 注册失败（这正是冲突检测在工作），建议退出第一个实例。
9. Python 版本：需要 Python 3.9+（PySide6 要求），3.10 ~ 3.12 均可。

## 常见问题

- Ctrl+T 没反应：先确认程序在后台运行（托盘有图标）。若启动时提示注册失败，说明快捷键被其他程序（QQ、输入法等）占用，可从托盘或便签右键菜单新建。
- 便签数据在哪：托盘右键 → 打开数据文件夹。
- 怎么彻底退出：托盘右键 → 退出程序（退出前会保存所有便签）。
- 开机自启：把 dist\tiptip.exe 的快捷方式放进 shell:startup 文件夹即可。
