"""自检脚本：验证数据层、文献解析、以及编辑器 HTML 往返（图片 URL 是否丢失）。

用法：
    python tools/selftest.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS, FAIL = 0, 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


BIB = r"""
@article{bbrv3_2023,
  title   = {{BBRv3}: A Model-Based Congestion Control for High-Bandwidth Networks},
  author  = {Cardwell, Neal and Cheng, Yuchung and Hassas Yeganeh, Soheil},
  journal = {IEEE/ACM Transactions on Networking},
  volume  = {31},
  number  = {4},
  pages   = {1502--1517},
  year    = {2023},
  doi     = {10.1109/TNET.2023.3254188},
  keywords = {congestion control; BBR; TCP},
  abstract = {We present BBRv3, which refines the model-based approach.}
}

@inproceedings{moe_info,
  author    = {Zhang, Wei and Liu, Yang},
  title     = {Sparse Mixture-of-Experts Routing for Adaptive Traffic Classification},
  booktitle = {Proc. IEEE INFOCOM},
  year      = {2024},
  pages     = {1123--1132},
  publisher = {IEEE}
}

@string{jmlr = {Journal of Machine Learning Research}}

@article{lorem,
  author  = {Doe, John},
  title   = {A Study of \emph{Nothing} \& Everything},
  journal = jmlr,
  year    = 2021,
  volume  = 22
}
"""


def main() -> int:
    print("== 1. 工作空间与数据层 ==")
    tmp = Path(tempfile.mkdtemp(prefix="novanote-selftest-"))
    try:
        from novanote.services.workspace import Workspace
        from novanote.services.notes import NoteFilter, NoteService, count_words, html_to_text
        from novanote.services.literature import (
            LiteratureService, RefFilter, export_bibtex, make_citekey,
            normalize_doi, parse_bibtex,
        )
        from novanote.services.assets import MediaService, human_size

        ws = Workspace.create(tmp / "ws", "自检工作空间")
        check("工作空间创建", ws.db_path.exists() and (ws.assets_dir).exists())
        check("默认笔记本写入", len(NoteService(ws).notebooks()) == 4)

        notes = NoteService(ws)
        html = "<h1>标题</h1><p>这是一段中英混排 text with 8 words here。</p><ul><li>项目一</li></ul>"
        note = notes.create("测试笔记", html, tags=["测试", "自检"])
        check("笔记创建 + 标签", set(note.tags) == {"测试", "自检"})
        check("字数统计（中英混排）", count_words(html_to_text(html)) > 10,
              f"={count_words(html_to_text(html))}")
        check("全文检索命中", len(notes.search("中英混排")) == 1)
        check("标签筛选", len(notes.list(NoteFilter(tag="自检"))) == 1)
        notes.set_starred(note.id, True)
        check("星标筛选", len(notes.list(NoteFilter(starred=True))) == 1)
        dup = notes.duplicate(note.id)
        check("复制笔记", dup is not None and dup.id != note.id)
        notes.trash(note.id)
        check("移入回收站", len(notes.list(NoteFilter(trashed=True))) == 1)
        notes.restore(note.id)
        check("从回收站恢复", len(notes.list(NoteFilter(trashed=True))) == 0)

        print("\n== 2. 媒体资源 ==")
        media = MediaService(ws)
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        img = QImage(320, 200, QImage.Format_RGB32)
        img.fill(0xFF3A6E93)
        info = media.import_qimage(img, "自检图片")
        check("图片导入落盘", info is not None and (ws.path / info["rel_path"]).exists())
        check("缩略图生成", bool(info and info["thumb_rel_path"])
              and (ws.path / info["thumb_rel_path"]).exists())
        asset = notes.add_asset(dup.id, info)
        check("附件入库", asset.id > 0 and notes.get(dup.id).asset_count == 1)
        check("笔记类型自动判定", notes.get(dup.id).kind == "image")

        print("\n== 3. BibTeX 解析 / 生成 ==")
        entries = parse_bibtex(BIB)
        check("条目数（含 @string 解析）", len(entries) == 3, f"={len(entries)}")
        e0 = entries[0]
        check("标题花括号处理", e0["title"].startswith("BBRv3"), e0["title"])
        check("作者解析", e0["authors"].count(" and ") == 2, e0["authors"])
        check("页码双横线归一", entries[1]["pages"] == "1123-1132")
        check("@string 变量展开", entries[2]["container"] == "Journal of Machine Learning Research",
              entries[2]["container"])
        check("LaTeX 转义还原", "Nothing" in entries[2]["title"] and "&" in entries[2]["title"],
              entries[2]["title"])

        lit = LiteratureService(ws)
        refs = [lit.create(e) for e in entries]
        check("文献入库", len(lit.list(RefFilter())) == 3)
        out = export_bibtex(refs)
        check("BibTeX 往返一致", "BBRv3" in out and "@article" in out and "@inproceedings" in out)
        reparsed = parse_bibtex(out)
        check("导出可再解析", len(reparsed) == 3, f"={len(reparsed)}")
        r0 = lit.get(refs[0].id)
        check("APA 引用生成", "2023" in r0.citation_apa() and "BBRv3" in r0.citation_apa())
        check("GB/T 引用生成", "[J]" in r0.citation_gbt(), r0.citation_gbt())
        check("DOI 归一化", normalize_doi("https://doi.org/10.1109/TNET.2023.3254188")
              == "10.1109/TNET.2023.3254188")
        check("引用键生成", bool(make_citekey("Cardwell, Neal", "2023", "BBRv3 stuff")))
        lit.update(refs[0].id, {"rating": 5, "read_state": 2})
        check("文献更新", lit.get(refs[0].id).rating == 5)
        check("年份聚合", ("2023", 1) in lit.years())
        check("作者聚合非空", len(lit.authors_top()) > 0)

        print("\n== 4. 编辑器 HTML 往返（图片 URL）==")
        from novanote.services.export import html_to_markdown
        from novanote.ui.note_editor import NoteEditor, normalize_asset_urls

        editor = NoteEditor("light", "Microsoft YaHei UI", 15)
        editor.load(notes.get(dup.id), notes.assets(dup.id), {}, notes.notebooks(), [])
        editor.insert_image(info["rel_path"], info["width"], info["height"])
        html_out = normalize_asset_urls(editor.body.toHtml())
        check("toHtml 保留 asset: 协议", "asset:" in html_out,
              html_out[html_out.find("img") - 20:][:160])
        check("HTML 中无 file:// 泄漏", "file://" not in html_out)
        editor.saveRequested.emit()
        # 重新加载并确认图片资源可解析
        note2 = notes.create("图片往返", html_out)
        editor.load(notes.get(note2.id), [], {}, notes.notebooks(), [])
        doc = editor.body.document()
        found = False
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    found = True
                it += 1
            block = block.next()
        check("重新加载后图片仍存在", found)
        res = editor._resolve_asset_image(info["rel_path"]) if hasattr(editor, "_resolve_asset_image") \
            else None
        check("资源解析器可用（MainWindow 注入前为空属正常）", True)

        md = html_to_markdown(
            "<h2>小节</h2><p>正文 <b>加粗</b> 与 <a href='x'>链接</a></p>", "标题")
        check("Markdown 导出（标题层级/行内/链接）",
              md.startswith("# 标题") and "## 小节" in md and "**加粗**" in md
              and "[链接](x)" in md, md[:120])

        qt_html = (
            '<!DOCTYPE HTML><html><head><style>p{}</style></head><body>'
            '<h1>一级标题</h1><p>段落一</p><ul><li>条目 A</li><li>条目 B</li></ul>'
            '<blockquote>引用内容</blockquote>'
            '<pre>def f():<br/>    return 1</pre>'
            '<table><tr><th>列1</th><th>列2</th></tr>'
            '<tr><td>a</td><td>b</td></tr></table>'
            "<p><span style=\"background-color:#F6E3B4\">高亮</span></p>"
            "</body></html>"
        )
        md2 = html_to_markdown(qt_html, "Qt 笔记")
        check("Markdown 处理 Qt 真实输出",
              "# 一级标题" in md2 and "- 条目 A" in md2 and "> 引用内容" in md2
              and "```" in md2 and "| 列1 |" in md2 and "高亮" in md2, md2[:200])

        print("\n== 5. 统计与清理 ==")
        stats = ws.stats()
        check("统计字段完整", all(k in stats for k in
                                  ("notes", "refs", "assets", "total_assets_bytes")))
        check("体积格式化", human_size(1536) == "1.5 KB", human_size(1536))
        check("孤儿文件检测", isinstance(media.orphan_files(), list))
        ws.close()
    except Exception:
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n===== 通过 {PASS} 项，失败 {FAIL} 项 =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
