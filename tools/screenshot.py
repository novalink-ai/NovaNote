"""开发用：搭建演示工作空间、走查各视图并输出截图。

用法：
    python tools/screenshot.py [输出目录]

脚本同时充当一次完整的功能冒烟测试：任何视图构建失败都会直接抛出异常。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 把全局配置指向临时目录，避免演示脚本污染用户的真实设置
import novanote.config as _cfg  # noqa: E402

_CFG_DIR = Path(tempfile.gettempdir()) / "NovaNote-demo-cfg"
_CFG_DIR.mkdir(parents=True, exist_ok=True)
_cfg.CONFIG_PATH = _CFG_DIR / "config.json"

from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from novanote.config import Settings  # noqa: E402
from novanote.icons import app_icon  # noqa: E402
from novanote.services.assets import MediaService  # noqa: E402
from novanote.services.literature import LiteratureService  # noqa: E402
from novanote.services.notes import NoteService  # noqa: E402
from novanote.services.workspace import Workspace, WorkspaceRegistry  # noqa: E402
from novanote.theme import Fonts, build_qss, resolve_font  # noqa: E402
from novanote.ui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


# --------------------------------------------------------------------------- #
def make_demo_image(path: Path, w: int = 1200, h: int = 700) -> Path:
    """生成一张用于演示的示意图（渐变 + 波形，模拟 rPPG / 信号图）。"""
    img = QImage(w, h, QImage.Format_RGB32)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#1B2A38"))
    g.setColorAt(1.0, QColor("#2C4A5E"))
    p = QPainter(img)
    p.fillRect(0, 0, w, h, g)
    p.setRenderHint(QPainter.Antialiasing, True)

    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    for x in range(0, w, 40):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 40):
        p.drawLine(0, y, w, y)

    import math

    for idx, (color, amp, freq, off) in enumerate([
        (QColor("#E8A76B"), 90, 0.021, 0.0),
        (QColor("#6DA4C9"), 60, 0.037, 1.2),
        (QColor("#8FC9A0"), 34, 0.061, 2.4),
    ]):
        p.setPen(QPen(color, 2.4))
        prev = None
        for x in range(0, w, 2):
            y = h / 2 + off * 40 + amp * math.sin(freq * x) * math.sin(0.004 * x + idx)
            if prev:
                p.drawLine(prev[0], prev[1], x, int(y))
            prev = (x, int(y))

    p.setPen(QColor("#E7ECF2"))
    p.setFont(QFont("Microsoft YaHei UI", 20, QFont.Bold))
    p.drawText(40, 62, "HRV 时频分析 · 演示图")
    p.setPen(QColor(180, 200, 216))
    p.setFont(QFont("Microsoft YaHei UI", 11))
    p.drawText(40, 92, "RR 间期 / LF-HF 比 / 呼吸性窦性心律不齐（示意）")
    p.end()
    img.save(str(path), "PNG")
    return path


def seed(ws: Workspace) -> None:
    notes = NoteService(ws)
    lit = LiteratureService(ws)
    media = MediaService(ws)

    nbs = notes.notebooks()
    nb_idea = nbs[0].id
    nb_work = nbs[1].id
    nb_lit = nbs[2].id
    nb_todo = nbs[3].id

    # ---------- 文献 ----------
    refs = [
        {
            "entry_type": "article",
            "title": "BBRv3: A Model-Based Congestion Control for High-Bandwidth Networks",
            "authors": "Cardwell Neal and Cheng Yuchung and Hassas Yeganeh Soheil and Swett Ian",
            "year": "2023", "container": "IEEE/ACM Transactions on Networking",
            "volume": "31", "issue": "4", "pages": "1502-1517",
            "doi": "10.1109/TNET.2023.3254188",
            "abstract": "We present BBRv3, the third generation of the Bottleneck Bandwidth and "
                        "Round-trip propagation time congestion control algorithm. BBRv3 refines the "
                        "model-based approach with improved loss and ECN handling, better fairness on "
                        "shared bottlenecks, and a redesigned probe phase that reduces queue pressure.",
            "keywords": "congestion control; BBR; TCP; bandwidth estimation",
            "keywords_note": "核心参考",
        },
        {
            "entry_type": "inproceedings",
            "title": "Sparse Mixture-of-Experts Routing for Adaptive Network Traffic Classification",
            "authors": "Zhang Wei and Liu Yang and Chen Hao",
            "year": "2024", "container": "Proceedings of the IEEE International Conference on "
                                            "Computer Communications (INFOCOM)",
            "publisher": "IEEE", "pages": "1123-1132",
            "doi": "10.1109/INFOCOM.2024.10451234",
            "abstract": "This paper explores Mixture-of-Experts (MoE) architectures for network "
                        "traffic classification. A sparse top-k routing scheme with load balancing "
                        "loss substantially reduces inference cost while improving macro-F1 on "
                        "imbalanced traffic traces.",
            "keywords": "MoE; traffic classification; sparse routing; deep learning",
        },
        {
            "entry_type": "article",
            "title": "YOLOv11 with Kalman Filtering for Small Object Detection in Surveillance Video",
            "authors": "Wang Lin and Sun Qi and Zhou Ming and Xu Dan",
            "year": "2025", "container": "Pattern Recognition",
            "volume": "158", "pages": "110-124",
            "doi": "10.1016/j.patcog.2024.110124",
            "abstract": "We combine an improved YOLOv11 detector with a Kalman filter based tracker "
                        "to stabilize detections of small objects under motion blur and partial occlusion. "
                        "A bidirectional feature pyramid and a dynamic label assignment improve recall by "
                        "6.4 points on a surveillance benchmark.",
            "keywords": "object detection; YOLO; Kalman filter; multi-object tracking",
        },
        {
            "entry_type": "article",
            "title": "Remote Photoplethysmography for Heart Rate Variability: A Systematic Review",
            "authors": "Martinez Elena and Rossi Paolo and Nguyen Kim",
            "year": "2024", "container": "Biomedical Signal Processing and Control",
            "volume": "92", "pages": "106-119",
            "doi": "10.1016/j.bspc.2024.106119",
            "abstract": "Remote photoplethysmography (rPPG) enables contactless heart rate and HRV "
                        "estimation from facial video. We review 214 studies, categorizing motion "
                        "robustness, illumination normalization, and validation protocols, and propose "
                        "a minimum reporting standard for clinical translation.",
            "keywords": "rPPG; heart rate variability; contactless sensing",
        },
    ]
    created = []
    for r in refs:
        data = dict(r)
        data.pop("keywords_note", None)
        created.append(lit.create(data, tags=[t.strip() for t in r["keywords"].split(";")][:3]))
    lit.set_read_state(created[0].id, 2)
    lit.set_read_state(created[1].id, 1)
    lit.set_starred(created[2].id, True)
    lit.update(created[0].id, {"rating": 5})
    lit.update(created[2].id, {"rating": 4, "note": "改进了小目标检测，可与红外阵列方案对比。"
                                                    "注意其标签分配策略对低分辨率输入的影响需复现验证。"})

    # ---------- 图片附件 ----------
    # 提前导入，便于在正文里用 asset: 伪协议内联引用
    tmp_dir = Path(tempfile.mkdtemp(prefix="novanote-demo-"))
    img_path = make_demo_image(tmp_dir / "hrv_demo.png")
    img_info = media.import_file(img_path)
    img_rel = img_info["rel_path"]

    # ---------- 笔记 ----------
    body1 = (
        "<h2>本周研究要点</h2>"
        "<p>围绕<b>别墅电梯跌倒检测</b>的多模态融合方案，重新梳理了低精度红外阵列与 "
        "WiFi CSI 两路信号的特征对齐问题。</p>"
        "<h3>关键结论</h3>"
        "<ul><li>红外阵列（32×24）在夜间能稳定给出<b>人体热区质心</b>，但对细粒度姿态无能为力；</li>"
        "<li>WiFi CSI 的<span style=\"background-color:#F6E3B4\">多普勒频移</span>对跌落这类"
        "剧烈动作非常敏感，代价是受多径影响大；</li>"
        "<li>两路信号在时间轴上做 200 ms 窗口滑窗对齐后，联合建模的 F1 比单模态提升明显。</li></ul>"
        "<h3>下一步</h3>"
        "<ul><li>☑ 完成教师学生网络的特征蒸馏基线</li>"
        "<li>☐ 补充身份识别分支的损失权重搜索</li>"
        "<li>☐ 整理社区实测数据集标注规范</li></ul>"
        "<blockquote>待验证：身份识别与跌倒检测共用 encoder 时，是否会出现梯度冲突？"
        "考虑用 GradNorm 做动态加权。</blockquote>"
    )

    body2 = (
        "<h2>rPPG 信号处理流程</h2>"
        "<p>摄像头采集 → 人脸 ROI 定位 → 颜色通道分离（POS / CHROM）→ 带通滤波（0.7–4 Hz）"
        " → 峰值检测 → RR 间期序列 → HRV 时频分析。</p>"
        "<p>下图是当前滤波器参数下的一段示意输出：</p>"
        f'<p><img src="asset:{img_rel}" width="560"/></p>'
    )

    body3 = (
        "<h2>组会记录 · 2026-09-18</h2>"
        "<p><b>汇报人：</b>赵诺伯特　<b>参与：</b>INSS 课题组</p>"
        "<h3>讨论</h3>"
        "<ul><li>网站课程页参考 CS50 与 MIT OCW 的信息层级，重点是把「课程目标—先修—周次安排」讲清楚；</li>"
        "<li>实验室主页配色统一为海蓝，图标使用扁平线性风格；</li>"
        "<li>需要补充「网络工程创新实践」的实验环境说明。</li></ul>"
        "<pre>课程列表：\n  · 操作系统\n  · 计算机网络\n  · Python 程序设计\n"
        "  · 无线网络技术\n  · 网络工程创新实践</pre>"
        "<p>会议结论：先出信息架构图，再定视觉稿。</p>"
    )

    body4 = (
        "<h2>文献速览</h2>"
        "<p>把 MoE 的稀疏路由思想迁移到网络流量分类上，是一个成本与精度都能交代得过去的方案。"
        "关键在负载均衡 loss 的系数——太小会导致专家坍缩，太大又牺牲精度。</p>"
        "<table cellspacing=\"0\" cellpadding=\"6\" border=\"1\" width=\"100%\">"
        "<tr><th>方案</th><th>推理成本</th><th>Macro-F1</th></tr>"
        "<tr><td>Dense 基线</td><td>1.00×</td><td>0.842</td></tr>"
        "<tr><td>Top-2 MoE</td><td>0.41×</td><td>0.887</td></tr>"
        "<tr><td>Top-1 MoE</td><td>0.23×</td><td>0.871</td></tr></table>"
        "<p>结论：<b>Top-2</b> 是当前性价比最优点。</p>"
    )

    n1 = notes.create("多模态跌倒检测 · 本周研究要点", body1, nb_work,
                      tags=["跌倒检测", "多模态融合", "WiFi CSI"])
    n2 = notes.create("rPPG 信号处理流程", body2, nb_work, tags=["rPPG", "HRV"])
    n3 = notes.create("组会记录 · INSS 课题组网站", body3, nb_idea, tags=["实验室", "网站"])
    notes.create("文献速览 · MoE 稀疏路由", body4, nb_lit, tags=["MoE", "文献"])
    n5 = notes.create("待办 · 本周", (
        "<ul><li>☑ 提交高压断路器缺陷检测阶段报告</li>"
        "<li>☐ 复现 YOLOv11 + Kalman 滤波基线</li>"
        "<li>☐ 整理电梯故障预测的 IMU 数据标注</li>"
        "<li>☐ 给 HRV 软件补一版 pyqtgraph 实时曲线</li></ul>"),
        nb_todo, tags=["待办"])

    # 图片附件（正文已通过 asset: 伪协议内联，这里再挂一份到附件条）
    notes.add_asset(n2.id, img_info)
    for _a in notes.assets(n2.id):
        notes.refresh_kind(n2.id)

    # 文献关联
    notes.link_ref(n1.id, created[2].id)
    notes.link_ref(n1.id, created[0].id)
    notes.link_ref(n1.id, created[1].id)
    lit_notes = notes.create_note_for_ref(created[0], nb_lit)
    notes.link_ref(lit_notes.id, created[3].id)

    notes.set_starred(n1.id, True)
    notes.set_starred(lit_notes.id, True)
    starred_extra = next(n for n in notes.list() if n.title.startswith("文献速览"))
    notes.set_starred(starred_extra.id, True)

    # 回收站里放一篇
    notes.trash(n5.id)


# --------------------------------------------------------------------------- #
def grab(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    QApplication.processEvents()
    time.sleep(0.35)
    QApplication.processEvents()
    px = widget.grab()
    path = OUT / f"{name}.png"
    px.save(str(path), "PNG")
    print(f"  ✓ {path.relative_to(ROOT)}  ({px.width()}×{px.height()})")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("NovaNote")
    app.setWindowIcon(app_icon())

    ui_font = resolve_font(Fonts.ui, [Fonts.ui_fallback, "Segoe UI", "sans-serif"])
    f = QFont(ui_font)
    f.setPointSizeF(9.75)
    app.setFont(f)

    ws_root = Path(tempfile.gettempdir()) / "NovaNote-demo"
    if ws_root.exists():
        import shutil

        shutil.rmtree(ws_root, ignore_errors=True)
    ws = Workspace.create(ws_root, "演示工作空间")
    seed(ws)

    settings = Settings()
    settings.theme = "light"
    settings.editor_font = "Microsoft YaHei UI"
    registry = WorkspaceRegistry(settings)
    registry.settings.add_or_update_workspace(ws.to_ref())
    registry.settings.current_workspace = ws.id
    registry.current = ws

    app.setStyleSheet(build_qss("light"))
    win = MainWindow(settings, registry)
    win.resize(1500, 940)
    win.show()
    QApplication.processEvents()
    time.sleep(0.6)

    shots = []

    def step(name: str, fn) -> None:
        fn()
        QApplication.processEvents()
        time.sleep(0.5)
        grab(win, name)
        shots.append(name)

    # 1. 工作台概览
    step("01_welcome", lambda: win.rail.select("notes") or win.show_welcome())

    # 2. 笔记 + 编辑器
    def show_note():
        win.rail.select("notes")
        win.on_search("")
        notes = win.notes.list()
        target = next(n for n in notes if n.title.startswith("多模态跌倒"))
        win.load_note(target.id)

    step("02_note_editor", show_note)

    # 3. 图文笔记（rPPG）
    def show_media_note():
        target = next(n for n in win.notes.list() if n.title.startswith("rPPG"))
        win.load_note(target.id)

    step("03_note_with_image", show_media_note)

    # 4. 文献列表 + 详情
    def show_lit():
        win.rail.select("literature")
        refs = win.lit.list()
        target = next(r for r in refs if "YOLOv11" in r.title)
        win.load_reference(target.id)

    step("04_literature", show_lit)

    # 5. 设置对话框
    def show_settings():
        from novanote.ui.dialogs import SettingsDialog

        dlg = SettingsDialog(settings, ws, "light", win)
        dlg.show()
        QApplication.processEvents()
        time.sleep(0.5)
        grab(dlg, "05_settings")
        shots.append("05_settings")
        dlg.close()

    QApplication.processEvents()
    show_settings()

    # 6. 深色主题
    def show_dark():
        win.apply_theme("dark")
        win.rail.select("notes")
        win.on_search("")
        target = next(n for n in win.notes.list() if n.title.startswith("文献速览"))
        win.load_note(target.id)

    step("06_dark_theme", show_dark)

    # 7. 工作空间向导
    def show_setup():
        from novanote.ui.dialogs import WorkspaceSetupDialog

        dlg = WorkspaceSetupDialog("light", registry.recent(), mode="welcome", parent=win)
        dlg.show()
        QApplication.processEvents()
        time.sleep(0.5)
        grab(dlg, "07_workspace_setup")
        shots.append("07_workspace_setup")
        dlg.close()

    win.apply_theme("light")
    show_setup()

    print(f"\n完成，共 {len(shots)} 张截图 → {OUT}")
    sys.stdout.flush()

    # 收尾：先让 Qt 处理完挂起事件，再销毁窗口。
    # 若直接 sys.exit()，解释器关闭阶段销毁仍持有媒体后端的控件会触发
    # 底层崩溃（表现为进程被 SIGTERM）。这里显式清理后用 os._exit 退出。
    win.close()
    win.deleteLater()
    for _ in range(3):
        QApplication.processEvents()
    QApplication.quit()
    return 0


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_rc)
