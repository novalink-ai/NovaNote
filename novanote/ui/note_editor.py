"""笔记编辑器：富文本正文、格式工具栏、媒体附件区、标签与文献关联。"""
from __future__ import annotations

import re

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..models import Asset, Note
from ..services.assets import format_duration, human_size
from ..theme import editor_stylesheet, tokens
from ..widgets.common import IconButton, TextButton, rgba
from ..widgets.flow_layout import FlowLayout

HIGHLIGHT_COLORS = [
    ("#F6E3B4", "暖黄"), ("#D9EAD3", "浅绿"), ("#D7E6F3", "雾蓝"),
    ("#F8DCD8", "浅红"), ("#EADCF3", "淡紫"), ("#EFE7DA", "暖灰"),
]
TEXT_COLORS = ["#1D2936", "#3A6E93", "#D0854C", "#BE5A50", "#57896A", "#6E7FA8", "#8B9AAB"]

ASSET_URL_PREFIX = "asset:"

# QTextBlockFormat.LineHeightTypes: Single=0, Proportional=1, Fixed=2, Minimum=3, LineDistance=4
_LINE_PROPORTIONAL = 1


def normalize_asset_urls(html: str) -> str:
    """把各种可能出现的图片地址统一成 `asset:<相对路径>`。

    Qt 在 toHtml() 时可能把内部 URL 写成 `file:///...`、`asset:///...` 或绝对路径，
    这里统一归一化，保证存库的 HTML 在工作空间被移动后依然可用。
    """
    if not html:
        return html
    html = html.replace("asset:///", "asset:").replace("asset://", "asset:")
    html = re.sub(r'file:/{2,3}[^"\']*?/assets/', "asset:assets/", html)
    html = re.sub(r'src="[A-Za-z]:[^"]*?/assets/', 'src="asset:assets/', html)
    html = re.sub(r"src='[A-Za-z]:[^']*?/assets/", "src='asset:assets/", html)
    html = re.sub(r'src="assets/', 'src="asset:assets/', html)
    return html


# --------------------------------------------------------------------------- #
class AssetDocument(QTextDocument):
    """支持 asset: 伪协议的文档，用于在正文里内联工作空间内的图片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resolver = None          # callable(rel_path: str) -> QImage | None

    def set_resolver(self, fn) -> None:
        self.resolver = fn

    def loadResource(self, type_: int, url: QUrl):  # noqa: N802
        s = url.toString()
        if s.startswith(ASSET_URL_PREFIX):
            rel = s[len(ASSET_URL_PREFIX):].lstrip("/\\")
            if self.resolver is not None:
                data = self.resolver(rel)
                if data is not None:
                    return data
        if s.startswith("file:"):
            path = QUrl(s).toLocalFile()
            if path:
                img = QImage(path)
                if not img.isNull():
                    return img
        return super().loadResource(type_, url)


# --------------------------------------------------------------------------- #
class RichTextEdit(QTextEdit):
    filesDropped = Signal(list)
    imagePasted = Signal(QImage)
    dirtyChanged = Signal()
    saveRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("NoteBody")
        self.setAcceptRichText(True)
        self.setAcceptDrops(True)
        self.setTabChangesFocus(False)
        self.setFrameShape(QFrame.NoFrame)
        self._theme = theme
        self._loading = False
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.textChanged.connect(self._on_text_changed)

    # ---- 状态 ---- #
    def begin_load(self) -> None:
        self._loading = True

    def end_load(self) -> None:
        self._loading = False
        self.document().clearUndoRedoStacks()

    def _on_text_changed(self) -> None:
        if not self._loading:
            self.dirtyChanged.emit()

    # ---- 粘贴 / 拖放 ---- #
    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                self.imagePasted.emit(img)
                return
        if source.hasUrls():
            paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
                return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    # ---- 待办勾选 ---- #
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._toggle_todo(event.position().toPoint()):
            event.accept()
            return
        super().mousePressEvent(event)

    def _toggle_todo(self, pos) -> bool:
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        text = block.text()
        if not text:
            return False
        stripped = text.lstrip()
        for mark, repl in (("☐", "☑"), ("☑", "☐")):
            if stripped.startswith(mark):
                # 只有点击在行首区域才切换，避免误触
                block_rect = self.cursorRect(cursor.atStartOfBlock())
                if pos.x() > block_rect.left() + 40:
                    return False
                c = QTextCursor(block)
                c.movePosition(QTextCursor.StartOfBlock)
                start = text.index(mark)
                c.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, start)
                c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                c.insertText(repl)
                return True
        return False

    # ---- Enter 自动续接列表 ---- #
    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers():
            cursor = self.textCursor()
            current_list = cursor.currentList()
            if current_list is not None:
                block_text = cursor.block().text().strip()
                if block_text in ("☐", "☑", "•", "-", ""):
                    # 空列表项 → 退出列表
                    current_list.remove(cursor.block())
                    fmt = QTextBlockFormat()
                    fmt.setIndent(0)
                    cursor.setBlockFormat(fmt)
                    self.setTextCursor(cursor)
                    event.accept()
                    return
                marker = self._list_marker(current_list)
                if marker:
                    self._continue_prefix = marker
        super().keyPressEvent(event)

    def _list_marker(self, lst) -> str:
        # 判断是否为"手写标记"型列表（我们用手写符号实现待办）
        return ""

    # ---- 撤销/重做快捷键在工具栏处理 ---- #
    def focusOutEvent(self, event):  # noqa: N802
        self.saveRequested.emit()
        super().focusOutEvent(event)


# --------------------------------------------------------------------------- #
class FormatBar(QFrame):
    """格式工具栏。"""

    action = Signal(str, object)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("FormatBar")
        self._theme = theme
        self._buttons: list = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 5, 20, 5)
        lay.setSpacing(3)

        # 段落样式
        self.style_box = QComboBox()
        for label, level in (("正文", 0), ("标题 1", 1), ("标题 2", 2), ("标题 3", 3),
                             ("引用", 4), ("代码块", 5)):
            self.style_box.addItem(label, level)
        self.style_box.setFixedWidth(96)
        self.style_box.setFixedHeight(28)
        self.style_box.activated.connect(
            lambda i: self.action.emit("block", self.style_box.itemData(i)))
        lay.addWidget(self.style_box)
        lay.addWidget(self._sep())

        groups = [
            [("bold", "bold", "加粗 Ctrl+B"), ("italic", "italic", "斜体 Ctrl+I"),
             ("underline", "underline", "下划线 Ctrl+U"), ("strike", "strike", "删除线")],
            [("highlight", "highlight", "高亮"), ("textcolor", "textcolor", "文字颜色"),
             ("__textcolor_more", "clear", "清除格式")],
            [("list", "list", "无序列表"), ("listnum", "listnum", "有序列表"),
             ("todo", "todo", "待办事项")],
            [("quote", "quote", "引用块"), ("code", "code", "代码块"),
             ("divider", "divider", "分割线")],
            [("link", "link", "插入链接 Ctrl+K"), ("table", "table", "插入表格")],
            [("image", "image", "插入图片"), ("video", "video", "插入视频/附件")],
        ]
        for gi, group in enumerate(groups):
            if gi:
                lay.addWidget(self._sep())
            for key, icn, tip in group:
                b = IconButton(icn, theme, 28, 17, tip=tip)
                b.setProperty("fmt", key)
                if key == "textcolor":
                    b.clicked.connect(lambda _=False, w=b: self._show_color_menu(w, "text"))
                elif key == "highlight":
                    b.clicked.connect(lambda _=False, w=b: self._show_color_menu(w, "highlight"))
                elif key == "__textcolor_more":
                    b.clicked.connect(lambda: self.action.emit("clear_format", None))
                else:
                    b.clicked.connect(lambda _=False, k=key: self.action.emit(k, None))
                lay.addWidget(b)
                self._buttons.append(b)

        lay.addStretch(1)

        for key, icn, tip in (("undo", "undo", "撤销 Ctrl+Z"), ("redo", "redo", "重做 Ctrl+Y")):
            b = IconButton(icn, theme, 28, 17, tip=tip)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k, None))
            lay.addWidget(b)
            self._buttons.append(b)

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFixedWidth(1)
        f.setFixedHeight(18)
        f.setStyleSheet(f"background: {tokens(self._theme)['border']};")
        return f

    def _show_color_menu(self, widget, kind: str) -> None:
        menu = QMenu(self)
        title = menu.addAction("文字颜色" if kind == "text" else "高亮颜色")
        title.setEnabled(False)
        menu.addSeparator()
        items = [(c, c) for c in TEXT_COLORS] if kind == "text" else HIGHLIGHT_COLORS
        for key, name in items:
            act = menu.addAction(name)
            act.setIcon(_swatch_icon(key))
            act.triggered.connect(
                lambda _=False, c=key, k=kind: self.action.emit(
                    "textcolor" if k == "text" else "highlight", c)
            )
        menu.exec(widget.mapToGlobal(QPoint(0, widget.height() + 4)))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for b in self._buttons:
            b.refresh(theme)

    def sync_state(self, char_fmt: QTextCharFormat, block_level: int) -> None:
        for b in self._buttons:
            key = b.property("fmt")
            if key == "bold":
                b.setChecked(char_fmt.fontWeight() >= QFont.Bold)
            elif key == "italic":
                b.setChecked(char_fmt.fontItalic())
            elif key == "underline":
                b.setChecked(char_fmt.fontUnderline())
            elif key == "strike":
                b.setChecked(char_fmt.fontStrikeOut())
        levels = {0: 0, 1: 1, 2: 2, 3: 3}
        idx = levels.get(block_level, 0)
        if self.style_box.currentIndex() != idx:
            self.style_box.blockSignals(True)
            self.style_box.setCurrentIndex(idx)
            self.style_box.blockSignals(False)


def _swatch_icon(color: str) -> QPixmap:
    px = QPixmap(14, 14)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(color))
    p.setPen(QColor(180, 190, 200))
    p.drawRoundedRect(0, 0, 13, 13, 4, 4)
    p.end()
    return px


# --------------------------------------------------------------------------- #
class AssetStrip(QListWidget):
    """附件缩略图条。"""

    activatedAsset = Signal(int)
    removeAsset = Signal(int)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("AttachmentStrip")
        self._theme = theme
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(84, 64))
        self.setGridSize(QSize(104, 96))
        self.setMovement(QListWidget.Static)
        self.setResizeMode(QListWidget.Adjust)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(104)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)
        self.itemDoubleClicked.connect(lambda it: self.activatedAsset.emit(int(it.data(Qt.UserRole))))

    def set_assets(self, assets: list[Asset], thumbs: dict[int, QPixmap]) -> None:
        self.clear()
        for a in assets:
            icon_name = {"image": "image", "video": "video", "audio": "volume"}.get(a.kind, "paperclip")
            px = thumbs.get(a.id)
            if px is not None and not px.isNull():
                icon = px.scaled(84, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                icon = icons.render_pixmap(icon_name, tokens(self._theme)["text_muted"], 34)
            label = a.filename if len(a.filename) <= 14 else a.filename[:12] + "…"
            if a.kind == "video" and a.duration_ms:
                label += f"\n{format_duration(a.duration_ms)}"
            elif a.kind == "image" and a.width:
                label += f"\n{a.width}×{a.height}"
            item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, a.id)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setToolTip(f"{a.filename}\n{a.size_text}"
                            + (f"\n{a.caption}" if a.caption else ""))
            item.setSizeHint(QSize(100, 92))
            self.addItem(item)

    def _ctx(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.activatedAsset.emit(int(item.data(Qt.UserRole))))
        menu.addAction("从笔记中移除", lambda: self.removeAsset.emit(int(item.data(Qt.UserRole))))
        menu.exec(self.viewport().mapToGlobal(pos))

    def refresh(self, theme: str) -> None:
        self._theme = theme


# --------------------------------------------------------------------------- #
class NoteEditor(QWidget):
    """完整笔记编辑器。"""

    saveRequested = Signal()
    titleChanged = Signal(str)
    starToggled = Signal(bool)
    notebookChanged = Signal(object)
    assetActivated = Signal(int)
    assetRemoved = Signal(int)
    assetAdded = Signal(list)               # list[str] 文件路径；空列表表示弹出选择框
    imagePasted = Signal(QImage)
    tagClicked = Signal(str)
    tagsEdited = Signal(list)
    refLinkRequested = Signal()
    refUnlinkRequested = Signal(int)
    refClicked = Signal(int)
    moreActionRequested = Signal(str)
    contentChanged = Signal()

    def __init__(self, theme: str = "light", editor_font: str = "Sitka Text",
                 editor_size: int = 15, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._note: Note | None = None
        self._loading = False
        self._asset_ids: list[int] = []
        self._editor_font = editor_font
        self._editor_size = editor_size
        self._tags: list[str] = []
        self._linked: list = []

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(900)
        self._save_timer.timeout.connect(self.saveRequested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 头部 ---------- #
        head = QWidget()
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(28, 16, 24, 8)
        head_lay.setSpacing(7)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("TitleEdit")
        self.title_edit.setPlaceholderText("无标题")
        self.title_edit.textChanged.connect(self._on_title_changed)
        self.title_edit.returnPressed.connect(self._focus_body)
        r1.addWidget(self.title_edit, 1)

        self.star = IconButton("star", theme, 30, 19, tip="收藏（Ctrl+Shift+S）")
        self.star.setCheckable(True)
        self.star.clicked.connect(lambda: self.starToggled.emit(self.star.isChecked()))
        r1.addWidget(self.star)

        self.btn_more = IconButton("more", theme, 30, 18, tip="更多操作")
        self.btn_more.clicked.connect(self._show_more_menu)
        r1.addWidget(self.btn_more)
        head_lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.nb_box = QComboBox()
        self.nb_box.setFixedHeight(27)
        self.nb_box.setMinimumWidth(120)
        self.nb_box.setMaximumWidth(220)
        self.nb_box.currentIndexChanged.connect(self._on_nb_changed)
        r2.addWidget(self.nb_box)

        self.meta_label = QLabel("")
        self.meta_label.setProperty("role", "muted")
        r2.addWidget(self.meta_label)

        self.saved_label = QLabel("")
        self.saved_label.setProperty("role", "muted")
        self.saved_label.setStyleSheet(f"color: {tokens(theme)['success']}; font-size: 11px;")
        r2.addWidget(self.saved_label)
        r2.addStretch(1)
        head_lay.addLayout(r2)
        root.addWidget(head)

        # ---------- 格式栏 ---------- #
        self.format_bar = FormatBar(theme)
        self.format_bar.action.connect(self._on_format_action)
        root.addWidget(self.format_bar)

        # ---------- 正文 ---------- #
        body_wrap = QWidget()
        body_lay = QVBoxLayout(body_wrap)
        body_lay.setContentsMargins(28, 12, 24, 8)
        body_lay.setSpacing(8)

        self.body = RichTextEdit(theme)
        self.body.setDocument(AssetDocument(self.body))
        self.body.dirtyChanged.connect(self._on_dirty)
        self.body.filesDropped.connect(self._on_files_dropped)
        self.body.imagePasted.connect(self.imagePasted.emit)
        self.body.saveRequested.connect(self.saveRequested.emit)
        self.body.cursorPositionChanged.connect(self._sync_format_state)
        self.body.currentCharFormatChanged.connect(lambda _f: self._sync_format_state())
        body_lay.addWidget(self.body, 1)

        self.placeholder = QLabel("开始记录…  支持 Ctrl+B 加粗、拖入图片/视频、粘贴截图")
        self.placeholder.setProperty("role", "muted")
        self.placeholder.setParent(self.body)
        self.placeholder.move(2, 2)
        self.placeholder.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        root.addWidget(body_wrap, 1)

        # ---------- 附件区 ---------- #
        self.attach_wrap = QWidget()
        al = QVBoxLayout(self.attach_wrap)
        al.setContentsMargins(28, 0, 24, 0)
        al.setSpacing(5)
        arow = QHBoxLayout()
        arow.setSpacing(6)
        self.attach_title = QLabel("附件")
        self.attach_title.setProperty("role", "h3")
        self.attach_count = QLabel("")
        self.attach_count.setProperty("role", "muted")
        arow.addWidget(self.attach_title)
        arow.addWidget(self.attach_count)
        arow.addStretch(1)
        btn_add_asset = IconButton("plus", theme, 24, 14, tip="添加附件")
        btn_add_asset.clicked.connect(lambda: self.assetAdded.emit([]))
        arow.addWidget(btn_add_asset)
        al.addLayout(arow)
        self.strip = AssetStrip(theme)
        self.strip.activatedAsset.connect(self.assetActivated.emit)
        self.strip.removeAsset.connect(self.assetRemoved.emit)
        al.addWidget(self.strip)
        root.addWidget(self.attach_wrap)
        self.attach_wrap.setVisible(False)

        # ---------- 底部：标签 + 文献 ---------- #
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(28, 6, 24, 12)
        fl.setSpacing(7)

        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        tl = QLabel("标签")
        tl.setProperty("role", "h3")
        tl.setFixedWidth(30)
        tag_row.addWidget(tl)
        self.tag_host = QWidget()
        self.tag_flow = FlowLayout(self.tag_host, margin=0, h_spacing=5, v_spacing=5)
        tag_row.addWidget(self.tag_host, 1)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("+ 标签")
        self.tag_input.setFixedWidth(104)
        self.tag_input.setFixedHeight(26)
        self.tag_input.returnPressed.connect(self._commit_tag)
        tag_row.addWidget(self.tag_input, 0, Qt.AlignTop)
        fl.addLayout(tag_row)

        ref_row = QHBoxLayout()
        ref_row.setSpacing(6)
        rl = QLabel("文献")
        rl.setProperty("role", "h3")
        rl.setFixedWidth(30)
        ref_row.addWidget(rl)
        self.ref_host = QWidget()
        self.ref_flow = FlowLayout(self.ref_host, margin=0, h_spacing=5, v_spacing=5)
        ref_row.addWidget(self.ref_host, 1)
        self.btn_link_ref = TextButton("关联", "link", theme, "subtle")
        self.btn_link_ref.setFixedHeight(26)
        self.btn_link_ref.clicked.connect(self.refLinkRequested.emit)
        ref_row.addWidget(self.btn_link_ref, 0, Qt.AlignTop)
        fl.addLayout(ref_row)
        root.addWidget(foot)

    # ================================================================== #
    # 加载 / 保存
    # ================================================================== #
    def load(self, note: Note, assets: list[Asset], thumbs: dict[int, QPixmap],
             notebooks: list, linked_refs: list) -> None:
        self._loading = True
        self._note = note
        self._asset_ids = [a.id for a in assets]
        self._linked = linked_refs

        self.title_edit.blockSignals(True)
        self.title_edit.setText(note.title)
        # 光标移回开头，避免长标题被自动滚到可见区尾部（只看得见后半段）
        self.title_edit.setCursorPosition(0)
        self.title_edit.blockSignals(False)

        self.nb_box.blockSignals(True)
        self.nb_box.clear()
        self.nb_box.addItem("未分类", None)
        for nb in notebooks:
            self.nb_box.addItem(nb.name, nb.id)
        idx = self.nb_box.findData(note.notebook_id)
        self.nb_box.setCurrentIndex(max(0, idx))
        self.nb_box.blockSignals(False)

        self.star.setChecked(note.is_starred)
        self._refresh_star_icon()

        self.body.begin_load()
        self.body.document().setDefaultStyleSheet(
            editor_stylesheet(self._theme, self._editor_font, self._editor_size))
        self.body.setHtml(normalize_asset_urls(note.body_html or ""))
        self._apply_line_height()
        self.body.end_load()

        self.meta_label.setText(
            f"创建 {note.created_at[:16]}  ·  更新 {note.updated_at[:16]}"
        )
        self.saved_label.setText("")

        self._tags = list(note.tags)
        self._rebuild_tags()
        self._rebuild_refs()
        self.set_assets(assets, thumbs)
        self._update_placeholder()
        self._loading = False

    def set_assets(self, assets: list[Asset], thumbs: dict[int, QPixmap]) -> None:
        self._asset_ids = [a.id for a in assets]
        self.strip.set_assets(assets, thumbs)
        n = len(assets)
        self.attach_wrap.setVisible(n > 0)
        total = sum(a.size for a in assets)
        self.attach_count.setText(f"{n} 项 · {human_size(total)}" if n else "")

    def _rebuild_tags(self) -> None:
        self.tag_flow.clear()
        for name in self._tags:
            chip = _TagChipEditable(name, self._theme)
            chip.removed.connect(self._remove_tag)
            self.tag_flow.addWidget(chip)

    def _rebuild_refs(self) -> None:
        self.ref_flow.clear()
        if not self._linked:
            hint = QLabel("未关联文献")
            hint.setProperty("role", "muted")
            self.ref_flow.addWidget(hint)
        for ref in self._linked:
            chip = _RefChip(ref, self._theme)
            chip.clicked.connect(lambda _=False, r=ref: self.refClicked.emit(r.id))
            chip.removed.connect(lambda r=ref: self.refUnlinkRequested.emit(r.id))
            self.ref_flow.addWidget(chip)

    def _commit_tag(self) -> None:
        name = self.tag_input.text().strip().lstrip("#")
        self.tag_input.clear()
        if not name or name in self._tags:
            return
        self._tags.append(name)
        self._rebuild_tags()
        self.tagsEdited.emit(list(self._tags))

    def _remove_tag(self, name: str) -> None:
        if name in self._tags:
            self._tags.remove(name)
            self._rebuild_tags()
            self.tagsEdited.emit(list(self._tags))

    def add_tag_chip(self, name: str) -> None:
        if name not in self._tags:
            self._tags.append(name)
            self._rebuild_tags()
            self.tagsEdited.emit(list(self._tags))

    # ================================================================== #
    def note(self) -> Note | None:
        return self._note

    def note_id(self) -> int | None:
        return self._note.id if self._note else None

    def collect(self) -> dict:
        return {
            "title": self.title_edit.text().strip() or "无标题笔记",
            "body_html": normalize_asset_urls(self.body.toHtml()),
            "notebook_id": self.nb_box.currentData(),
        }

    def mark_saved(self) -> None:
        self.saved_label.setText("已保存")
        QTimer.singleShot(1800, lambda: self.saved_label.setText(""))

    def schedule_save(self) -> None:
        if not self._loading:
            self._save_timer.start()

    def _on_dirty(self) -> None:
        if self._loading:
            return
        self._update_placeholder()
        self.schedule_save()
        self.contentChanged.emit()

    def _on_title_changed(self, text: str) -> None:
        if self._loading:
            return
        self.titleChanged.emit(text)
        self.schedule_save()
        self.contentChanged.emit()

    def _update_placeholder(self) -> None:
        self.placeholder.setVisible(not self.body.toPlainText().strip())

    def _focus_body(self) -> None:
        self.body.setFocus()

    # ================================================================== #
    # 格式操作
    # ================================================================== #
    def _on_format_action(self, key: str, value) -> None:
        ed = self.body
        cursor = ed.textCursor()
        if key == "undo":
            ed.undo()
            return
        if key == "redo":
            ed.redo()
            return
        if key == "block":
            self._set_block_style(int(value))
            return
        if key == "clear_format":
            fmt = QTextCharFormat()
            cursor.setCharFormat(fmt)
            ed.setCurrentCharFormat(fmt)
        elif key == "bold":
            self._toggle_char("fontWeight")
        elif key == "italic":
            self._toggle_char("fontItalic")
        elif key == "underline":
            self._toggle_char("fontUnderline")
        elif key == "strike":
            self._toggle_char("fontStrikeOut")
        elif key == "highlight":
            self._set_background(value or "#F6E3B4")
        elif key == "textcolor":
            self._set_foreground(value or tokens(self._theme)["text"])
        elif key == "list":
            self._toggle_list(QTextListFormat.ListDisc)
        elif key == "listnum":
            self._toggle_list(QTextListFormat.ListDecimal)
        elif key == "todo":
            self._insert_todo()
        elif key == "quote":
            self._set_block_style(4)
        elif key == "code":
            self._set_block_style(5)
        elif key == "divider":
            cursor.insertHtml("<hr/>")
        elif key == "link":
            self._insert_link()
        elif key == "table":
            self._insert_table()
        elif key in ("image", "video"):
            self.assetAdded.emit([])
            return
        self._sync_format_state()
        self.schedule_save()

    def _merge_char(self, fmt: QTextCharFormat) -> None:
        ed = self.body
        cursor = ed.textCursor()
        if not cursor.hasSelection():
            ed.mergeCurrentCharFormat(fmt)
        else:
            cursor.mergeCharFormat(fmt)
            ed.mergeCurrentCharFormat(fmt)
        ed.setFocus()

    def _toggle_char(self, prop: str) -> None:
        ed = self.body
        cur = ed.currentCharFormat()
        fmt = QTextCharFormat()
        if prop == "fontWeight":
            fmt.setFontWeight(QFont.Normal if cur.fontWeight() >= QFont.Bold else QFont.Bold)
        elif prop == "fontItalic":
            fmt.setFontItalic(not cur.fontItalic())
        elif prop == "fontUnderline":
            fmt.setFontUnderline(not cur.fontUnderline())
        elif prop == "fontStrikeOut":
            fmt.setFontStrikeOut(not cur.fontStrikeOut())
        self._merge_char(fmt)
        self._sync_format_state()

    def _set_foreground(self, color: str) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        self._merge_char(fmt)

    def _set_background(self, color: str) -> None:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(color))
        self._merge_char(fmt)

    def _set_block_style(self, level: int) -> None:
        ed = self.body
        cursor = ed.textCursor()
        cursor.beginEditBlock()
        bf = QTextBlockFormat()
        cf = QTextCharFormat()
        base = self._editor_size
        if level == 0:
            bf.setHeadingLevel(0)
            cf.setFontPointSize(base)
            cf.setFontWeight(QFont.Normal)
            bf.setIndent(0)
            bf.setLeftMargin(0)
        elif level in (1, 2, 3):
            sizes = {1: base * 1.72, 2: base * 1.42, 3: base * 1.18}
            bf.setHeadingLevel(level)
            cf.setFontPointSize(sizes[level])
            cf.setFontWeight(QFont.Bold)
            bf.setIndent(0)
            bf.setLeftMargin(0)
        elif level == 4:      # 引用
            bf.setHeadingLevel(0)
            cf.setFontPointSize(base)
            cf.setFontItalic(True)
            cf.setForeground(QColor(tokens(self._theme)["text_secondary"]))
            bf.setLeftMargin(14)
            bf.setIndent(0)
        else:                 # 代码块
            bf.setHeadingLevel(0)
            cf.setFontFamilies(["Consolas", "Cascadia Mono", "monospace"])
            cf.setFontPointSize(max(9, base - 1))
            cf.setBackground(QColor(tokens(self._theme)["bg_sunken"]))
            bf.setLeftMargin(12)
            bf.setIndent(0)
        bf.setLineHeight(self._line_height(), _LINE_PROPORTIONAL)
        if cursor.hasSelection():
            cursor.mergeBlockFormat(bf)
            cursor.mergeCharFormat(cf)
        else:
            # 应用到整个段落
            c2 = QTextCursor(cursor.block())
            c2.select(QTextCursor.BlockUnderCursor)
            c2.mergeBlockFormat(bf)
            c2.mergeCharFormat(cf)
        cursor.endEditBlock()
        ed.setFocus()

    def _line_height(self) -> int:
        return 168

    def _apply_line_height(self) -> None:
        doc = self.body.document()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.Start)
        bf = QTextBlockFormat()
        bf.setLineHeight(self._line_height(), _LINE_PROPORTIONAL)
        while True:
            cursor.mergeBlockFormat(bf)
            if not cursor.movePosition(QTextCursor.NextBlock):
                break
        cursor.endEditBlock()

    def _toggle_list(self, style: int) -> None:
        ed = self.body
        cursor = ed.textCursor()
        current = cursor.currentList()
        if current is not None and current.format().style() == style:
            current.remove(cursor.block())
            bf = QTextBlockFormat()
            bf.setIndent(0)
            cursor.setBlockFormat(bf)
        else:
            lf = QTextListFormat()
            lf.setStyle(style)
            lf.setIndent(1)
            cursor.createList(lf)
        ed.setFocus()

    def _insert_todo(self) -> None:
        cursor = self.body.textCursor()
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.insertText("\n☐ ")
        self.body.setTextCursor(cursor)
        self.body.setFocus()

    def _insert_link(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(self, "插入链接", "链接地址：", text="https://")
        if not ok or not url.strip():
            return
        cursor = self.body.textCursor()
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url.strip())
        fmt.setForeground(QColor(tokens(self._theme)["blue"]))
        fmt.setFontUnderline(True)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            cursor.insertText(url.strip(), fmt)
        self.body.setFocus()

    def _insert_table(self) -> None:
        rows, cols = 3, 3
        html = ['<table cellspacing="0" cellpadding="5" border="1" width="100%">']
        for r in range(rows):
            html.append("<tr>")
            for c in range(cols):
                tag = "th" if r == 0 else "td"
                html.append(f"<{tag}>表头 {c + 1}</{tag}>" if r == 0 else f"<{tag}>&nbsp;</{tag}>")
            html.append("</tr>")
        html.append("</table><p><br/></p>")
        self.body.textCursor().insertHtml("".join(html))
        self.body.setFocus()

    # ================================================================== #
    # 内联资源
    # ================================================================== #
    def insert_image(self, rel_path: str, width: int = 0, height: int = 0) -> None:
        from PySide6.QtGui import QTextImageFormat

        url = f"{ASSET_URL_PREFIX}{rel_path}"
        cursor = self.body.textCursor()
        img_fmt = QTextImageFormat()
        img_fmt.setName(url)
        if width:
            max_w = 620
            scale = min(1.0, max_w / max(1, width))
            img_fmt.setWidth(width * scale)
            img_fmt.setHeight((height or width) * scale)
        cursor.insertBlock(QTextBlockFormat())
        cursor.insertImage(img_fmt)
        cursor.insertBlock(QTextBlockFormat())
        self.body.setTextCursor(cursor)
        self.refresh_asset_urls()

    def refresh_asset_urls(self) -> None:
        """强制重绘文档中的图片资源。"""
        doc = self.body.document()
        doc.markContentsDirty(0, doc.characterCount())

    def _on_files_dropped(self, paths: list) -> None:
        self.assetAdded.emit(list(paths))

    def _sync_format_state(self) -> None:
        cur = self.body.currentCharFormat()
        block = self.body.textCursor().block()
        level = 0
        try:
            lvl = block.blockFormat().headingLevel()
            if 1 <= lvl <= 3:
                level = lvl
        except Exception:
            level = 0
        self.format_bar.sync_state(cur, level)

    # ================================================================== #
    def _on_nb_changed(self, _idx: int) -> None:
        if self._loading:
            return
        self.notebookChanged.emit(self.nb_box.currentData())
        self.schedule_save()

    def _refresh_star_icon(self) -> None:
        t = tokens(self._theme)
        self.star.setIcon(icons.icon(
            "star_fill" if self.star.isChecked() else "star",
            t["orange"] if self.star.isChecked() else t["text_muted"], 19))

    def set_starred(self, value: bool) -> None:
        self.star.setChecked(value)
        self._refresh_star_icon()

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        acts = [
            ("复制引用信息", "copy_citation"),
            ("导出为 Markdown", "export_md"),
            ("导出为 HTML", "export_html"),
            ("导出为 PDF", "export_pdf"),
            ("复制笔记内容", "copy_body"),
            ("", None),
            ("复制笔记", "duplicate"),
            ("移入回收站", "trash"),
        ]
        for label, key in acts:
            if key is None:
                menu.addSeparator()
                continue
            menu.addAction(label, lambda k=key: self.moreActionRequested.emit(k))
        menu.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 4)))

    # ================================================================== #
    def set_theme(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.format_bar.refresh(theme)
        self.star.refresh(theme)
        self.btn_more.refresh(theme)
        self.strip.refresh(theme)
        self.attach_wrap.setVisible(self.strip.count() > 0)
        self.body.document().setDefaultStyleSheet(
            editor_stylesheet(theme, self._editor_font, self._editor_size))
        self.saved_label.setStyleSheet(f"color: {t['success']}; font-size: 11px;")
        self._rebuild_tags()
        self._rebuild_refs()
        self._refresh_star_icon()

    def set_editor_font(self, family: str, size: int) -> None:
        self._editor_font = family
        self._editor_size = size
        self.body.document().setDefaultStyleSheet(
            editor_stylesheet(self._theme, family, size))
        self.set_theme(self._theme)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "placeholder"):
            self.placeholder.move(2, 2)

    def focus_body(self) -> None:
        self.body.setFocus()


# --------------------------------------------------------------------------- #
class _TagChipEditable(QPushButton):
    removed = Signal(str)

    def __init__(self, text: str, theme: str):
        super().__init__(text, None)
        self._text = text
        self._theme = theme
        c = QColor(tokens(theme)["orange"] if theme == "light" else "#D9925C")
        bg = rgba(c, 30 if theme == "light" else 58)
        fg = c.darker(118).name() if theme == "light" else c.lighter(128).name()
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none;"
            f" border-radius: 8px; padding: 3px 9px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c.name()}; color: #FFFFFF; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("右键移除标签")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def contextMenuEvent(self, event):  # noqa: N802
        self.removed.emit(self._text)
        event.accept()


class _RefChip(QPushButton):
    removed = Signal()

    def __init__(self, ref, theme: str):
        label = f"❝ {ref.authors_short} {ref.year_text}"
        super().__init__(label, None)
        self.setToolTip(ref.title)
        c = QColor(tokens(theme)["blue"])
        bg = rgba(c, 28 if theme == "light" else 56)
        fg = c.darker(118).name() if theme == "light" else c.lighter(130).name()
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none;"
            f" border-radius: 8px; padding: 3px 9px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c.name()}; color: #FFFFFF; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{ref.title}\n（右键取消关联）")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def contextMenuEvent(self, event):  # noqa: N802
        self.removed.emit()
        event.accept()
