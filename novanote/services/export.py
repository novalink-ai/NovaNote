"""导出：Markdown / HTML / PDF。"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

from ..theme import editor_stylesheet, tokens


def _inline_md(s: str) -> str:
    s = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", s, flags=re.S | re.I)
    s = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", s, flags=re.S | re.I)
    s = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", s, flags=re.S | re.I)
    s = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", s, flags=re.S | re.I)
    s = re.sub(r"<u[^>]*>(.*?)</u>", r"<u>\1</u>", s, flags=re.S | re.I)
    s = re.sub(r"<s[^>]*>(.*?)</s>", r"~~\1~~", s, flags=re.S | re.I)
    s = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", s, flags=re.S | re.I)
    s = re.sub(r"""<a[^>]*href=["']([^"']*)["'][^>]*>(.*?)</a>""", r"[\2](\1)", s, flags=re.S | re.I)
    s = re.sub(r"""<img[^>]*src=["']([^"']*)["'][^>]*/?>""", r"![](\1)", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).strip()


def _prefix_lines(text: str, prefix: str) -> str:
    return "\n".join(prefix + ln if ln.strip() else prefix.rstrip()
                     for ln in text.splitlines())


def _table_to_md(match: re.Match) -> str:
    inner = match.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, flags=re.S | re.I)
    if not rows:
        return "\n"
    out: list[str] = []
    for ri, row in enumerate(rows):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I)
        cells = [re.sub(r"\s+", " ", _inline_md(c)) or " " for c in cells]
        if not cells:
            continue
        out.append("| " + " | ".join(cells) + " |")
        if ri == 0:
            out.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n" + "\n".join(out) + "\n\n"


def html_to_markdown(body_html: str, title: str = "") -> str:
    """把 QTextEdit 产出的 HTML 转成 Markdown（覆盖常见标记）。"""
    if not body_html:
        return f"# {title}\n" if title else ""
    text = body_html
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S | re.I)

    # 代码块优先，避免内部标签被当作行内标记
    def pre_repl(m: re.Match) -> str:
        inner = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        return "\n```\n" + inner.strip("\n") + "\n```\n\n"

    text = re.sub(r"<pre[^>]*>(.*?)</pre>", pre_repl, text, flags=re.S | re.I)

    # 表格
    text = re.sub(r"<table[^>]*>(.*?)</table>", _table_to_md, text, flags=re.S | re.I)

    # 标题
    for lvl in range(1, 7):
        text = re.sub(
            rf"<h{lvl}[^>]*>(.*?)</h{lvl}>",
            lambda m, l=lvl: "\n" + "#" * l + " " + _inline_md(m.group(1)) + "\n\n",
            text, flags=re.S | re.I,
        )

    # 引用块
    text = re.sub(
        r"<blockquote[^>]*>(.*?)</blockquote>",
        lambda m: "\n" + _prefix_lines(_inline_md(m.group(1)), "> ") + "\n\n",
        text, flags=re.S | re.I,
    )

    # 列表项
    text = re.sub(r"<li[^>]*>(.*?)</li>",
                  lambda m: "\n- " + _inline_md(m.group(1)), text, flags=re.S | re.I)
    text = re.sub(r"</?(ul|ol)[^>]*>", "\n", text, flags=re.I)

    # 段落
    text = re.sub(r"<p[^>]*>(.*?)</p>",
                  lambda m: "\n" + _inline_md(m.group(1)) + "\n\n", text, flags=re.S | re.I)
    text = re.sub(r"<div[^>]*>(.*?)</div>",
                  lambda m: "\n" + _inline_md(m.group(1)) + "\n", text, flags=re.S | re.I)

    # 其它块级
    text = re.sub(r"<hr\s*/?>", "\n---\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(body|html|head|meta|title)[^>]*>", "", text, flags=re.I)

    # 收尾：行内标记 + 去标签
    text = _inline_md(text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    header = f"# {title}\n\n" if title else ""
    return header + md + "\n"


def note_to_html_document(title: str, body_html: str, meta: str = "",
                          theme: str = "light", font: str = "Sitka Text",
                          size: int = 15) -> str:
    t = tokens(theme)
    css = editor_stylesheet(theme, font, size)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{_html.escape(title)}</title>
<style>
  html, body {{ background: {t['bg_app']}; }}
  body {{ max-width: 760px; margin: 0 auto; padding: 48px 40px 80px 40px; }}
  .doc-title {{ font-size: 30px; font-weight: 700; margin: 0 0 6px 0; color: {t['text']}; }}
  .doc-meta {{ font-size: 12px; color: {t['text_muted']}; margin-bottom: 26px;
               padding-bottom: 18px; border-bottom: 1px solid {t['border']};
               font-family: "Microsoft YaHei UI", sans-serif; }}
  .doc-body {{ font-family: "{font}"; }}
  {css}
</style>
</head>
<body>
  <div class="doc-title">{_html.escape(title)}</div>
  <div class="doc-meta">{_html.escape(meta)}</div>
  <div class="doc-body">{body_html}</div>
</body>
</html>
"""


def export_note_pdf(path: str | Path, title: str, body_html: str, meta: str,
                    theme: str = "light", font: str = "Sitka Text", size: int = 12) -> bool:
    """使用 Qt 打印栈导出 PDF。"""
    try:
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter
    except Exception:
        return False

    t = tokens(theme)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(path))
    _set_margins(printer, 18)
    doc = QTextDocument()
    doc.setDefaultStyleSheet(editor_stylesheet(theme, font, size))
    doc.setHtml(
        f'<div style="font-family:\'{font}\';font-size:{size}pt;color:{t["text"]}">'
        f'<div style="font-size:{int(size * 1.9)}pt;font-weight:700;margin-bottom:4px">'
        f"{_html.escape(title)}</div>"
        f'<div style="font-size:{max(8, size - 2)}pt;color:{t["text_muted"]};'
        f'margin-bottom:14px">{_html.escape(meta)}</div>'
        f"<hr/>{body_html}</div>"
    )
    doc.print_(printer)
    return True


def _set_margins(printer, mm: float) -> None:
    try:
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout

        layout = printer.pageLayout()
        layout.setUnits(QPageLayout.Millimeter)
        layout.setMargins(QMarginsF(mm, mm, mm, mm))
        printer.setPageLayout(layout)
    except Exception:
        pass
