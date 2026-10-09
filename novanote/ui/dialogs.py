"""对话框：工作空间向导、偏好设置、关于、笔记本编辑等。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..config import APP_NAME, APP_NAME_CN, APP_TAGLINE, APP_VERSION, default_workspace_root
from ..services.assets import human_size
from ..theme import tokens
from ..widgets.common import Card, HRule, IconButton, TextButton

ICON_CHOICES = ["folder", "note", "book", "spark", "star", "tag", "layers", "todo", "inbox", "clock"]
COLOR_CHOICES = ["#3A6E93", "#D0854C", "#57896A", "#C79A3F", "#9A6E9E",
                 "#4E8C8C", "#BE5A50", "#6E7FA8"]


def _title_row(parent: QWidget, logo_size: int = 34) -> QWidget:
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    logo = QLabel()
    logo.setPixmap(icons.logo_pixmap(logo_size))
    lay.addWidget(logo)
    text = QVBoxLayout()
    text.setSpacing(1)
    name = QLabel(f"{APP_NAME}  ·  {APP_NAME_CN}")
    name.setProperty("role", "h2")
    tag = QLabel(APP_TAGLINE)
    tag.setProperty("role", "muted")
    text.addWidget(name)
    text.addWidget(tag)
    lay.addLayout(text, 1)
    return w


# --------------------------------------------------------------------------- #
class WorkspaceSetupDialog(QDialog):
    """首次启动 / 新建工作空间向导。"""

    def __init__(self, theme: str = "light", recent: list | None = None,
                 mode: str = "welcome", parent=None):
        super().__init__(parent)
        self.setWindowTitle("NovaNote · 工作空间")
        self.setMinimumWidth(620 if mode == "welcome" else 540)
        self.setMinimumHeight(460 if mode == "welcome" else 330)
        self._theme = theme
        self._recent = recent or []
        self.mode = mode
        self.result_action = "cancel"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(14)
        root.addWidget(_title_row(self))

        if mode == "welcome" and self._recent:
            hint = QLabel("选择一个已有工作空间继续，或新建一个。每个工作空间拥有独立的数据库与附件目录。")
        else:
            hint = QLabel("工作空间是一个独立文件夹，内含数据库、附件与导出结果。"
                          "可放在本机任意位置，便于备份或迁移到移动硬盘。")
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        root.addWidget(hint)

        # ---- 最近 ----
        self.recent_box = QListWidget()
        self.recent_box.setFrameShape(QFrame.NoFrame)
        self.recent_box.setMinimumHeight(96)
        self.recent_box.setMaximumHeight(150)
        if self._recent:
            for ref in self._recent:
                state = "可用" if ref.exists() else "路径已失效"
                item = QListWidgetItem(
                    icons.icon("workspace", tokens(theme)["blue"], 16),
                    f"{ref.name}    {ref.path}    ({state})",
                )
                item.setData(Qt.UserRole, ref.id)
                if not ref.exists():
                    item.setForeground(Qt.gray)
                self.recent_box.addItem(item)
            self.recent_box.setCurrentRow(0)
            root.addWidget(QLabel("最近使用"))
            root.addWidget(self.recent_box)
            root.addWidget(HRule())

        # ---- 新建 ----
        root.addWidget(QLabel("新建工作空间"))
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        lab1 = QLabel("名称")
        lab1.setProperty("role", "muted")
        lab1.setFixedWidth(56)
        lab1.setAlignment(Qt.AlignRight)
        self.name_edit = QLineEdit("我的知识库")
        self.name_edit.setMinimumHeight(32)
        name_row.addWidget(lab1)
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        lab2 = QLabel("位置")
        lab2.setProperty("role", "muted")
        lab2.setFixedWidth(56)
        lab2.setAlignment(Qt.AlignRight)
        self.path_edit = QLineEdit(str(default_workspace_root()))
        self.path_edit.setMinimumHeight(32)
        self.path_edit.textChanged.connect(self._update_preview)
        self.name_edit.textChanged.connect(self._update_preview)
        btn_browse = TextButton("浏览…", "folder", theme, "default")
        btn_browse.setFixedHeight(32)
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(lab2)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_browse)
        root.addLayout(path_row)

        self.preview = QLabel("")
        self.preview.setProperty("role", "muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self._update_preview()

        root.addStretch(1)
        root.addWidget(HRule())

        # ---- 按钮 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_quit = TextButton("退出", "", theme, "ghost")
        self.btn_quit.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_quit)
        btn_row.addStretch(1)
        if mode == "welcome" and self._recent:
            self.btn_open = TextButton("打开所选工作空间", "folder", theme, "default")
            self.btn_open.setMinimumHeight(34)
            self.btn_open.clicked.connect(self._open_selected)
            btn_row.addWidget(self.btn_open)
        self.btn_create = TextButton("创建并进入", "spark", theme, "primary")
        self.btn_create.setMinimumHeight(34)
        self.btn_create.clicked.connect(self._create)
        btn_row.addWidget(self.btn_create)
        root.addLayout(btn_row)

        self.btn_create.setDefault(True)

    # ------------------------------------------------------------------ #
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择工作空间所在目录", self.path_edit.text() or str(Path.home()))
        if d:
            self.path_edit.setText(d)

    def _target_dir(self) -> Path:
        base = Path(self.path_edit.text().strip() or str(default_workspace_root()))
        return base

    def _update_preview(self) -> None:
        target = self._target_dir()
        name = self.name_edit.text().strip() or "我的知识库"
        note = ""
        if target.name != name and (target / "novanote.db").exists():
            note = "（该目录已是 NovaNote 工作空间，将直接打开）"
        elif target.exists() and any(target.iterdir()) and not (target / "workspace.json").exists():
            note = "⚠ 该目录非空且不是工作空间，请换一个空目录或新建子目录"
        self.preview.setText(f"数据将保存于：{target}   {note}")

    def _open_selected(self) -> None:
        item = self.recent_box.currentItem()
        if item is None:
            return
        self.result_action = "open"
        self.selected_ws_id = item.data(Qt.UserRole)
        self.accept()

    def _create(self) -> None:
        target = self._target_dir()
        name = self.name_edit.text().strip() or "我的知识库"
        if target.exists() and any(target.iterdir()) and not (target / "workspace.json").exists():
            QMessageBox.warning(self, "目录不可用",
                                f"目录 {target} 非空且不是 NovaNote 工作空间。\n"
                                "请选择一个空目录，或在路径末尾追加一个新的子目录名。")
            return
        self.result_action = "create"
        self.workspace_name = name
        self.workspace_path = str(target)
        self.accept()


# --------------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    changed = Signal()
    openWorkspaceDir = Signal()
    backupRequested = Signal()
    cleanupRequested = Signal()
    switchWorkspaceRequested = Signal()
    deleteWorkspaceRequested = Signal()

    def __init__(self, settings, workspace, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setWindowTitle("NovaNote · 设置")
        self.setMinimumWidth(600)
        self._settings = settings
        self._ws = workspace
        self._theme = theme

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addWidget(_title_row(self))
        root.addWidget(HRule())

        # ---- 外观 ---- #
        sec1 = QLabel("外观与编辑")
        sec1.setProperty("role", "h3")
        root.addWidget(sec1)

        row_theme = QHBoxLayout()
        row_theme.setSpacing(10)
        row_theme.addWidget(_lab("主题"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色（推荐）", "light")
        self.theme_combo.addItem("深色", "dark")
        idx = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.setFixedHeight(30)
        row_theme.addWidget(self.theme_combo, 1)
        root.addLayout(row_theme)

        row_font = QHBoxLayout()
        row_font.setSpacing(10)
        row_font.addWidget(_lab("正文字体"))
        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        for f in ["Sitka Text", "Microsoft YaHei UI", "Source Han Serif SC", "Georgia",
                  "Segoe UI", "KaiTi", "SimSun", "Times New Roman"]:
            self.font_combo.addItem(f)
        self.font_combo.setCurrentText(settings.editor_font)
        self.font_combo.setFixedHeight(30)
        row_font.addWidget(self.font_combo, 1)
        row_font.addWidget(_lab("字号"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(11, 26)
        self.size_spin.setValue(settings.editor_font_size)
        self.size_spin.setFixedHeight(30)
        self.size_spin.setFixedWidth(70)
        row_font.addWidget(self.size_spin)
        root.addLayout(row_font)

        row_save = QHBoxLayout()
        row_save.setSpacing(10)
        row_save.addWidget(_lab("自动保存"))
        self.autosave = QSpinBox()
        self.autosave.setRange(300, 5000)
        self.autosave.setSingleStep(100)
        self.autosave.setSuffix(" ms")
        self.autosave.setValue(settings.autosave_ms)
        self.autosave.setFixedHeight(30)
        self.autosave.setFixedWidth(110)
        row_save.addWidget(self.autosave)
        row_save.addStretch(1)
        self.chk_word = QCheckBox("显示字数统计")
        self.chk_word.setChecked(settings.show_word_count)
        self.chk_confirm = QCheckBox("删除前二次确认")
        self.chk_confirm.setChecked(settings.confirm_delete)
        row_save.addWidget(self.chk_word)
        row_save.addWidget(self.chk_confirm)
        root.addLayout(row_save)

        root.addWidget(HRule())

        # ---- 当前工作空间 ---- #
        sec2 = QLabel("当前工作空间")
        sec2.setProperty("role", "h3")
        root.addWidget(sec2)

        stats = self._ws.stats() if self._ws else {}
        info = Card(self, alt=True, padding=12)
        info.layout().addWidget(_kv("名称", stats.get("name", "—")))
        info.layout().addWidget(_kv("路径", stats.get("path", "—"), selectable=True))
        info.layout().addWidget(_kv(
            "规模",
            f"{stats.get('notes', 0)} 篇笔记 · {stats.get('refs', 0)} 条文献 · "
            f"{stats.get('assets', 0)} 个附件 · 占用 {human_size(stats.get('total_assets_bytes', 0))}",
        ))
        root.addWidget(info)

        ws_btns = QHBoxLayout()
        ws_btns.setSpacing(8)
        for label, icn, sig in (("打开数据目录", "folder", self.openWorkspaceDir),
                                ("立即备份", "save", self.backupRequested),
                                ("切换工作空间", "workspace", self.switchWorkspaceRequested),
                                ("清理未使用文件", "clear", self.cleanupRequested),
                                ("移除该工作空间", "trash", self.deleteWorkspaceRequested)):
            b = TextButton(label, icn, theme, "subtle")
            b.setMinimumHeight(32)
            b.clicked.connect(sig.emit)
            ws_btns.addWidget(b)
        ws_btns.addStretch(1)
        root.addLayout(ws_btns)

        root.addStretch(1)
        root.addWidget(HRule())

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("保存")
        bb.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _accept(self) -> None:
        self._settings.theme = self.theme_combo.currentData()
        self._settings.editor_font = self.font_combo.currentText().strip() or "Sitka Text"
        self._settings.editor_font_size = self.size_spin.value()
        self._settings.autosave_ms = self.autosave.value()
        self._settings.show_word_count = self.chk_word.isChecked()
        self._settings.confirm_delete = self.chk_confirm.isChecked()
        self._settings.save()
        self.changed.emit()
        self.accept()


def _lab(text: str) -> QLabel:
    l = QLabel(text)
    l.setProperty("role", "muted")
    l.setFixedWidth(70)
    l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return l


def _kv(key: str, value: str, selectable: bool = False) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    k = QLabel(key)
    k.setProperty("role", "muted")
    k.setFixedWidth(48)
    k.setAlignment(Qt.AlignRight | Qt.AlignTop)
    v = QLabel(value or "—")
    v.setWordWrap(True)
    if selectable:
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(k, 0, Qt.AlignTop)
    lay.addWidget(v, 1)
    return w


# --------------------------------------------------------------------------- #
class QuickCaptureDialog(QDialog):
    """轻量速记窗口（Ctrl+Enter 保存，Esc 关闭）。"""

    def __init__(self, theme: str = "light", notebooks: list | None = None, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("快速记录")
        self.setFixedWidth(520)
        self._theme = theme

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(22))
        head.addWidget(logo)
        title = QLabel("快速记录")
        title.setProperty("role", "h2")
        head.addWidget(title)
        head.addStretch(1)
        self.nb_combo = QComboBox()
        self.nb_combo.setFixedHeight(28)
        for nb in (notebooks or []):
            self.nb_combo.addItem(nb.name, nb.id)
        head.addWidget(self.nb_combo)
        root.addLayout(head)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("随手记一句… 第一行将作为标题\nCtrl+Enter 保存 · Esc 取消")
        self.editor.setFixedHeight(170)
        root.addWidget(self.editor)

        foot = QHBoxLayout()
        self.hint = QLabel("Ctrl+Enter 保存")
        self.hint.setProperty("role", "muted")
        foot.addWidget(self.hint)
        foot.addStretch(1)
        btn_cancel = TextButton("取消", "", theme, "ghost")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)
        btn_save = TextButton("保存", "check", theme, "primary")
        btn_save.setMinimumHeight(32)
        btn_save.clicked.connect(self.accept)
        foot.addWidget(btn_save)
        root.addLayout(foot)

    def content(self) -> tuple[str, str, int | None]:
        raw = self.editor.toPlainText().strip()
        lines = [l for l in raw.splitlines() if l.strip()]
        title = lines[0][:80] if lines else "速记"
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        return title, body, self.nb_combo.currentData()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class AboutDialog(QDialog):
    def __init__(self, theme: str = "light", stats: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setFixedWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(12)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(64))
        hl.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(3)
        name = QLabel(f"{APP_NAME} {APP_NAME_CN}")
        name.setProperty("role", "display")
        ver = QLabel(f"版本 {APP_VERSION}  ·  本地优先的桌面知识工作台")
        ver.setProperty("role", "muted")
        col.addWidget(name)
        col.addWidget(ver)
        hl.addLayout(col, 1)
        root.addWidget(head)

        desc = QLabel(
            "把日常速记、图文视频素材与学术文献放在同一个安静的工作台里。\n"
            "所有数据保存在你自己的磁盘上，不依赖账号与网络。"
        )
        desc.setWordWrap(True)
        desc.setProperty("role", "secondary")
        root.addWidget(desc)
        root.addWidget(HRule())

        feats = QLabel(
            "•  富文本笔记：标题层级、列表、待办、引用、代码块、表格、高亮\n"
            "•  媒体笔记：拖拽或粘贴图片，视频附件内嵌播放，自动生成缩略图\n"
            "•  学术文献：元数据管理、BibTeX 导入导出、DOI 自动抓取、"
            "APA / GB-T 7714 引用、PDF 全文关联\n"
            "•  组织方式：笔记本 + 标签 + 星标 + 全文检索\n"
            "•  独立工作空间：一个文件夹即一套完整数据，可整体备份与迁移"
        )
        feats.setWordWrap(True)
        root.addWidget(feats)

        if stats:
            root.addWidget(HRule())
            kvs = QLabel(
                f"当前工作空间：{stats.get('name', '—')}\n"
                f"{stats.get('notes', 0)} 篇笔记 · {stats.get('refs', 0)} 条文献 · "
                f"{stats.get('assets', 0)} 个附件 · 占用 {human_size(stats.get('total_assets_bytes', 0))}"
            )
            kvs.setProperty("role", "muted")
            kvs.setWordWrap(True)
            root.addWidget(kvs)

        root.addWidget(HRule())
        tech = QLabel("技术栈：Python · PySide6 (Qt 6) · SQLite  |  界面配色：黛蓝 × 陶橘")
        tech.setProperty("role", "muted")
        root.addWidget(tech)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("关闭")
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        root.addWidget(bb)


# --------------------------------------------------------------------------- #
class NotebookDialog(QDialog):
    """新建 / 编辑笔记本。"""

    def __init__(self, theme: str = "light", name: str = "", icon: str = "folder",
                 color: str = "#3A6E93", title: str = "新建笔记本", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self._theme = theme
        self._icon = icon
        self._color = color

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        head = QLabel(title)
        head.setProperty("role", "h1")
        root.addWidget(head)

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(_lab("名称"))
        self.name_edit = QLineEdit(name)
        self.name_edit.setMinimumHeight(32)
        self.name_edit.setPlaceholderText("例如：算法笔记")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        icon_row = QHBoxLayout()
        icon_row.setSpacing(6)
        icon_row.addWidget(_lab("图标"))
        self.icon_buttons = []
        for icn in ICON_CHOICES:
            b = IconButton(icn, theme, 30, 17, tip=icn)
            b.setCheckable(True)
            b.setChecked(icn == icon)
            b.clicked.connect(lambda _=False, i=icn: self._pick_icon(i))
            icon_row.addWidget(b)
            self.icon_buttons.append((icn, b))
        icon_row.addStretch(1)
        root.addLayout(icon_row)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        color_row.addWidget(_lab("配色"))
        self.color_buttons = []
        for c in COLOR_CHOICES:
            b = QPushButton()
            b.setObjectName("AccentSwatch")
            b.setFixedSize(26, 26)
            b.setCheckable(True)
            b.setChecked(c == color)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton#AccentSwatch {{ background: {c}; border-radius: 8px;"
                f" border: {'2px solid #1D2936' if c == color else '1px solid ' + c}; }}"
            )
            b.clicked.connect(lambda _=False, cc=c: self._pick_color(cc))
            color_row.addWidget(b)
            self.color_buttons.append((c, b))
        color_row.addStretch(1)
        root.addLayout(color_row)

        root.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("确定")
        bb.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _pick_icon(self, icon: str) -> None:
        self._icon = icon
        for icn, b in self.icon_buttons:
            b.setChecked(icn == icon)

    def _pick_color(self, color: str) -> None:
        self._color = color
        for c, b in self.color_buttons:
            sel = c == color
            b.setChecked(sel)
            b.setStyleSheet(
                f"QPushButton#AccentSwatch {{ background: {c}; border-radius: 8px;"
                f" border: {'2px solid #1D2936' if sel else '1px solid ' + c}; }}"
            )

    def values(self) -> tuple[str, str, str]:
        return self.name_edit.text().strip() or "未命名笔记本", self._icon, self._color


class TextPromptDialog(QDialog):
    def __init__(self, title: str, label: str, value: str = "", theme: str = "light", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(400)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)
        head = QLabel(title)
        head.setProperty("role", "h1")
        root.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_lab(label))
        self.edit = QLineEdit(value)
        self.edit.setMinimumHeight(32)
        self.edit.selectAll()
        row.addWidget(self.edit, 1)
        root.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("确定")
        bb.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.edit.returnPressed.connect(self.accept)

    def value(self) -> str:
        return self.edit.text().strip()


class DoiDialog(QDialog):
    """通过 DOI 抓取文献元数据。"""

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setWindowTitle("通过 DOI 添加文献")
        self.setFixedWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        head = QLabel("通过 DOI 抓取元数据")
        head.setProperty("role", "h1")
        root.addWidget(head)

        tip = QLabel("输入 DOI（如 10.1109/TCOMM.2023.1234567），"
                     "NovaNote 会从 Crossref 拉取标题、作者、期刊、摘要等信息。")
        tip.setWordWrap(True)
        tip.setProperty("role", "secondary")
        root.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_lab("DOI"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("10.xxxx/xxxxx 或 https://doi.org/10.xxxx/xxxxx")
        self.edit.setMinimumHeight(32)
        row.addWidget(self.edit, 1)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("抓取并保存")
        bb.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_status(self, text: str) -> None:
        self.status.setText(text)
