"""界面性能基准：列表渲染 / 滚动 / 主题切换。

用来守住两个容易退化的性能红线：
  1. 列表渲染耗时不能随数据量增长 —— 卡片控件必须按可视区惰性实例化；
  2. 单张卡片构造成本要保持在亚毫秒级 —— 尤其别在卡片里对"还没有父控件"
     的 QLabel 调 setVisible(True)（会创建原生顶层窗口，单卡多出约 40ms）。

用法：
    python tools/bench_ui.py                     # 用默认演示数据
    python tools/bench_ui.py --notes 5000        # 指定规模（会现造数据）
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import novanote.config as _cfg  # noqa: E402

_cfg.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="novanote-benchui-cfg-")) / "config.json"
_cfg.LOG_PATH = _cfg.CONFIG_PATH.parent / "novanote.log"

from PySide6.QtWidgets import QApplication  # noqa: E402

from novanote.services.literature import LiteratureService  # noqa: E402
from novanote.services.notes import NoteService  # noqa: E402
from novanote.services.workspace import Workspace  # noqa: E402
from novanote.theme import build_qss  # noqa: E402
from novanote.ui.literature import RefListPane  # noqa: E402
from novanote.ui.note_list import NoteCard, NoteListPane  # noqa: E402

VIEWPORT = (300, 720)


def log(msg: str) -> None:
    print(msg, flush=True)


def timeit(label: str, fn, repeat: int = 3) -> float:
    """计时并把 processEvents 排除在外（否则测到的是"绘制"而非"构造"）。"""
    times = []
    for _ in range(repeat):
        app.processEvents()
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    app.processEvents()
    best = min(times)
    log(f"   {label:<40} {best:8.1f} ms")
    return best


app = QApplication.instance() or QApplication([])
app.setStyleSheet(build_qss("light"))

ws_root = Path(tempfile.gettempdir()) / "NovaNote-bench"
if not (ws_root / "novanote.db").exists():
    log(f"演示工作空间不存在：{ws_root}")
    log("请先运行  python tools/bench.py 2000 300  造一份基准数据。")
    sys.exit(1)

ws = Workspace.open(ws_root)
svc = NoteService(ws)
lit = LiteratureService(ws)
all_notes = svc.list()
all_refs = lit.list()
log(f"== 界面性能基准（{len(all_notes)} 篇笔记 / {len(all_refs)} 篇文献）==\n")

log("-- 列表渲染：耗时应与数据量无关 --")
for n in (100, 300, 600, 1000, 2000):
    if n > len(all_notes):
        continue
    subset = all_notes[:n]
    pane = NoteListPane("light")
    pane.resize(*VIEWPORT)
    pane.show()
    timeit(f"set_notes({n:>4} 条)", lambda p=pane, a=subset: p.set_notes(a))
    log(f"        └ 子控件 {len(pane.findChildren(object)):>4}"
        f" / 卡片 {pane.list.live_card_count()}")

    t0 = time.perf_counter()
    pane.list.verticalScrollBar().setValue(720)
    app.processEvents()
    log(f"        └ 滚动一屏 {(time.perf_counter() - t0) * 1000:7.1f} ms")
    pane.hide()
    pane.deleteLater()

log("\n-- 单张卡片构造成本（应为亚毫秒）--")
sample = all_notes[0]
timeit("NoteCard()", lambda: NoteCard(sample, "light"), repeat=30)

log("\n-- 文献列表 --")
rpane = RefListPane("light")
rpane.resize(*VIEWPORT)
rpane.show()
timeit(f"set_refs({len(all_refs)} 条)", lambda: rpane.set_refs(all_refs))
log(f"        └ 子控件 {len(rpane.findChildren(object)):>4}"
    f" / 卡片 {rpane.list.live_card_count()}")

log("\n-- 主题切换（全量重建 QSS + 重新着色可视卡片）--")
timeit("apply_theme(dark) → refresh", lambda: (
    app.setStyleSheet(build_qss("dark")), rpane.refresh("dark")), repeat=3)

log("\n完成。")
