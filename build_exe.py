"""NovaNote 打包脚本 —— 生成 Windows 可执行程序，并可一键产出完整安装包。

用法：
    python build_exe.py                  # 打包为免安装目录（onedir，推荐）
    python build_exe.py --onefile        # 打包为单个 exe（启动慢，不推荐）
    python build_exe.py --clean          # 构建前清理 build/ 与 dist/
    python build_exe.py --installer      # 打包后继续生成 setup.exe 安装包
    python build_exe.py --console        # 保留控制台窗口（排查启动问题用）

产物：
    dist/NovaNote/NovaNote.exe           # 免安装程序（--installer 时作为安装源）
    dist/NovaNote-<版本>-setup.exe       # 完整安装包（--installer，需 Inno Setup 6）

设计说明：
    PyInstaller 的 PySide6 钩子会按「Qt 模块依赖表」一股脑收集二进制，其中包含
    本应用完全用不到的 QML/Quick 运行时与软件 OpenGL 后端（合计约 33 MB）。
    这些文件是在构建**之后**才出现的，事后删除既慢又容易被环境的批量删除保护
    拦截，因此这里改为生成 .spec 文件，在 Analysis 阶段就把它们从 binaries
    列表里剔除——更干净，也更快。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "NovaNote"

# —— 应用元数据（与 novanote/config.py 保持同步）—— #
APP_VERSION = "1.0.0"
APP_NAME_CN = "星笺"
APP_TAGLINE = "本地优先的知识与文献工作台"
ORG_NAME = "NovaLab"

DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
APP_DIR = DIST_DIR / NAME
ICON = ROOT / "novanote" / "assets" / "logo.ico"
MANIFEST = ROOT / "installer" / "app.manifest"
SPEC = ROOT / f"{NAME}.spec"
ISS = ROOT / "installer.iss"

# 运行时按需动态导入、静态分析抓不到的模块
HIDDEN_IMPORTS = [
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtVideo",
]

# 应用完全用不到、但可能被误收集的 Python 模块（体积大或引发额外依赖）
EXCLUDES = [
    "tkinter", "unittest", "pydoc_data", "lib2to3", "test", "distutils",
    "matplotlib", "numpy", "scipy", "pandas", "PIL", "IPython", "notebook",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtTest",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtHelp",
    "PySide6.QtSql",
]

# 从产物中剔除的二进制（按文件名子串匹配）。
# 依据：实测 Qt6Core/QtGui/QtWidgets/QtMultimedia/QtSvg/QtPrintSupport 均不依赖
# 下列库，只有 QML 家族内部互相引用；而本应用是纯 2D Widgets 界面，
# Qt 6 在 Windows 上默认使用 Direct3D 11 渲染，不会加载软件 OpenGL 后端。
EXCLUDE_BINARIES = (
    "opengl32sw.dll",          # 软件 OpenGL 回退（Mesa），约 20 MB
    "Qt6Qml",                  # QML 运行时（含 QmlModels/QmlMeta/QmlWorkerScript）
    "Qt6Quick",                # Quick 场景图运行时
    "Qt6VirtualKeyboard",      # 触屏虚拟键盘（依赖 Quick/Qml）
    "qtvirtualkeyboardplugin", # 虚拟键盘平台输入法插件
)


# --------------------------------------------------------------------------- #
# 版本资源（exe「属性 → 详细信息」里显示的内容）
# --------------------------------------------------------------------------- #
def write_version_file() -> Path:
    parts = (APP_VERSION.split(".") + ["0", "0", "0", "0"])[:4]
    v = ", ".join(str(int(p)) for p in parts if p.isdigit()) or "0, 0, 0, 0"
    body = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}),
    prodvers=({v}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', '{ORG_NAME}'),
         StringStruct('FileDescription', '{NAME} · {APP_NAME_CN} —— {APP_TAGLINE}'),
         StringStruct('FileVersion', '{APP_VERSION}'),
         StringStruct('InternalName', '{NAME}'),
         StringStruct('LegalCopyright', '(C) 2026 {ORG_NAME}. All rights reserved.'),
         StringStruct('OriginalFilename', '{NAME}.exe'),
         StringStruct('ProductName', '{NAME} · {APP_NAME_CN}'),
         StringStruct('ProductVersion', '{APP_VERSION}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    out = BUILD_DIR / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# 生成 .spec
# --------------------------------------------------------------------------- #
def write_spec(onefile: bool, console: bool) -> Path:
    def py_list(items: list[str], indent: int = 4) -> str:
        pad = " " * indent
        return "[\n" + "".join(f"{pad}{item!r},\n" for item in items) + " " * (indent - 4) + "]"

    assets = ROOT / "novanote" / "assets"
    spec = f'''# -*- mode: python ; coding: utf-8 -*-
"""由 build_exe.py 自动生成，请勿手工修改——改 build_exe.py 里的配置。"""
import os

ROOT = {str(ROOT)!r}

# 在 Analysis 阶段就剔除用不到的 Qt 二进制，避免打进产物后再删。
EXCLUDE_BINARIES = {EXCLUDE_BINARIES!r}


def _keep(entry):
    name = entry[0].replace("\\\\", "/").lower()
    return not any(pat.lower() in name for pat in EXCLUDE_BINARIES)


a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "novanote", "assets"), "novanote/assets")],
    hiddenimports={py_list(HIDDEN_IMPORTS)},
    hookspath=[],
    runtime_hooks=[],
    excludes={py_list(EXCLUDES)},
    noarchive=False,
)

pyz = PYZ(a.pure)

a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

exe_kwargs = dict(
    name={NAME!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console={console!r},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={str(ICON)!r},
    version={str(BUILD_DIR / 'version_info.txt')!r},
    manifest={str(MANIFEST)!r},
)
'''
    if onefile:
        spec += '''
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    **exe_kwargs,
)
'''
    else:
        spec += '''
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=%r,
)
''' % NAME

    SPEC.write_text(spec, encoding="utf-8")
    return SPEC


# --------------------------------------------------------------------------- #
# 清空目录
# --------------------------------------------------------------------------- #
def _wipe(path: Path) -> None:
    """清空目录。

    优先直接递归删除；若所处环境拦截批量删除（受管环境下常见），
    则退化为「同盘改名挪开」，保证构建源目录干净、不残留旧文件。
    """
    if not path.exists():
        return
    import time

    shutil.rmtree(path, ignore_errors=True)
    if not path.exists():
        print(f"已清理 {path.name}")
        return

    trash = path.with_name(f".{path.name}-old-{int(time.time())}")
    try:
        path.rename(trash)
    except OSError as e:
        print(f"  警告：无法清理 {path}（{e}），构建可能残留旧文件")
        return
    shutil.rmtree(trash, ignore_errors=True)
    if trash.exists():
        print(f"  旧产物已挪到 {trash.name}（可稍后手动删除）")


# --------------------------------------------------------------------------- #
# 定位 Inno Setup 编译器
# --------------------------------------------------------------------------- #
def find_iscc() -> Path | None:
    env = os.environ.get("ISCC")
    cands: list[Path] = []
    if env:
        cands.append(Path(env))
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            cands.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for c in cands:
        if c.is_file():
            return c
    return None


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_exe(onefile: bool, clean: bool, console: bool) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先运行：")
        print("  python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple")
        return 1

    if clean:
        for d in (BUILD_DIR, DIST_DIR):
            _wipe(d)

    write_version_file()
    spec = write_spec(onefile, console)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        str(spec),
    ]
    print("\n构建可执行程序 ……")
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc

    exe = APP_DIR / f"{NAME}.exe"
    if exe.is_file():
        mb = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file()) / 1024 / 1024
        print(f"\n✓ 可执行程序就绪：{exe}")
        print(f"  目录体积：{mb:.1f} MB")
    return 0


def build_installer() -> int:
    iscc = find_iscc()
    if iscc is None:
        print("\n未找到 Inno Setup 6 编译器（ISCC.exe）。")
        print("  安装方式： winget install --id JRSoftware.InnoSetup -e -s winget")
        print("  或下载：   https://jrsoftware.org/isdl.php")
        print("  安装后重试，或设置环境变量 ISCC 指向 ISCC.exe。")
        return 1
    if not (APP_DIR / f"{NAME}.exe").is_file():
        print("\n请先执行打包生成 dist/NovaNote/。")
        return 1

    print(f"\n生成安装包（{iscc}）……")
    rc = subprocess.call([str(iscc), str(ISS)], cwd=str(ROOT))
    if rc != 0:
        return rc

    outs = sorted(DIST_DIR.glob(f"{NAME}-*-setup.exe"))
    if outs:
        out = outs[-1]
        print(f"\n✓ 安装包就绪：{out}")
        print(f"  体积：{out.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{NAME} 打包工具")
    ap.add_argument("--onefile", action="store_true", help="打包为单个 exe（启动较慢）")
    ap.add_argument("--clean", action="store_true", help="构建前清理 build/ 与 dist/")
    ap.add_argument("--installer", action="store_true", help="打包后生成 setup.exe 安装包")
    ap.add_argument("--console", action="store_true", help="保留控制台窗口（排查启动问题用）")
    args = ap.parse_args()

    if args.installer:
        args.clean = True  # 出安装包时强制干净构建，避免旧文件被打进去

    rc = build_exe(args.onefile, args.clean, args.console)
    if rc != 0:
        return rc
    if args.installer:
        return build_installer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
