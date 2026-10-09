"""性能基准：构造较大数据集，测量各关键路径耗时。

用法：
    python tools/bench.py            # 默认 2000 笔记 / 300 文献
    python tools/bench.py 5000 800
"""
from __future__ import annotations

import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import novanote.config as _cfg  # noqa: E402

_TMP_CFG = Path(tempfile.mkdtemp(prefix="novanote-bench-cfg-"))
_cfg.CONFIG_PATH = _TMP_CFG / "config.json"
_cfg.LOG_PATH = _TMP_CFG / "novanote.log"

from novanote.services.literature import LiteratureService, RefFilter  # noqa: E402
from novanote.services.notes import NoteFilter, NoteService  # noqa: E402
from novanote.services.notes import count_words, html_to_text  # noqa: E402
from novanote.services.workspace import Workspace  # noqa: E402

WORDS = ["滤波", "多模态", "跌倒检测", "红外阵列", "WiFi CSI", "教师学生网络",
         "MoE", "稀疏路由", "HRV", "rPPG", "Kalman", "YOLOv11", "语义分割",
         "知识蒸馏", "注意力机制", "时间序列", "特征对齐", "数据集", "消融实验", "基线"]
TOPICS = ["别墅电梯", "高压断路器", "精神分裂症早筛", "INSS 网站", "BBRv3",
          "电梯故障预测", "课题申报", "组会记录", "文献综述", "实验记录"]


def make_body(i: int) -> str:
    rnd = random.Random(i)
    ws = rnd.sample(WORDS, 6)
    return (
        f"<h2>{rnd.choice(TOPICS)} · 第 {i} 篇</h2>"
        f"<p>围绕 <b>{ws[0]}</b> 与 <b>{ws[1]}</b> 展开，重点关注 {ws[2]} 的建模方式。</p>"
        f"<ul><li>{ws[3]} 需要与 {ws[4]} 做时间轴对齐；</li>"
        f"<li>{ws[5]} 在多径条件下表现不稳定。</li></ul>"
        f"<p>{'这是一段用于拉开正文长度的中文说明文字，' * 4}</p>"
    )


def build(ws_root: Path, n_notes: int, n_refs: int):
    ws = Workspace.create(ws_root, "基准工作空间")
    notes = NoteService(ws)
    lit = LiteratureService(ws)

    nbs = [n.id for n in notes.notebooks()]
    tags = [f"标签{k:02d}" for k in range(30)]

    t0 = time.perf_counter()
    for i in range(n_notes):
        notes.create(
            title=f"{random.Random(i).choice(TOPICS)} 笔记 {i:05d}",
            body_html=make_body(i),
            notebook_id=nbs[i % len(nbs)],
            tags=random.Random(i).sample(tags, 3),
        )
    t_notes = time.perf_counter() - t0

    t0 = time.perf_counter()
    for i in range(n_refs):
        rnd = random.Random(1000 + i)
        lit.create({
            "title": f"{rnd.choice(TOPICS)} related work {i:04d}",
            "authors": " and ".join(f"Author{rnd.randrange(300)} Name{rnd.randrange(300)}"
                                    for _ in range(rnd.randint(1, 5))),
            "year": str(rnd.randint(2010, 2026)),
            "container": rnd.choice(["IEEE Transactions on Networking", "Pattern Recognition",
                                     "INFOCOM", "Biomedical Signal Processing", "Sensors"]),
            "abstract": "Abstract text about " + " ".join(rnd.sample(WORDS, 5)),
            "keywords": "; ".join(rnd.sample(WORDS, 3)),
            "read_state": rnd.randint(0, 2),
        }, tags=random.Random(i).sample(tags, 2))
    t_refs = time.perf_counter() - t0

    print(f"  构建：{n_notes} 笔记 {t_notes:.2f}s ／ {n_refs} 文献 {t_refs:.2f}s")
    return ws, notes, lit


def bench(label: str, fn, repeat: int = 5) -> float:
    times = []
    result_repr = ""
    for _ in range(repeat):
        t0 = time.perf_counter()
        r = fn()
        times.append((time.perf_counter() - t0) * 1000)
        if isinstance(r, (list, tuple)):
            result_repr = f"{len(r)} 项"
    med = statistics.median(times)
    print(f"  {label:<38} {med:8.1f} ms   (min {min(times):.1f} / max {max(times):.1f})  {result_repr}")
    return med


def main() -> int:
    n_notes = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    n_refs = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    ws_root = Path(tempfile.gettempdir()) / "NovaNote-bench"
    if ws_root.exists():
        shutil.rmtree(ws_root, ignore_errors=True)

    print(f"== NovaNote 性能基准（{n_notes} 笔记 / {n_refs} 文献）==")
    ws, notes, lit = build(ws_root, n_notes, n_refs)

    db_size = ws.db.path.stat().st_size / 1024 / 1024
    print(f"  数据库体积：{db_size:.1f} MB\n")

    print("-- 笔记列表 / 检索 --")
    bench("notes.list() 全量", lambda: notes.list())
    bench("notes.list(notebook_id=1)", lambda: notes.list(NoteFilter(notebook_id=1)))
    bench("notes.list(starred)", lambda: notes.list(NoteFilter(starred=True)))
    bench("notes.list(query='滤波')", lambda: notes.list(NoteFilter(query="滤波")))
    bench("notes.list(tag='标签01')", lambda: notes.list(NoteFilter(tag="标签01")))
    bench("notes.search(limit=200)", lambda: notes.search("多模态", limit=200))
    bench("notes.get(1)", lambda: notes.get(1), repeat=20)
    bench("notes.timeline(60)", lambda: notes.timeline(60))

    print("\n-- 侧栏 / 统计 --")
    bench("notes.notebooks()", lambda: notes.notebooks())
    bench("notes.tags()", lambda: notes.tags())
    bench("db.stats()", lambda: ws.db.stats())

    print("\n-- 文献 --")
    bench("lit.list() 全量", lambda: lit.list())
    bench("lit.list(limit=100)", lambda: lit.list(RefFilter(limit=100)))
    bench("lit.list(query='routing')", lambda: lit.list(RefFilter(query="routing")))
    bench("lit.list(read_state=2)", lambda: lit.list(RefFilter(read_state=2)))
    bench("lit.years()", lambda: lit.years())
    bench("lit.authors_top()", lambda: lit.authors_top())
    bench("lit.venues_top()", lambda: lit.venues_top())

    print("\n-- 编辑保存热路径 --")
    big_html = make_body(1) * 12
    bench("html_to_text + count_words", lambda: count_words(html_to_text(big_html)), repeat=30)

    print("\n-- 原子操作 --")
    bench("notes.create() 单篇", lambda: notes.create(title="t", body_html=make_body(9)),
          repeat=20)
    bench("notes.update() 正文", lambda: notes.update(1, body_html=make_body(7)), repeat=20)

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
