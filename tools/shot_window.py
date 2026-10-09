"""抓取正在运行的 NovaNote 窗口截图。

与 tools/screenshot.py 的区别：
  - screenshot.py 在进程内搭建演示工作空间并逐视图截图（离线、可重现）；
  - 本脚本抓的是**你此刻正在用的那个窗口**（在线、真实状态）。

用法：
    python tools/shot_window.py                    # 存到 docs/_live.png
    python tools/shot_window.py out.png            # 指定输出
    python tools/shot_window.py out.png --title X  # 匹配其它窗口标题

注意（Windows 高分屏）：
    PrintWindow 工作在实际像素坐标系下。若只按逻辑尺寸建位图，在 200% 缩放的
    屏幕上会只截到窗口左上角 1/4。因此这里先 SetProcessDPIAware() 再取
    GetWindowRect，尺寸即为物理像素。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import pathlib
import sys

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


def find_window(substr: str) -> int:
    """按标题子串查找第一个可见顶层窗口。"""
    hits: list[tuple[int, str]] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if substr.lower() in buf.value.lower():
            hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(proc(cb), 0)
    if not hits:
        raise SystemExit(f"未找到标题包含 {substr!r} 的可见窗口")
    hwnd, title = hits[0]
    print(f"命中窗口：{title!r}  HWND={hwnd}")
    return hwnd


def grab(hwnd: int, out: pathlib.Path) -> None:
    user32.SetProcessDPIAware()
    r = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    width, height = r.right - r.left, r.bottom - r.top

    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem, bmp)
    try:
        if not user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT):
            raise SystemExit("PrintWindow 失败（窗口可能已关闭）")
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32,
                              0, width * height * 4, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(width * height * 4)
        rows = gdi32.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bi), 0)
        if rows != height:
            raise SystemExit(f"GetDIBits 只取到 {rows}/{height} 行")
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)

    # 交给 Qt 编码：Windows 的 32 位 DIB 是 BGRA，对应 Qt 的 Format_ARGB32
    from PySide6.QtGui import QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(buf.raw, width, height, width * 4, QImage.Format_ARGB32)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(out)):
        raise SystemExit(f"写入 {out} 失败")
    print(f"已保存 {out}  ({width}×{height} 物理像素)")
    del app


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path("docs/_live.png")
    title = "NovaNote"
    if "--title" in argv:
        title = argv[argv.index("--title") + 1]
    grab(find_window(title), out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
