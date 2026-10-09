"""扁平化线性图标系统。

全部图标以 24×24 SVG 路径定义，运行时按主题颜色渲染为 QIcon，
因此同一套图标可以在明/暗主题与不同强调色下复用，无需多套资源。
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# --------------------------------------------------------------------------- #
# 图标路径表（stroke 风格，{c} 为颜色占位符）
# --------------------------------------------------------------------------- #
_S = {
    # —— 导航 ——
    "note": '<path d="M6.8 3.2h6.7L19.2 9v11.3a1.5 1.5 0 0 1-1.5 1.5H6.8a1.5 1.5 0 0 1-1.5-1.5V4.7a1.5 1.5 0 0 1 1.5-1.5Z"/>'
            '<path d="M13.4 3.2v6h5.8"/><path d="M8.6 13.4h6.4M8.6 16.8h4.2"/>',
    "notes": '<path d="M9 4.4h5.3L18.5 9v9.8a1.2 1.2 0 0 1-1.2 1.2H9a1.2 1.2 0 0 1-1.2-1.2V5.6A1.2 1.2 0 0 1 9 4.4Z"/>'
             '<path d="M14.3 4.4V9h4.2"/><path d="M6.2 7.6H4.9a1.2 1.2 0 0 0-1.2 1.2v9.6a1.2 1.2 0 0 0 1.2 1.2h7"/>',
    "book": '<path d="M12 6.6C10.4 5.2 7.9 4.4 5.4 4.4c-.7 0-1.3.6-1.3 1.3v10.9c0 .7.6 1.3 1.3 1.3 2.5 0 5 .8 6.6 2.2"/>'
            '<path d="M12 6.6c1.6-1.4 4.1-2.2 6.6-2.2.7 0 1.3.6 1.3 1.3v10.9c0 .7-.6 1.3-1.3 1.3-2.5 0-5 .8-6.6 2.2"/>'
            '<path d="M12 6.6V22"/>',
    "star": '<path d="M12 3.6l2.65 5.55 6.05.85-4.4 4.2 1.1 6.05L12 17.4l-5.4 2.85 1.1-6.05-4.4-4.2 6.05-.85z"/>',
    "trash": '<path d="M4.4 7h15.2"/><path d="M9.6 7V4.9h4.8V7"/>'
             '<path d="M6.6 7l.85 12.1a1.5 1.5 0 0 0 1.5 1.4h6.1a1.5 1.5 0 0 0 1.5-1.4L17.4 7"/>'
             '<path d="M10.6 11v6M13.4 11v6"/>',
    "tag": '<path d="M4.2 11.5V5.2A1 1 0 0 1 5.2 4.2h6.3a1 1 0 0 1 .7.3l7.6 7.6a1 1 0 0 1 0 1.4l-6.3 6.3a1 1 0 0 1-1.4 0L4.5 12.2a1 1 0 0 1-.3-.7Z"/>'
           '<path d="M8.4 8.4h.02"/>',
    "folder": '<path d="M4 7.6A1.6 1.6 0 0 1 5.6 6h3.8a1.6 1.6 0 0 1 1.2.6l1.2 1.4h6.6A1.6 1.6 0 0 1 20 9.6V18a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 18V7.6Z"/>',
    "layers": '<path d="M12 3.4l8.6 4.3-8.6 4.3-8.6-4.3z"/><path d="M3.4 12.2l8.6 4.3 8.6-4.3"/><path d="M3.4 16.5l8.6 4.3 8.6-4.3"/>',
    "clock": '<path d="M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6Z"/><path d="M12 8v4.3l2.9 1.8"/>',
    "settings": '<path d="M12 15.1a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2Z"/>'
                '<path d="M19.3 14.4a1.5 1.5 0 0 0 .3 1.65l.06.06a1.8 1.8 0 1 1-2.55 2.55l-.06-.06a1.5 1.5 0 0 0-1.65-.3 1.5 1.5 0 0 0-.9 1.37V20a1.8 1.8 0 1 1-3.6 0v-.1a1.5 1.5 0 0 0-.98-1.37 1.5 1.5 0 0 0-1.65.3l-.06.06A1.8 1.8 0 1 1 5.66 16.3l.06-.06a1.5 1.5 0 0 0 .3-1.65 1.5 1.5 0 0 0-1.37-.9H4.4a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.37-.98 1.5 1.5 0 0 0-.3-1.65l-.06-.06A1.8 1.8 0 1 1 8.06 4.85l.06.06a1.5 1.5 0 0 0 1.65.3H9.9a1.5 1.5 0 0 0 .9-1.37V3.7a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 .9 1.37 1.5 1.5 0 0 0 1.65-.3l.06-.06a1.8 1.8 0 1 1 2.55 2.55l-.06.06a1.5 1.5 0 0 0-.3 1.65v.05a1.5 1.5 0 0 0 1.37.9h.1a1.8 1.8 0 1 1 0 3.6h-.1a1.5 1.5 0 0 0-1.37.9Z"/>',
    "search": '<path d="M10.8 4.2a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2Z"/><path d="M15.6 15.6L20 20"/>',
    "spark": '<path d="M12 2.6c.85 5.1 2.55 6.8 7.65 7.65-5.1.85-6.8 2.55-7.65 7.65-.85-5.1-2.55-6.8-7.65-7.65C9.45 9.4 11.15 7.7 12 2.6Z"/>',
    "plus": '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
    "check": '<path d="M5.2 12.6l4.6 4.6L18.8 7"/>',

    # —— 媒体 ——
    "image": '<path d="M4.4 6.6A1.6 1.6 0 0 1 6 5h12a1.6 1.6 0 0 1 1.6 1.6v10.8A1.6 1.6 0 0 1 18 19H6a1.6 1.6 0 0 1-1.6-1.6z"/>'
             '<path d="M4.9 16.4l4.1-4.3a1.5 1.5 0 0 1 2.1 0l4.5 4.6"/>'
             '<path d="M15.2 13.6l1.5-1.5a1.5 1.5 0 0 1 2.1 0l1.3 1.3"/>'
             '<path d="M9.1 9.7a1.1 1.1 0 1 0 0-2.2 1.1 1.1 0 0 0 0 2.2Z"/>',
    "video": '<path d="M4.4 7.6A1.6 1.6 0 0 1 6 6h7.2a1.6 1.6 0 0 1 1.6 1.6v8.8A1.6 1.6 0 0 1 13.2 18H6a1.6 1.6 0 0 1-1.6-1.6z"/>'
             '<path d="M14.8 10.6l4.2-2.6a.7.7 0 0 1 1.1.6v6.8a.7.7 0 0 1-1.1.6l-4.2-2.6"/>',
    "play": '<path d="M8.4 5.8v12.4a.6.6 0 0 0 .92.5l9.7-6.2a.6.6 0 0 0 0-1L9.32 5.3a.6.6 0 0 0-.92.5Z"/>',
    "pause": '<path d="M9 5.5v13M15 5.5v13"/>',
    "volume": '<path d="M11.4 5.4L6.9 9H4.3v6h2.6l4.5 3.6z"/><path d="M15.4 9.4a3.6 3.6 0 0 1 0 5.2"/>'
              '<path d="M18 7a7 7 0 0 1 0 10"/>',
    "paperclip": '<path d="M15.2 5.6l-7.5 7.5a3.1 3.1 0 1 0 4.4 4.4l7.5-7.5a5.1 5.1 0 0 0-7.2-7.2l-7.5 7.5a7.2 7.2 0 0 0 10.2 10.2l6.2-6.2"/>',
    "camera": '<path d="M4.4 8.6A1.6 1.6 0 0 1 6 7h2.1l1.1-1.9h5.6L15.9 7H18a1.6 1.6 0 0 1 1.6 1.6v8A1.6 1.6 0 0 1 18 18.2H6a1.6 1.6 0 0 1-1.6-1.6z"/>'
              '<path d="M12 15.4a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2Z"/>',

    # —— 编辑格式 ——
    "bold": '<path d="M8 4.6h4.9a3.55 3.55 0 0 1 0 7.1H8Z"/><path d="M8 11.7h5.8a3.9 3.9 0 0 1 0 7.8H8Z"/>',
    "italic": '<path d="M14.6 4.6H9.8M14.2 19.4H9.4M15 4.6l-3.7 14.8"/>',
    "underline": '<path d="M7 4.6v6.7a5 5 0 0 0 10 0V4.6"/><path d="M5.6 19.4h12.8"/>',
    "strike": '<path d="M5 12.1h14"/><path d="M8.3 8.4c0-2 1.7-3.4 3.9-3.4 1.7 0 3.1.8 3.7 2"/>'
              '<path d="M15.7 15.7c0 2-1.7 3.4-3.9 3.4-1.9 0-3.4-1-3.9-2.4"/>',
    "highlight": '<path d="M5 20.6h9.6"/><path d="M11.4 17.6L5.5 11.7l7.4-7.4a1.6 1.6 0 0 1 2.3 0l3.6 3.6a1.6 1.6 0 0 1 0 2.3z"/><path d="M9.4 7.8l6.9 6.9"/>',
    "textcolor": '<path d="M6 19.4h12"/><path d="M9.3 15.4l3-8.4h.5l3 8.4"/><path d="M10.4 12.4h4"/>',
    "heading": '<path d="M5.6 5.6v12.8M12.6 5.6v12.8M5.6 12h7"/><path d="M17.2 18.4v-8.6l-2.4 1.7"/>',
    "list": '<path d="M9.2 6.6h11M9.2 12h11M9.2 17.4h11"/><path d="M4.6 6.6h.02M4.6 12h.02M4.6 17.4h.02"/>',
    "listnum": '<path d="M9.2 6.6h11M9.2 12h11M9.2 17.4h11"/>'
               '<path d="M4.1 4.9h1.2v3.4M3.7 8.3h3.1"/><path d="M3.7 11.9h2l-2 2.7h2"/>',
    "todo": '<path d="M4.6 5.4A1.3 1.3 0 0 1 5.9 4.1h4.2A1.3 1.3 0 0 1 11.4 5.4v4.2a1.3 1.3 0 0 1-1.3 1.3H5.9a1.3 1.3 0 0 1-1.3-1.3z"/>'
            '<path d="M6.4 7.2l1.4 1.4 2.6-2.8"/><path d="M14.4 5.8h5.6M14.4 12h5.6M4.6 17.6h15.4M4.6 21h9.2"/>',
    "quote": '<path d="M4.6 7.6h14.8"/><path d="M7.6 12.1h11.8"/><path d="M7.6 16.6h11.8"/>',
    "code": '<path d="M9 8.4L5.2 12 9 15.6M15 8.4L18.8 12 15 15.6M13.3 5.4l-2.6 13.2"/>',
    "link": '<path d="M10.4 13.6a3.7 3.7 0 0 0 5.2 0l2.7-2.7a3.7 3.7 0 0 0-5.2-5.2l-1.2 1.2"/>'
            '<path d="M13.6 10.4a3.7 3.7 0 0 0-5.2 0l-2.7 2.7a3.7 3.7 0 0 0 5.2 5.2l1.2-1.2"/>',
    "table": '<path d="M4.4 6.4A1.6 1.6 0 0 1 6 4.8h12a1.6 1.6 0 0 1 1.6 1.6v11.2A1.6 1.6 0 0 1 18 19.2H6a1.6 1.6 0 0 1-1.6-1.6z"/>'
             '<path d="M4.4 9.9h15.2M4.4 14.1h15.2M12 4.8v14.4"/>',
    "divider": '<path d="M3.8 12h3.4M10.3 12h3.4M16.8 12h3.4"/>',
    "undo": '<path d="M8.4 8.6L5 12l3.4 3.4"/><path d="M5 12h9.1a5.1 5.1 0 0 1 0 10.2h-3.8"/>',
    "redo": '<path d="M15.6 8.6L19 12l-3.4 3.4"/><path d="M19 12h-9.1a5.1 5.1 0 0 0 0 10.2h3.8"/>',
    "clear": '<path d="M9.4 5.4l7.6 7.6a1.4 1.4 0 0 1 0 2l-3.4 3.4a1.4 1.4 0 0 1-2 0L5.2 12z"/>'
             '<path d="M13.6 20.6H20"/><path d="M15.4 9.4l-7.6 7.6"/>',
    "eraser": '<path d="M8.6 19.4h9.8"/><path d="M12.2 15.8L6 9.6a1.5 1.5 0 0 1 0-2.1l3.9-3.9a1.5 1.5 0 0 1 2.1 0l6.2 6.2a1.5 1.5 0 0 1 0 2.1z"/><path d="M9.6 8.2l6.6 6.6"/>',

    # —— 功能 ——
    "save": '<path d="M5.6 5.6A1.6 1.6 0 0 1 7.2 4h8.1L20 8.7v9.7a1.6 1.6 0 0 1-1.6 1.6H7.2A1.6 1.6 0 0 1 5.6 18.4z"/>'
            '<path d="M8.6 4v5.2h5.8V4"/><path d="M8.6 20v-5.6h6.8V20"/>',
    "export": '<path d="M12 15.4V4.2"/><path d="M8.1 8.1L12 4.2l3.9 3.9"/>'
              '<path d="M4.8 14.6v4.1A1.5 1.5 0 0 0 6.3 20.2h11.4a1.5 1.5 0 0 0 1.5-1.5v-4.1"/>',
    "import": '<path d="M12 4.2v11.2"/><path d="M8.1 11.5l3.9 3.9 3.9-3.9"/>'
              '<path d="M4.8 14.6v4.1A1.5 1.5 0 0 0 6.3 20.2h11.4a1.5 1.5 0 0 0 1.5-1.5v-4.1"/>',
    "copy": '<path d="M9 9.6A1.6 1.6 0 0 1 10.6 8h6.8A1.6 1.6 0 0 1 19 9.6v6.8a1.6 1.6 0 0 1-1.6 1.6h-6.8A1.6 1.6 0 0 1 9 16.4z"/>'
            '<path d="M5.6 15A1.6 1.6 0 0 1 5 13.8V6.6A1.6 1.6 0 0 1 6.6 5h7.2a1.6 1.6 0 0 1 1.2.6"/>',
    "bookmark": '<path d="M8.4 4.4h7.2a1.1 1.1 0 0 1 1.1 1.1v14.1l-4.7-2.9-4.7 2.9V5.5a1.1 1.1 0 0 1 1.1-1.1Z"/>',
    "globe": '<path d="M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6Z"/><path d="M4.4 12h15.2"/>'
             '<path d="M12 4.2a13.4 13.4 0 0 1 0 15.6 13.4 13.4 0 0 1 0-15.6Z"/>',
    "download": '<path d="M12 4.2v11.2"/><path d="M8.1 11.5l3.9 3.9 3.9-3.9"/><path d="M4.8 19.8h14.4"/>',
    "eye": '<path d="M2.8 12S6.4 5.8 12 5.8 21.2 12 21.2 12 17.6 18.2 12 18.2 2.8 12 2.8 12Z"/>'
           '<path d="M12 14.6a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2Z"/>',
    "calendar": '<path d="M5 6.6A1.6 1.6 0 0 1 6.6 5h10.8A1.6 1.6 0 0 1 19 6.6v10.8a1.6 1.6 0 0 1-1.6 1.6H6.6A1.6 1.6 0 0 1 5 17.4z"/>'
                '<path d="M5 9.6h14M9.2 3.4v3.2M14.8 3.4v3.2"/>',
    "user": '<path d="M12 11.6a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2Z"/><path d="M5.4 20.6a6.6 6.6 0 0 1 13.2 0"/>',
    "grid": '<path d="M5 5h5.8v5.8H5zM13.2 5H19v5.8h-5.8zM5 13.2h5.8V19H5zM13.2 13.2H19V19h-5.8z"/>',
    "rows": '<path d="M4.6 7h14.8M4.6 12h14.8M4.6 17h14.8"/>',
    "sun": '<path d="M12 16.2a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Z"/><path d="M12 2.6v2.2M12 19.2v2.2M4.6 12h2.2M17.2 12h2.2M6.6 6.6l1.6 1.6M15.8 15.8l1.6 1.6M17.4 6.6l-1.6 1.6M8.2 15.8l-1.6 1.6"/>',
    "moon": '<path d="M20.2 14.4A8.6 8.6 0 0 1 9.6 3.8 8.6 8.6 0 1 0 20.2 14.4Z"/>',
    "filter": '<path d="M4.4 6.4h15.2l-5.9 6.7v5.2l-3.4 1.7v-6.9z"/>',
    "sort": '<path d="M7.2 6v12"/><path d="M4.2 15l3 3 3-3"/><path d="M16.8 18V6"/><path d="M13.8 9l3-3 3 3"/>',
    "more": '<path d="M6 12h.02M12 12h.02M18 12h.02"/>',
    "close": '<path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/>',
    "minimize": '<path d="M6 12h12"/>',
    "maximize": '<path d="M6.6 6.6h10.8v10.8H6.6z"/>',
    "restore": '<path d="M8.8 8.8h9.6v9.6H8.8z"/><path d="M6.6 15.2V6.6h9.2"/>',
    "chevron-down": '<path d="M7.2 10l4.8 4.8L16.8 10"/>',
    "chevron-up": '<path d="M7.2 14.4L12 9.6l4.8 4.8"/>',
    "chevron-right": '<path d="M10 7.2l4.8 4.8L10 16.8"/>',
    "chevron-left": '<path d="M14 7.2L9.2 12 14 16.8"/>',
    "info": '<path d="M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6Z"/><path d="M12 11.2v5.2M12 7.9h.02"/>',
    "warning": '<path d="M12 4.4l8.9 15.2H3.1z"/><path d="M12 10.2v4M12 16.7h.02"/>',
    "refresh": '<path d="M19.6 12a7.6 7.6 0 1 1-2.3-5.4"/><path d="M19.8 4.9v4.3h-4.3"/>',
    "lock": '<path d="M6.6 10.4h10.8a1 1 0 0 1 1 1v6.8a1 1 0 0 1-1 1H6.6a1 1 0 0 1-1-1v-6.8a1 1 0 0 1 1-1Z"/>'
             '<path d="M8.6 10.4V8a3.4 3.4 0 0 1 6.8 0v2.4"/>',
    "pin": '<path d="M12 17.4v4M8.6 3.6h6.8l-.8 4.6 3.4 3.2H6l3.4-3.2z"/>',
    "sigma": '<path d="M17.2 5.4H6.8l5 6.6-5 6.6h10.4"/>',
    "hash": '<path d="M9.4 3.8L7.6 20.2M16.4 3.8l-1.8 16.4M4.4 9.2h15M4 14.8h15"/>',
    "workspace": '<path d="M3.4 8.2A1.6 1.6 0 0 1 5 6.6h3.4l1.6 2h9A1.6 1.6 0 0 1 20.6 10.2v8a1.6 1.6 0 0 1-1.6 1.6H5a1.6 1.6 0 0 1-1.6-1.6z"/>'
                 '<path d="M12 12v5.8M9.1 14.9h5.8"/>',
    "help": '<path d="M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6Z"/>'
            '<path d="M9.6 9.6a2.5 2.5 0 0 1 4.8.8c0 1.7-2.4 2.5-2.4 2.5"/><path d="M12 16.8h.02"/>',
    "zoom-in": '<path d="M10.8 4.2a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2Z"/><path d="M15.6 15.6L20 20"/>'
               '<path d="M10.8 8.4v4.8M8.4 10.8h4.8"/>',
    "zoom-out": '<path d="M10.8 4.2a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2Z"/><path d="M15.6 15.6L20 20"/>'
                '<path d="M8.4 10.8h4.8"/>',
    "rotate": '<path d="M4.4 12a7.6 7.6 0 1 0 2.3-5.4"/><path d="M4.2 4.9v4.3h4.3"/>',
    "fullscreen": '<path d="M4.6 9.2V4.6h4.6M19.4 9.2V4.6h-4.6M4.6 14.8v4.6h4.6M19.4 14.8v4.6h-4.6"/>',
    "sync": '<path d="M4.6 11a7.4 7.4 0 0 1 12.6-4.6l2.2 2.1"/><path d="M19.4 3.9v4.6h-4.6"/>'
            '<path d="M19.4 13a7.4 7.4 0 0 1-12.6 4.6L4.6 15.5"/><path d="M4.6 20.1v-4.6h4.6"/>',
    "inbox": '<path d="M4.4 12.6L6.6 5.4A1.6 1.6 0 0 1 8.1 4.2h7.8a1.6 1.6 0 0 1 1.5 1.2l2.2 7.2"/>'
             '<path d="M4.4 12.6h4.3l1.3 2.6h4l1.3-2.6h4.3v5.4a1.6 1.6 0 0 1-1.6 1.6H6a1.6 1.6 0 0 1-1.6-1.6z"/>',
}

# 需要填充的图标（不描边）
_F = {
    "star_fill": "M12 3.1l2.75 5.75 6.25.88-4.55 4.35L17.6 20.3 12 17.35 6.4 20.3l1.15-6.22L3 9.73l6.25-.88z",
    "spark_fill": "M12 2.6c.85 5.1 2.55 6.8 7.65 7.65-5.1.85-6.8 2.55-7.65 7.65-.85-5.1-2.55-6.8-7.65-7.65C9.45 9.4 11.15 7.7 12 2.6Z",
    "dot": "M12 8.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2Z",
    "pin_fill": "M8.6 3.6h6.8l-.8 4.6 3.4 3.2H6l3.4-3.2zM11.05 13.4h1.9v7.6h-1.9z",
}

_CACHE: dict[tuple, QIcon] = {}
_PX_CACHE: dict[tuple, QPixmap] = {}


def _svg_source(name: str, color: str) -> str:
    """生成完整 SVG 源。

    注意：Qt 的 QSvgRenderer 不会把根 <svg> 上的 fill / stroke 继承给子 <path>，
    因此这里把描边属性直接写到每个 path 上，否则闭合路径会被填充成黑块。
    """
    stroke_style = (f'fill="none" stroke="{color}" stroke-width="1.7" '
                    'stroke-linecap="round" stroke-linejoin="round"')
    if name in _F:
        inner = f'<path d="{_F[name]}" fill="{color}" stroke="none"/>'
    else:
        raw = _S.get(name) or _S["note"]
        inner = raw.replace("<path", f"<path {stroke_style}")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>"
    )


def render_pixmap(name: str, color: str, size: int = 20, dpr: float = 1.0) -> QPixmap:
    key = (name, color, size, dpr)
    if key in _PX_CACHE:
        return _PX_CACHE[key]
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg_source(name, color).encode("utf-8")))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    # 必须显式给出目标矩形：不带矩形时 render() 会使用 painter.viewport()，
    # 而带 devicePixelRatio 的 QPixmap 上该值是"设备无关尺寸"，与实际物理
    # 坐标系不一致，图标会被缩到左上角 1/4 区域（表现为残缺弧线）。
    renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
    painter.end()
    _PX_CACHE[key] = px
    return px


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """按颜色渲染图标；自动生成 1x / 2x 位图以保证高分屏清晰。"""
    key = (name, color, size)
    if key in _CACHE:
        return _CACHE[key]
    ic = QIcon()
    ic.addPixmap(render_pixmap(name, color, size, 1.0))
    ic.addPixmap(render_pixmap(name, color, size, 2.0))
    _CACHE[key] = ic
    return ic


def has_icon(name: str) -> bool:
    return name in _S or name in _F


def clear_cache() -> None:
    _CACHE.clear()
    _PX_CACHE.clear()


# --------------------------------------------------------------------------- #
# 应用图标
# --------------------------------------------------------------------------- #
def app_icon() -> QIcon:
    """优先使用构建期生成的 PNG 多尺寸图标，回退到内嵌渲染。"""
    from .config import ASSETS_DIR

    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        p = ASSETS_DIR / "icons" / f"logo_{size}.png"
        if p.exists():
            ic.addFile(str(p), QSize(size, size))
    if not ic.isNull():
        return ic

    # 回退：直接从 SVG 缩放
    svg_path = ASSETS_DIR / "logo.svg"
    if svg_path.exists():
        px = QPixmap(512, 512)
        px.fill(Qt.transparent)
        r = QSvgRenderer(str(svg_path))
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        r.render(p)
        p.end()
        for size in (16, 24, 32, 48, 64, 128, 256):
            ic.addPixmap(px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return ic


def logo_pixmap(size: int = 40) -> QPixmap:
    from .config import ASSETS_DIR

    p = ASSETS_DIR / "icons" / f"logo_{size}.png"
    if p.exists():
        return QPixmap(str(p))
    svg_path = ASSETS_DIR / "logo.svg"
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    if svg_path.exists():
        r = QSvgRenderer(str(svg_path))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r.render(painter)
        painter.end()
    return px
