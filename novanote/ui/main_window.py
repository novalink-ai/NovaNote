"""主窗口：无边框外壳 + 侧栏 + 上下文面板 + 列表 + 内容区。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSizeGrip,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..config import APP_NAME, APP_NAME_CN, Settings
from ..models import Asset, Note
from ..services.assets import MediaService, human_size, load_pixmap
from ..services.export import export_note_pdf, html_to_markdown, note_to_html_document
from ..services.literature import (
    LiteratureService,
    RefFilter,
    export_bibtex,
    fetch_doi_metadata,
    normalize_doi,
    parse_bibtex,
)
from ..services.notes import NoteFilter, NoteService
from ..services.workspace import WorkspaceRegistry
from ..theme import build_qss, tokens
from ..widgets.common import Toast
from .context_panel import ContextPanel
from .dialogs import (
    AboutDialog,
    DoiDialog,
    NotebookDialog,
    QuickCaptureDialog,
    SettingsDialog,
    TextPromptDialog,
    WorkspaceSetupDialog,
)
from .literature import ReferenceDetail, RefListPane
from .media_viewer import MediaViewer, open_in_system
from .note_editor import NoteEditor
from .note_list import NoteListPane
from .siderail import SideRail
from .titlebar import TitleBar
from .welcome import WelcomeView

RESIZE_MARGIN = 6


class _DoiWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, doi: str, parent=None):
        super().__init__(parent)
        self.doi = doi

    def run(self) -> None:
        try:
            self.done.emit(fetch_doi_metadata(self.doi))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QWidget):
    """顶层窗口（QWidget + 无边框，便于自绘圆角与标题栏）。"""

    def __init__(self, settings: Settings, registry: WorkspaceRegistry):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.settings = settings
        self.registry = registry
        self.ws = registry.current
        if self.ws is None:
            raise RuntimeError("未打开工作空间")

        self.notes = NoteService(self.ws)
        self.lit = LiteratureService(self.ws)
        self.media = MediaService(self.ws)

        self.theme = settings.theme
        self.mode = "notes"
        self.current_note_id: int | None = None
        self.current_ref_id: int | None = None
        self.current_asset_id: int | None = None
        self._thumb_cache: dict[int, QPixmap] = {}
        self._search_text = ""
        self._note_filter_state: dict = {"notebook_id": None, "tag": None, "starred": None,
                                         "trashed": False}
        self._ref_filter = RefFilter()
        self._dirty = False

        self.setWindowTitle(f"{APP_NAME} · {APP_NAME_CN}")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1060, 680)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self._build_ui()
        self._wire()
        self._install_shortcuts()

        self.toast = Toast(self)
        self._restore_geometry()
        self.apply_theme(self.theme, initial=True)
        self.refresh_all(select_first=False)
        self.show_welcome()

    # ================================================================== #
    # 构建界面
    # ================================================================== #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.root = QFrame()
        self.root.setObjectName("Root")
        outer.addWidget(self.root)

        rv = QVBoxLayout(self.root)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.titlebar = TitleBar(self.theme)
        rv.addWidget(self.titlebar)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        self.rail = SideRail(self.theme)
        bl.addWidget(self.rail)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(3)
        self.splitter.setChildrenCollapsible(False)

        self.context = ContextPanel(self.theme)
        self.splitter.addWidget(self.context)

        # 列表区（笔记 / 文献）
        self.list_stack = QStackedWidget()
        self.note_list = NoteListPane(self.theme)
        self.ref_list = RefListPane(self.theme)
        self.list_stack.addWidget(self.note_list)
        self.list_stack.addWidget(self.ref_list)
        self.splitter.addWidget(self.list_stack)

        # 内容区
        self.canvas = QStackedWidget()
        self.canvas.setObjectName("Canvas")
        self.welcome = WelcomeView(self.theme)
        self.editor = NoteEditor(self.theme, self.settings.editor_font,
                                 self.settings.editor_font_size)
        self.editor.body.document().set_resolver(self._resolve_asset_image)
        self.ref_detail = ReferenceDetail(self.theme)
        self.media_viewer = MediaViewer(self.theme)
        for w in (self.welcome, self.editor, self.ref_detail, self.media_viewer):
            self.canvas.addWidget(w)

        canvas_holder = QFrame()
        canvas_holder.setObjectName("Canvas")
        ch = QVBoxLayout(canvas_holder)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.addWidget(self.canvas)
        self.splitter.addWidget(canvas_holder)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([240, 330, 760])

        bl.addWidget(self.splitter, 1)
        rv.addWidget(body, 1)

        # 状态栏
        self.status = QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "muted")
        self.status.addWidget(self.status_label)
        self.right_label = QLabel("")
        self.right_label.setProperty("role", "muted")
        self.status.addPermanentWidget(self.right_label)
        self.grip = QSizeGrip(self.status)
        self.grip.setFixedSize(14, 14)
        self.status.addPermanentWidget(self.grip)
        rv.addWidget(self.status)

    # ================================================================== #
    def _wire(self) -> None:
        tb = self.titlebar
        tb.minimizeRequested.connect(self.showMinimized)
        tb.maximizeRequested.connect(self.toggle_max)
        tb.closeRequested.connect(self.close)
        tb.themeToggled.connect(self.toggle_theme)
        tb.settingsRequested.connect(self.open_settings)
        tb.searchChanged.connect(self.on_search)
        tb.newNoteRequested.connect(self.new_note)
        tb.newRefRequested.connect(self.new_reference)
        tb.quickRequested.connect(self.quick_capture)
        tb.workspaceMenuRequested.connect(self._show_workspace_menu)

        self.rail.modeChanged.connect(self.set_mode)
        self.rail.themeToggled.connect(self.toggle_theme)
        self.rail.settingsRequested.connect(self.open_settings)
        self.rail.aboutRequested.connect(self.open_about)

        cp = self.context
        cp.notebookSelected.connect(self._on_notebook_selected)
        cp.tagSelected.connect(self._on_tag_selected)
        cp.addNotebookRequested.connect(self.new_notebook)
        cp.addTagRequested.connect(self.new_tag)
        cp.notebookContextRequested.connect(self._notebook_context_menu)
        cp.tagContextRequested.connect(self._tag_context_menu)
        cp.literature_panel.filterSelected.connect(self._on_ref_filter)
        cp.literature_panel.tagSelected.connect(self._on_ref_tag_selected)

        nl = self.note_list
        nl.noteSelected.connect(self.load_note)
        nl.noteStarred.connect(self._on_note_starred)
        nl.noteContextRequested.connect(self._note_context_menu)
        nl.newNoteRequested.connect(self.new_note)
        nl.emptyActionRequested.connect(self.new_note)
        nl.sortChanged.connect(self._on_note_sort)

        rl = self.ref_list
        rl.refSelected.connect(self.load_reference)
        rl.refStarred.connect(self._on_ref_starred)
        rl.refContextRequested.connect(self._ref_context_menu)
        rl.newRefRequested.connect(self.new_reference)
        rl.importBibRequested.connect(self.import_bibtex)
        rl.exportBibRequested.connect(lambda: self.export_bibtex())
        rl.doiRequested.connect(self.add_by_doi)
        rl.sortChanged.connect(self._on_ref_sort)

        ed = self.editor
        ed.saveRequested.connect(lambda: self.save_note())
        ed.titleChanged.connect(lambda _t: self._mark_dirty())
        ed.starToggled.connect(self._on_editor_star)
        ed.notebookChanged.connect(self._on_editor_notebook)
        ed.assetActivated.connect(self.open_asset)
        ed.assetRemoved.connect(self.remove_asset)
        ed.assetAdded.connect(self.add_assets_dialog)
        ed.imagePasted.connect(self.paste_image)
        ed.tagsEdited.connect(self._on_editor_tags)
        ed.refLinkRequested.connect(self.link_reference)
        ed.refUnlinkRequested.connect(self._unlink_reference)
        ed.refClicked.connect(self.open_reference_from_note)
        ed.moreActionRequested.connect(self._editor_more_action)
        ed.contentChanged.connect(self._on_content_changed)

        rd = self.ref_detail
        rd.changed.connect(self._on_ref_fields_changed)
        rd.starToggled.connect(self._on_ref_starred)
        rd.readStateChanged.connect(self._on_ref_read_state)
        rd.ratingChanged.connect(self._on_ref_rating)
        rd.deleted.connect(self.delete_reference)
        rd.attachRequested.connect(self.attach_to_reference)
        rd.attachOpened.connect(self.open_ref_attachment)
        rd.attachRemoved.connect(self.remove_ref_attachment)
        rd.createNoteRequested.connect(self.create_note_for_ref)
        rd.openNote.connect(self.open_note_by_id)
        rd.unlinkNote.connect(self._unlink_reference)
        rd.doiLookupRequested.connect(self.fill_reference_by_doi)
        rd.moreActionRequested.connect(self._ref_quick_action)

        mv = self.media_viewer
        mv.closeRequested.connect(self.close_media)
        mv.openExternal.connect(self._open_current_asset_external)
        mv.revealRequested.connect(self._reveal_current_asset)
        mv.deleteRequested.connect(lambda: self.remove_asset(self.current_asset_id or 0))

        self.welcome.newNote.connect(self.new_note)
        self.welcome.newRef.connect(self.new_reference)
        self.welcome.quickCapture.connect(self.quick_capture)
        self.welcome.openNote.connect(self.open_note_by_id)
        self.welcome.openWorkspaceDir.connect(self.open_workspace_dir)
        self.welcome.switchWorkspace.connect(self._switch_workspace_dialog)

    def _install_shortcuts(self) -> None:
        def sc(seq: str, fn) -> None:
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)

        sc("Ctrl+N", self.new_note)
        sc("Ctrl+Shift+N", self.quick_capture)
        sc("Ctrl+S", lambda: self.save_note(force=True))
        sc("Ctrl+K", self.focus_search)
        sc("Ctrl+F", self.focus_search)
        sc("Ctrl+Shift+S", self._toggle_star_current)
        sc("Ctrl+Shift+L", self.new_reference)
        sc("Ctrl+1", lambda: self.rail.select("notes"))
        sc("Ctrl+2", lambda: self.rail.select("literature"))
        sc("Ctrl+3", lambda: self.rail.select("starred"))
        sc("Ctrl+4", lambda: self.rail.select("trash"))
        sc("Ctrl+Shift+T", self.toggle_theme)
        sc("Esc", self._on_escape)

    # ================================================================== #
    # 主题
    # ================================================================== #
    def apply_theme(self, theme: str, initial: bool = False) -> None:
        self.theme = theme
        self.settings.theme = theme
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_qss(theme))
        t = tokens(theme)
        self.root.setStyleSheet(
            f"QFrame#Root {{ background: {t['bg_app']};"
            f" border: 1px solid {t['border_strong']}; border-radius: 12px; }}"
        )
        for w in (self.titlebar, self.rail, self.context, self.note_list, self.ref_list,
                  self.welcome):
            if hasattr(w, "refresh"):
                w.refresh(theme)
        self.titlebar.set_theme_icon(theme)
        self.titlebar.set_maximized(self.isMaximized())
        self.editor.set_theme(theme)
        self.ref_detail.refresh(theme)
        self.media_viewer.refresh(theme)
        if not initial:
            self.settings.save()
        self._update_status()

    def toggle_theme(self) -> None:
        self.apply_theme("dark" if self.theme == "light" else "light")
        self.toast.show_message(
            "已切换到深色主题" if self.theme == "dark" else "已切换到浅色主题",
            self.theme, "info", 1400)

    # ================================================================== #
    # 模式与数据刷新
    # ================================================================== #
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "literature":
            self.context.show_page(1)
            self.list_stack.setCurrentWidget(self.ref_list)
            self.refresh_refs()
            if self.current_ref_id:
                self.load_reference(self.current_ref_id)
            else:
                first = self.ref_list.list.count()
                if first:
                    self.ref_list.refSelected.emit(
                        int(self.ref_list.list.item(0).data(Qt.UserRole)))
        else:
            self.context.show_page(0 if mode == "notes" else 2)
            self.list_stack.setCurrentWidget(self.note_list)
            if mode == "notes":
                self._note_filter_state = {"notebook_id": None, "tag": None,
                                           "starred": None, "trashed": False}
                self.note_list.set_title("全部笔记")
                self.note_list.set_empty_text("note", "这里还没有笔记",
                                              "点击右上角 + 新建一篇，或直接把图片/视频拖进来。")
            elif mode == "starred":
                self._note_filter_state = {"notebook_id": None, "tag": None,
                                           "starred": True, "trashed": False}
                self.note_list.set_title("收藏")
                self.note_list.set_empty_text(
                    "star", "还没有收藏的内容", "在笔记或文献卡片上点击星标即可加入收藏。")
                self.context.simple_panel.set_content(
                    "收藏", "这里汇集所有打了星标的笔记与文献。",
                    "提示：Ctrl+Shift+S 可快速收藏当前笔记。")
            else:
                self._note_filter_state = {"notebook_id": None, "tag": None,
                                           "starred": None, "trashed": True}
                self.note_list.set_title("回收站")
                self.note_list.set_empty_text(
                    "trash", "回收站是空的", "删除的笔记会先放到这里，可随时恢复。")
                self.context.simple_panel.set_content(
                    "回收站", "删除的笔记会暂存在这里，不会立即从磁盘移除。",
                    "右键条目可以「恢复」或「彻底删除」。")
            self.refresh_notes()
            # 切回笔记类视图时，恢复此前编辑的笔记；否则展示列表第一篇
            note = self.notes.get(self.current_note_id) if self.current_note_id else None
            if note and note.is_trashed == (mode == "trash"):
                self.load_note(note.id)
            elif self.note_list.list.count():
                self.load_note(int(self.note_list.list.item(0).data(Qt.UserRole)))
            else:
                self.show_welcome()
        self._update_status()

    def refresh_all(self, select_first: bool = False) -> None:
        self._thumb_cache.clear()
        self._refresh_context_data()
        self.refresh_notes()
        self.refresh_refs()
        self._update_status()
        if select_first and self.note_list.list.count():
            first = self.note_list.list.item(0)
            self.load_note(int(first.data(Qt.UserRole)))

    def _refresh_context_data(self) -> None:
        stats = self.ws.stats()
        notebooks = self.notes.notebooks()
        tags = self.notes.tags()
        self.context.notebook_panel.set_data(notebooks, tags, stats)
        refs = self.lit.list(RefFilter())
        self.context.literature_panel.set_data(
            refs, self.notes.tags(include_refs=False), self.lit.years(),
            self.lit.venues_top(40), stats)

    def refresh_notes(self) -> None:
        st = self._note_filter_state
        flt = NoteFilter(
            notebook_id=st.get("notebook_id"),
            tag=st.get("tag"),
            starred=st.get("starred"),
            trashed=st.get("trashed", False),
            query=self._search_text,
            sort=self._note_sort or "updated_desc",
        )
        notes = self.notes.list(flt)
        thumbs: dict[int, QPixmap] = {}
        if self.note_list._mode == "media":
            # 一次批量取回每篇笔记的首个附件，避免逐篇查询
            for nid, asset in self.notes.first_assets([n.id for n in notes]).items():
                px = self._asset_pixmap(asset, 200)
                if px is not None:
                    thumbs[nid] = px
        self.note_list.set_notes(notes, thumbs)
        if self.current_note_id and self.note_list.list.count():
            self.note_list.set_current(self.current_note_id)

    def refresh_refs(self) -> None:
        flt = RefFilter(
            query=self._search_text,
            tag=self._ref_filter.tag,
            entry_type=self._ref_filter.entry_type,
            year=self._ref_filter.year,
            read_state=self._ref_filter.read_state,
            starred=self._ref_filter.starred,
            has_pdf=self._ref_filter.has_pdf,
            sort=self._ref_sort or "added_desc",
        )
        self._ref_filter_raw = self.lit.list(RefFilter())
        refs = self.lit.list(flt)
        self.ref_list.set_refs(refs)
        if self.current_ref_id and self.ref_list.list.count():
            self.ref_list.set_current(self.current_ref_id)

    def _update_status(self) -> None:
        if not self.ws:
            return
        stats = self.ws.stats()
        self.status_label.setText(
            f"  {stats.get('name', '')}   ·   {stats.get('notes', 0)} 篇笔记   "
            f"{stats.get('refs', 0)} 条文献   {stats.get('assets', 0)} 个附件"
        )
        self.right_label.setText(
            f"{self.ws.path}   ·   {human_size(stats.get('total_assets_bytes', 0))}   "
        )

    # ================================================================== #
    # 笔记
    # ================================================================== #
    _note_sort: str = "updated_desc"
    _ref_sort: str = "added_desc"

    def _on_note_sort(self, key: str) -> None:
        self._note_sort = key
        self.refresh_notes()

    def _on_ref_sort(self, key: str) -> None:
        self._ref_sort = key
        self.refresh_refs()

    def new_note(self, notebook_id=None, kind: str = "text", title: str = "",
                 body_html: str = "") -> Note:
        if notebook_id is None:
            notebook_id = self._note_filter_state.get("notebook_id")
        note = self.notes.create(title=title or "新建笔记", body_html=body_html,
                                 notebook_id=notebook_id, kind=kind)
        if self.mode != "notes":
            self.rail.select("notes")
        self._refresh_context_data()
        self.refresh_notes()
        self.load_note(note.id, focus_title=not bool(title))
        self.toast.show_message("已新建笔记", self.theme, "success", 1400)
        return note

    def load_note(self, note_id: int, focus_title: bool = False) -> None:
        self._flush_pending_save()
        note = self.notes.get(note_id)
        if not note:
            return
        self.current_note_id = note_id
        assets = self.notes.assets(note_id)
        thumbs = {a.id: self._asset_pixmap(a, 180) for a in assets}
        thumbs = {k: v for k, v in thumbs.items() if v is not None}
        linked = []
        for rid in self.notes.linked_refs(note_id):
            ref = self.lit.get(rid)
            if ref:
                linked.append(ref)
        self.editor.load(note, assets, thumbs, self.notes.notebooks(), linked)
        self.canvas.setCurrentWidget(self.editor)
        self.note_list.set_current(note_id)
        self._dirty = False
        if focus_title:
            self.editor.title_edit.setFocus()
            self.editor.title_edit.selectAll()
        self._update_word_count()

    def save_note(self, force: bool = False) -> None:
        if not self.current_note_id:
            return
        data = self.editor.collect()
        self.notes.update(self.current_note_id, **data)
        self._dirty = False
        self.editor.mark_saved()
        if force:
            self._refresh_context_data()
            self._silent_refresh_list()

    def _flush_pending_save(self) -> None:
        if self.current_note_id and self._dirty:
            self.save_note()
        self.ref_detail.flush_now()

    def _silent_refresh_list(self) -> None:
        """刷新列表但尽量保持滚动位置与选中项。"""
        st = self._note_filter_state
        flt = NoteFilter(notebook_id=st.get("notebook_id"), tag=st.get("tag"),
                         starred=st.get("starred"), trashed=st.get("trashed", False),
                         query=self._search_text, sort=self._note_sort)
        notes = self.notes.list(flt)
        list_widget = self.note_list.list
        bar = list_widget.verticalScrollBar().value()
        self.note_list.set_notes(notes, {})
        list_widget.verticalScrollBar().setValue(bar)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _on_content_changed(self) -> None:
        self._dirty = True
        self._update_word_count()

    def _update_word_count(self) -> None:
        if not self.settings.show_word_count:
            return
        text = self.editor.body.toPlainText()
        from ..services.notes import count_words

        n = count_words(text)
        self.editor.saved_label.setText(self.editor.saved_label.text())
        cursor = self.editor.body.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        self.right_label.setText(
            f"第 {line} 行 第 {col} 列   ·   {n} 字   ·   {self.ws.path}   "
        )

    def _on_note_starred(self, note_id: int, value: bool) -> None:
        self.notes.set_starred(note_id, value)
        if self.current_note_id == note_id:
            self.editor.set_starred(value)
        if self.mode == "starred":
            self.refresh_notes()
        else:
            self._silent_refresh_list()
        self._update_status()
        self.toast.show_message("已收藏" if value else "已取消收藏", self.theme, "info", 1100)

    def _on_editor_star(self, value: bool) -> None:
        if self.current_note_id:
            self.notes.set_starred(self.current_note_id, value)
            self.editor.set_starred(value)
            self._silent_refresh_list()

    def _toggle_star_current(self) -> None:
        if self.current_note_id:
            value = not self.editor.star.isChecked()
            self.editor.set_starred(value)
            self._on_editor_star(value)

    def _on_editor_notebook(self, notebook_id) -> None:
        if self.current_note_id:
            self.notes.update(self.current_note_id, notebook_id=notebook_id)
            self._refresh_context_data()
            self._silent_refresh_list()

    def _on_editor_tags(self, tags: list) -> None:
        if self.current_note_id:
            self.notes.set_note_tags(self.current_note_id, tags)
            self._refresh_context_data()
            self._silent_refresh_list()

    def _on_notebook_selected(self, notebook_id) -> None:
        if self.mode != "notes":
            self.rail.select("notes")
            return
        self._note_filter_state["notebook_id"] = notebook_id
        self._note_filter_state["tag"] = None
        nb = self.notes.notebook(notebook_id) if notebook_id else None
        self.note_list.set_title(nb.name if nb else "全部笔记")
        self.refresh_notes()

    def _on_tag_selected(self, tag: str) -> None:
        if self.mode == "literature":
            self._ref_filter.tag = tag
            self.ref_list.set_title(f"标签 #{tag}")
            self.refresh_refs()
            return
        if self.mode != "notes":
            self.rail.select("notes")
        self._note_filter_state["tag"] = tag
        self._note_filter_state["notebook_id"] = None
        self.note_list.set_title(f"标签 #{tag}")
        self.refresh_notes()

    def on_search(self, text: str) -> None:
        self._search_text = (text or "").strip()
        if self.mode == "literature":
            self.ref_list.set_title(f"搜索：{self._search_text}" if self._search_text else "全部文献")
            self.refresh_refs()
        else:
            base = {"notes": "全部笔记", "starred": "收藏", "trash": "回收站"}.get(self.mode, "笔记")
            self.note_list.set_title(
                f"搜索：{self._search_text}" if self._search_text else base)
            self.refresh_notes()

    def focus_search(self) -> None:
        self.titlebar.search.setFocus()
        self.titlebar.search.selectAll()

    # ================================================================== #
    # 笔记右键菜单
    # ================================================================== #
    def _note_context_menu(self, note_id: int, pos: QPoint) -> None:
        note = self.notes.get(note_id)
        if not note:
            return
        menu = QMenu(self)
        trashy = note.is_trashed
        if trashy:
            menu.addAction("恢复笔记", lambda: self._restore_note(note_id))
            menu.addAction("彻底删除", lambda: self._purge_note(note_id))
        else:
            menu.addAction("打开", lambda: self.load_note(note_id))
            menu.addAction("收藏" if not note.is_starred else "取消收藏",
                           lambda: self._on_note_starred(note_id, not note.is_starred))
            menu.addAction("复制笔记", lambda: self._duplicate_note(note_id))
            menu.addSeparator()
            move_menu = menu.addMenu("移动到笔记本")
            for nb in self.notes.notebooks():
                move_menu.addAction(nb.name, lambda _=False, n=nb.id: self._move_note(note_id, n))
            menu.addSeparator()
            menu.addAction("导出为 Markdown", lambda: self._export_note(note_id, "md"))
            menu.addAction("导出为 HTML", lambda: self._export_note(note_id, "html"))
            menu.addAction("导出为 PDF", lambda: self._export_note(note_id, "pdf"))
            menu.addSeparator()
            menu.addAction("移入回收站", lambda: self._trash_note(note_id))
        menu.exec(pos)

    def _trash_note(self, note_id: int) -> None:
        if self.settings.confirm_delete:
            r = QMessageBox.question(self, "移入回收站", "确定要把这篇笔记移入回收站吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self.notes.trash(note_id)
        if self.current_note_id == note_id:
            self.current_note_id = None
            self.show_welcome()
        self._refresh_context_data()
        self.refresh_notes()
        self._update_status()
        self.toast.show_message("已移入回收站", self.theme, "info")

    def _restore_note(self, note_id: int) -> None:
        self.notes.restore(note_id)
        self._refresh_context_data()
        self.refresh_notes()
        self._update_status()
        self.toast.show_message("已恢复", self.theme, "success")

    def _purge_note(self, note_id: int) -> None:
        r = QMessageBox.question(self, "彻底删除",
                                 "该操作不可撤销，笔记及其附件文件将被删除。确定继续吗？",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        rels = self.notes.purge(note_id)
        self.media.delete_asset_files(rels)
        if self.current_note_id == note_id:
            self.current_note_id = None
            self.show_welcome()
        self._refresh_context_data()
        self.refresh_notes()
        self._update_status()

    def _duplicate_note(self, note_id: int) -> None:
        copy = self.notes.duplicate(note_id)
        if copy:
            self._refresh_context_data()
            self.refresh_notes()
            self.load_note(copy.id)
            self.toast.show_message("已复制笔记", self.theme, "success")

    def _move_note(self, note_id: int, notebook_id: int) -> None:
        self.notes.update(note_id, notebook_id=notebook_id)
        self._refresh_context_data()
        self.refresh_notes()

    def open_note_by_id(self, note_id: int) -> None:
        note = self.notes.get(note_id)
        if not note:
            return
        if note.is_trashed:
            self.rail.select("trash")
            return
        if self.mode != "notes":
            self.rail.select("notes")
            self._note_filter_state["tag"] = None
            self._note_filter_state["notebook_id"] = None
            self.note_list.set_title("全部笔记")
            self.refresh_notes()
        self.load_note(note_id)

    # ================================================================== #
    # 附件与媒体
    # ================================================================== #
    def _asset_pixmap(self, asset: Asset, size: int = 160) -> QPixmap | None:
        if asset.id in self._thumb_cache:
            return self._thumb_cache[asset.id]
        rel = asset.thumb_rel_path or asset.rel_path
        if not rel:
            return None
        path = self.media.abs_path(rel)
        if not path.exists():
            return None
        px = load_pixmap(path, size)
        if px.isNull():
            return None
        self._thumb_cache[asset.id] = px
        return px

    def _resolve_asset_image(self, rel: str) -> QImage | None:
        path = self.media.abs_path(rel)
        if path.exists():
            img = QImage(str(path))
            if not img.isNull():
                if img.width() > 1400:
                    img = img.scaledToWidth(1400, Qt.SmoothTransformation)
                return img
        return None

    def add_assets_dialog(self, paths=None) -> None:
        if not self.current_note_id:
            return
        files = list(paths or [])
        if not files:
            files, _ = QFileDialog.getOpenFileNames(
                self, "添加图片 / 视频 / 附件", str(Path.home()),
                "媒体与文档 (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.svg *.mp4 *.mov *.avi "
                "*.mkv *.webm *.m4v *.mp3 *.wav *.m4a *.pdf *.docx *.pptx *.txt);;所有文件 (*)")
        if not files:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._import_files(files)
        finally:
            QApplication.restoreOverrideCursor()

    def _import_files(self, files: list) -> None:
        infos = []
        failed = []
        for f in files:
            try:
                infos.append(self.media.import_file(f))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{Path(f).name}: {e}")
        if not infos:
            self.toast.show_message("导入失败", self.theme, "error")
            return
        first_image = None
        for info in infos:
            asset = self.notes.add_asset(self.current_note_id, info)
            if info["kind"] == "image" and first_image is None:
                first_image = (info["rel_path"], info["width"], info["height"])
        if first_image and self.editor.body.toPlainText().strip() == "":
            self.editor.insert_image(*first_image)
        self._reload_assets()
        self._mark_dirty()
        self.save_note()
        msg = f"已添加 {len(infos)} 个附件"
        if failed:
            msg += f"，{len(failed)} 个失败"
        self.toast.show_message(msg, self.theme, "success" if not failed else "error")

    def paste_image(self, img: QImage) -> None:
        if not self.current_note_id:
            return
        info = self.media.import_qimage(img, "粘贴图片")
        if not info:
            return
        self.notes.add_asset(self.current_note_id, info)
        self.editor.insert_image(info["rel_path"], info["width"], info["height"])
        self._reload_assets()
        self._mark_dirty()
        self.save_note()
        self.toast.show_message("截图已插入", self.theme, "success", 1200)

    def _reload_assets(self) -> None:
        if not self.current_note_id:
            return
        assets = self.notes.assets(self.current_note_id)
        thumbs = {a.id: self._asset_pixmap(a, 180) for a in assets}
        thumbs = {k: v for k, v in thumbs.items() if v is not None}
        self.editor.set_assets(assets, thumbs)

    def _find_asset(self, asset_id: int) -> tuple[Asset | None, str]:
        """在笔记与文献附件中查找，返回 (asset, owner)，owner 为 'note' | 'ref' | ''。"""
        if not asset_id:
            return None, ""
        if self.current_note_id:
            for a in self.notes.assets(self.current_note_id):
                if a.id == asset_id:
                    return a, "note"
        if self.current_ref_id:
            for a in self.lit.attachments(self.current_ref_id):
                if a.id == asset_id:
                    return a, "ref"
        row = self.ws.db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
        if row:
            asset = Asset.from_row(row)
            return asset, ("note" if asset.note_id else ("ref" if asset.ref_id else ""))
        return None, ""

    def open_asset(self, asset_id: int) -> None:
        asset, _owner = self._find_asset(asset_id)
        if asset is None:
            return
        path = self.media.abs_path(asset.rel_path)
        if not path.exists():
            self.toast.show_message("附件文件已丢失", self.theme, "error")
            return
        if asset.kind in ("image", "video"):
            self.current_asset_id = asset.id
            self.media_viewer.show_asset(asset, path)
            self.canvas.setCurrentWidget(self.media_viewer)
            self.media_viewer.setFocus()
        else:
            open_in_system(path)

    def close_media(self) -> None:
        self.media_viewer.close_media()
        self.current_asset_id = None
        if self.canvas.currentWidget() is self.media_viewer:
            if self.mode == "literature" and self.current_ref_id:
                self.canvas.setCurrentWidget(self.ref_detail)
            elif self.current_note_id:
                self.canvas.setCurrentWidget(self.editor)
            else:
                self.show_welcome()

    def remove_asset(self, asset_id: int) -> None:
        if not asset_id:
            return
        r = QMessageBox.question(self, "移除附件", "从笔记中移除该附件？（磁盘文件将一并删除）",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        asset, owner = self._find_asset(asset_id)
        if asset is None:
            return
        if owner == "ref":
            rels = self.lit.detach(asset_id)
            self.media.delete_asset_files(rels)
            if self.current_ref_id:
                self.load_reference(self.current_ref_id)
        else:
            rels = self.notes.delete_asset(asset_id)
            self.media.delete_asset_files(rels)
            if self.current_note_id:
                self._reload_assets()
                self.save_note()
        if self.current_asset_id == asset_id:
            self.close_media()
        self._refresh_context_data()
        self._update_status()

    def _open_current_asset_external(self) -> None:
        asset, _ = self._find_asset(self.current_asset_id or 0)
        if asset is not None:
            open_in_system(self.media.abs_path(asset.rel_path))

    def _reveal_current_asset(self) -> None:
        asset, _ = self._find_asset(self.current_asset_id or 0)
        if asset is None:
            return
        path = self.media.abs_path(asset.rel_path)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception:
            pass

    # ================================================================== #
    # 编辑器更多操作
    # ================================================================== #
    def _editor_more_action(self, key: str) -> None:
        if not self.current_note_id:
            return
        note = self.notes.get(self.current_note_id)
        if not note:
            return
        if key == "copy_citation":
            refs = [self.lit.get(r) for r in self.notes.linked_refs(note.id)]
            refs = [r for r in refs if r]
            text = "\n".join(r.citation_gbt() for r in refs) or "（未关联文献）"
            QGuiApplication.clipboard().setText(text)
            self.toast.show_message("引用已复制到剪贴板", self.theme, "success")
        elif key == "copy_body":
            QGuiApplication.clipboard().setText(self.editor.body.toPlainText())
            self.toast.show_message("正文已复制", self.theme, "success")
        elif key.startswith("export_"):
            self._export_note(note.id, key.split("_", 1)[1])
        elif key == "duplicate":
            self._duplicate_note(note.id)
        elif key == "trash":
            self._trash_note(note.id)

    def _export_note(self, note_id: int, kind: str) -> None:
        note = self.notes.get(note_id)
        if not note:
            return
        if kind == "md":
            content = html_to_markdown(note.body_html, note.title)
            ext, filt = ".md", "Markdown (*.md)"
        elif kind == "html":
            content = note_to_html_document(
                note.title, note.body_html,
                f"更新于 {note.updated_at}  ·  {note.word_count} 字"
                + (f"  ·  {note.notebook_name}" if note.notebook_name else ""),
                self.theme, self.settings.editor_font, self.settings.editor_font_size)
            ext, filt = ".html", "HTML (*.html)"
        else:
            default = self.ws.exports_dir / f"{_safe_filename(note.title)}.pdf"
            path, _ = QFileDialog.getSaveFileName(self, "导出为 PDF", str(default), "PDF (*.pdf)")
            if not path:
                return
            ok = export_note_pdf(path, note.title, note.body_html,
                                 f"更新于 {note.updated_at}  ·  {note.word_count} 字",
                                 self.theme, self.settings.editor_font)
            self.toast.show_message("PDF 已导出" if ok else "PDF 导出失败", self.theme,
                                    "success" if ok else "error")
            return

        default = self.ws.exports_dir / f"{_safe_filename(note.title)}{ext}"
        path, _ = QFileDialog.getSaveFileName(self, "导出笔记", str(default), filt)
        if not path:
            return
        try:
            Path(path).write_text(content, encoding="utf-8")
            self.toast.show_message(f"已导出到 {Path(path).name}", self.theme, "success")
        except OSError as e:
            self.toast.show_message(f"导出失败：{e}", self.theme, "error")

    # ================================================================== #
    # 笔记本 / 标签
    # ================================================================== #
    def new_notebook(self) -> None:
        dlg = NotebookDialog(self.theme, title="新建笔记本", parent=self)
        if dlg.exec() == QDialog.Accepted:
            name, icon, color = dlg.values()
            self.notes.create_notebook(name, icon, color)
            self._refresh_context_data()
            self.toast.show_message(f"已创建笔记本「{name}」", self.theme, "success")

    def _notebook_context_menu(self, notebook_id: int, pos: QPoint) -> None:
        nb = self.notes.notebook(notebook_id)
        if not nb:
            return
        menu = QMenu(self)
        menu.addAction("打开", lambda: self._on_notebook_selected(notebook_id))
        menu.addAction("重命名 / 换图标", lambda: self._edit_notebook(notebook_id))
        menu.addSeparator()
        menu.addAction("清空本笔记本的笔记（移入回收站）",
                       lambda: self._empty_notebook(notebook_id))
        menu.addAction("删除笔记本（笔记移到未分类）",
                       lambda: self._delete_notebook(notebook_id))
        menu.exec(pos)

    def _edit_notebook(self, notebook_id: int) -> None:
        nb = self.notes.notebook(notebook_id)
        if not nb:
            return
        dlg = NotebookDialog(self.theme, nb.name, nb.icon, nb.color, "编辑笔记本", parent=self)
        if dlg.exec() == QDialog.Accepted:
            name, icon, color = dlg.values()
            self.notes.update_notebook(notebook_id, name=name, icon=icon, color=color)
            self._refresh_context_data()
            self.refresh_notes()

    def _empty_notebook(self, notebook_id: int) -> None:
        if QMessageBox.question(self, "清空笔记本", "该笔记本中的笔记将全部移入回收站，确定吗？",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        for n in self.notes.list(NoteFilter(notebook_id=notebook_id)):
            self.notes.trash(n.id)
        self._refresh_context_data()
        self.refresh_notes()

    def _delete_notebook(self, notebook_id: int) -> None:
        if QMessageBox.question(self, "删除笔记本", "笔记本将被删除，其中的笔记会移到「未分类」。",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.notes.delete_notebook(notebook_id)
        self._refresh_context_data()
        self.refresh_notes()
        self._on_notebook_selected(None)

    def new_tag(self) -> None:
        dlg = TextPromptDialog("新建标签", "名称", "", self.theme, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.value():
            self.notes.ensure_tag(dlg.value())
            self._refresh_context_data()
            self.toast.show_message(f"已创建标签 #{dlg.value()}", self.theme, "success")

    def _tag_context_menu(self, tag: str, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("筛选该标签", lambda: self._on_tag_selected(tag))
        menu.addAction("重命名", lambda: self._rename_tag(tag))
        menu.addAction("更换颜色", lambda: self._recolor_tag(tag))
        menu.addSeparator()
        menu.addAction("删除标签", lambda: self._delete_tag(tag))
        menu.exec(pos)

    def _rename_tag(self, tag: str) -> None:
        dlg = TextPromptDialog("重命名标签", "名称", tag, self.theme, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.value():
            row = self.ws.db.query_one("SELECT id FROM tags WHERE name = ?", (tag,))
            if row:
                self.notes.rename_tag(int(row["id"]), dlg.value())
                self._refresh_context_data()

    def _recolor_tag(self, tag: str) -> None:
        from ..services.notes import TAG_PALETTE

        menu = QMenu(self)
        row = self.ws.db.query_one("SELECT id FROM tags WHERE name = ?", (tag,))
        if not row:
            return
        for c in TAG_PALETTE:
            act = menu.addAction(c)
            act.triggered.connect(
                lambda _=False, cc=c: (self.notes.set_tag_color(int(row["id"]), cc),
                                       self._refresh_context_data()))
        menu.exec(QGuiApplication.primaryScreen().cursor().pos())

    def _delete_tag(self, tag: str) -> None:
        row = self.ws.db.query_one("SELECT id FROM tags WHERE name = ?", (tag,))
        if not row:
            return
        self.notes.delete_tag(int(row["id"]))
        self._refresh_context_data()
        self.refresh_notes()

    # ================================================================== #
    # 文献
    # ================================================================== #
    def _new_ref_filter(self) -> RefFilter:
        return RefFilter(query=self._search_text, sort=self._ref_sort)

    def _on_ref_filter(self, key: str, value) -> None:
        f = self._ref_filter
        if key == "all":
            self._ref_filter = RefFilter(query=self._search_text, sort=self._ref_sort)
        elif key == "starred":
            self._ref_filter = RefFilter(query=self._search_text, sort=self._ref_sort, starred=True)
        elif key == "has_pdf":
            self._ref_filter = RefFilter(query=self._search_text, sort=self._ref_sort, has_pdf=True)
        elif key == "read_state":
            self._ref_filter = RefFilter(query=self._search_text, sort=self._ref_sort, read_state=value)
        elif key == "year":
            self._ref_filter = RefFilter(query=self._search_text, sort=self._ref_sort, year=value)
        elif key == "container":
            self._ref_filter = RefFilter(query=value or self._search_text, sort=self._ref_sort)
        labels = {
            "all": "全部文献", "starred": "星标文献", "has_pdf": "含 PDF 全文",
            "read_state": {"未读": "未读", 0: "未读", 1: "在读", 2: "已读"}.get(value, "文献"),
            "year": f"{value} 年", "container": str(value)[:24],
        }
        self.ref_list.set_title(labels.get(key, "文献"))
        self.refresh_refs()

    def _on_ref_tag_selected(self, tag: str) -> None:
        if self.mode != "literature":
            self.rail.select("literature")
        self._ref_filter = RefFilter(query="", sort=self._ref_sort, tag=tag)
        self.ref_list.set_title(f"标签 #{tag}")
        self.refresh_refs()

    def new_reference(self) -> None:
        if self.mode != "literature":
            self.rail.select("literature")
        ref = self.lit.create({"title": "未命名文献", "entry_type": "article"})
        self._refresh_context_data()
        self.refresh_refs()
        self.load_reference(ref.id)
        self.ref_detail.focus_title()
        self.toast.show_message("已新增文献条目，请填写元数据", self.theme, "info", 2200)

    def load_reference(self, ref_id: int) -> None:
        self._flush_pending_save()
        ref = self.lit.get(ref_id)
        if not ref:
            return
        self.current_ref_id = ref_id
        self.ref_detail.load(ref, self.lit.attachments(ref_id), self.notes.notes_for_ref(ref_id))
        self.canvas.setCurrentWidget(self.ref_detail)
        self.ref_list.set_current(ref_id)

    def _on_ref_fields_changed(self, ref_id: int, fields: dict) -> None:
        if not fields:
            return
        if not fields.get("citekey") and any(k in fields for k in ("authors", "year", "title")):
            ref = self.lit.get(ref_id)
            if ref and not ref.citekey:
                from ..services.literature import make_citekey

                fields = dict(fields)
                fields["citekey"] = make_citekey(
                    fields.get("authors", ref.authors), fields.get("year", ref.year),
                    fields.get("title", ref.title))
        self.lit.update(ref_id, fields)
        ref = self.lit.get(ref_id)
        if ref:
            self.ref_detail.cite_apa.setPlainText(ref.citation_apa())
            self.ref_detail.cite_gbt.setPlainText(ref.citation_gbt())
            self.ref_detail.cite_bib.setPlainText(export_bibtex([ref]).strip())
            self.ref_detail.type_pill.setText(ref.type_text)
            self.ref_detail.sub_label.setText(
                f"{ref.authors_short} · {ref.year_text} · {ref.venue_short}")
        self.ref_list.set_current(ref_id)
        self.refresh_refs()
        self._refresh_context_data()

    def _on_ref_starred(self, ref_id: int, value: bool) -> None:
        self.lit.set_starred(ref_id, value)
        self.ref_detail.set_starred(value)
        self.refresh_refs()
        if self._ref_filter.starred:
            self._update_status()

    def _on_ref_read_state(self, ref_id: int, state: int) -> None:
        self.lit.set_read_state(ref_id, state)
        self.ref_detail.set_read_state(state)
        self.refresh_refs()
        self._refresh_context_data()

    def _on_ref_rating(self, ref_id: int, value: int) -> None:
        self.lit.update(ref_id, {"rating": value})
        self.refresh_refs()

    def _ref_context_menu(self, ref_id: int, pos: QPoint) -> None:
        ref = self.lit.get(ref_id)
        if not ref:
            return
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.load_reference(ref_id))
        menu.addAction("复制 APA 引用",
                       lambda: self._copy_text(ref.citation_apa(), "APA 引用"))
        menu.addAction("复制 GB/T 7714 引用",
                       lambda: self._copy_text(ref.citation_gbt(), "GB/T 7714 引用"))
        menu.addAction("复制 BibTeX",
                       lambda: self._copy_text(export_bibtex([ref]).strip(), "BibTeX"))
        menu.addSeparator()
        menu.addAction("据此新建笔记", lambda: self.create_note_for_ref(ref_id))
        menu.addAction("添加 PDF 附件", lambda: self.attach_to_reference(ref_id))
        menu.addAction("用 DOI 补全元数据", lambda: self.fill_reference_by_doi(ref_id))
        menu.addSeparator()
        menu.addAction("导出该条为 BibTeX", lambda: self.export_bibtex([ref_id]))
        menu.addAction("删除条目", lambda: self.delete_reference(ref_id))
        menu.exec(pos)

    def _copy_text(self, text: str, label: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.toast.show_message(f"{label}已复制", self.theme, "success", 1500)

    def _ref_quick_action(self, ref_id: int, key: str) -> None:
        ref = self.lit.get(ref_id)
        if not ref:
            return
        if key == "copy_apa":
            self._copy_text(ref.citation_apa(), "APA 引用")
        elif key == "copy_gbt":
            self._copy_text(ref.citation_gbt(), "GB/T 7714 引用")
        elif key == "copy_bib":
            self._copy_text(export_bibtex([ref]).strip(), "BibTeX")
        elif key == "copy_doi":
            self._copy_text(f"https://doi.org/{ref.doi}" if ref.doi else ref.url, "DOI 链接")
        elif key.startswith("copied:"):
            self.toast.show_message(f"{key.split(':', 1)[1]} 已复制", self.theme, "success", 1400)

    def delete_reference(self, ref_id: int) -> None:
        ref = self.lit.get(ref_id)
        if not ref:
            return
        if self.settings.confirm_delete:
            r = QMessageBox.question(self, "删除文献", f"确定删除「{ref.title[:40]}」？附件文件也会被删除。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        rels = self.lit.delete(ref_id)
        self.media.delete_asset_files(rels)
        if self.current_ref_id == ref_id:
            self.current_ref_id = None
            self.show_welcome()
        self._refresh_context_data()
        self.refresh_refs()
        self._update_status()
        self.toast.show_message("已删除文献条目", self.theme, "info")

    def attach_to_reference(self, ref_id: int) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 PDF / 附件", str(Path.home()),
            "文档 (*.pdf *.epub *.djvu *.docx *.txt *.md *.bib *.ris);;所有文件 (*)")
        if not files:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for f in files:
                try:
                    info = self.media.import_file(f, subdir="refs")
                    kind = "pdf" if Path(f).suffix.lower() == ".pdf" else info["kind"]
                    self.lit.attach(ref_id, info, kind=kind)
                except Exception:
                    continue
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_context_data()
        self.refresh_refs()
        self.load_reference(ref_id)
        self.toast.show_message("附件已添加", self.theme, "success")

    def open_ref_attachment(self, asset_id: int) -> None:
        self.open_asset(asset_id)

    def remove_ref_attachment(self, asset_id: int) -> None:
        rels = self.lit.detach(asset_id)
        self.media.delete_asset_files(rels)
        if self.current_ref_id:
            self.load_reference(self.current_ref_id)
        self._refresh_context_data()

    def create_note_for_ref(self, ref_id: int) -> None:
        ref = self.lit.get(ref_id)
        if not ref:
            return
        note = self.notes.create_note_for_ref(ref)
        self.rail.select("notes")
        self._note_filter_state["notebook_id"] = None
        self._note_filter_state["tag"] = None
        self.note_list.set_title("全部笔记")
        self._refresh_context_data()
        self.refresh_notes()
        self.load_note(note.id)
        self.toast.show_message("已创建文献笔记", self.theme, "success")

    def link_reference(self) -> None:
        if not self.current_note_id:
            return
        linked = set(self.notes.linked_refs(self.current_note_id))
        candidates = [r for r in self.lit.list(RefFilter(query=self.titlebar.search.text().strip()))
                      if r.id not in linked]
        if not candidates:
            self.toast.show_message("没有可关联的文献", self.theme, "info")
            return
        menu = QMenu(self)
        for r in candidates[:40]:
            label = f"{r.authors_short} {r.year_text} — {r.title[:56]}"
            menu.addAction(label, lambda _=False, rid=r.id: self._do_link(rid))
        menu.exec(self.editor.btn_link_ref.mapToGlobal(
            QPoint(0, self.editor.btn_link_ref.height() + 4)))

    def _do_link(self, ref_id: int) -> None:
        if not self.current_note_id:
            return
        self.notes.link_ref(self.current_note_id, ref_id)
        self.load_note(self.current_note_id)
        self.toast.show_message("已关联文献", self.theme, "success")

    def _unlink_reference(self, ref_id: int, note_id: int | None = None) -> None:
        target = note_id or self.current_note_id
        if not target:
            return
        self.notes.unlink_ref(target, ref_id)
        if self.current_note_id == target:
            self.load_note(target)
        if self.current_ref_id == ref_id:
            self.load_reference(ref_id)

    def open_reference_from_note(self, ref_id: int) -> None:
        self.rail.select("literature")
        self.load_reference(ref_id)

    # ---------------- BibTeX / DOI ---------------- #
    def import_bibtex(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 BibTeX / RIS", str(Path.home()),
            "文献数据 (*.bib *.ris *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.toast.show_message(f"读取失败：{e}", self.theme, "error")
            return
        entries = parse_bibtex(text)
        if not entries and Path(path).suffix.lower() == ".ris":
            entries = _parse_ris(text)
        if not entries:
            self.toast.show_message("未解析到有效条目", self.theme, "error")
            return
        count = 0
        for e in entries:
            try:
                tags = [t.strip() for t in (e.get("keywords") or "").replace(";", ",").split(",") if t.strip()][:5]
                self.lit.create(e, tags=tags)
                count += 1
            except Exception:
                continue
        self._refresh_context_data()
        self.refresh_refs()
        self._update_status()
        self.toast.show_message(f"成功导入 {count} 条文献", self.theme, "success", 2600)

    def export_bibtex(self, ref_ids: list[int] | None = None) -> None:
        if ref_ids:
            refs = [r for r in (self.lit.get(i) for i in ref_ids) if r]
        else:
            refs = self.lit.list(RefFilter(query=self._search_text))
        if not refs:
            self.toast.show_message("没有可导出的文献", self.theme, "info")
            return
        default = self.ws.exports_dir / f"references_{time.strftime('%Y%m%d')}.bib"
        path, _ = QFileDialog.getSaveFileName(self, "导出 BibTeX", str(default), "BibTeX (*.bib)")
        if not path:
            return
        try:
            Path(path).write_text(export_bibtex(refs), encoding="utf-8")
            self.toast.show_message(f"已导出 {len(refs)} 条到 {Path(path).name}", self.theme, "success")
        except OSError as e:
            self.toast.show_message(f"导出失败：{e}", self.theme, "error")

    def add_by_doi(self) -> None:
        dlg = DoiDialog(self.theme, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        doi = normalize_doi(dlg.value())
        if not doi:
            return
        self._run_doi(doi, ref_id=None)

    def fill_reference_by_doi(self, ref_id: int) -> None:
        ref = self.lit.get(ref_id)
        if not ref:
            return
        doi = normalize_doi(ref.doi)
        if not doi:
            dlg = DoiDialog(self.theme, parent=self)
            if dlg.exec() != QDialog.Accepted:
                return
            doi = normalize_doi(dlg.value())
            if not doi:
                return
        self._run_doi(doi, ref_id=ref_id)

    def _run_doi(self, doi: str, ref_id: int | None) -> None:
        self.toast.show_message(f"正在从 Crossref 抓取 {doi} …", self.theme, "info", 4000)
        worker = _DoiWorker(doi, self)
        self._doi_worker = worker

        def on_done(data: dict) -> None:
            try:
                if ref_id:
                    self.lit.update(ref_id, {k: v for k, v in data.items()
                                             if k in LiteratureService._FIELDS})
                    self.load_reference(ref_id)
                    msg = "元数据已补全"
                else:
                    ref = self.lit.create(data)
                    self._refresh_context_data()
                    self.refresh_refs()
                    self.load_reference(ref.id)
                    msg = f"已添加《{ref.title[:36]}》"
                self._refresh_context_data()
                self.refresh_refs()
                self.toast.show_message(msg, self.theme, "success", 2600)
            finally:
                worker.deleteLater()

        def on_fail(message: str) -> None:
            self.toast.show_message(f"抓取失败：{message}", self.theme, "error", 3600)
            worker.deleteLater()

        worker.done.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    # ================================================================== #
    # 快速记录 / 欢迎页
    # ================================================================== #
    def quick_capture(self) -> None:
        dlg = QuickCaptureDialog(self.theme, self.notes.notebooks(), self)
        dlg.move(QGuiApplication.primaryScreen().availableGeometry().center()
                 - dlg.rect().center())
        if dlg.exec() != QDialog.Accepted:
            return
        title, body, nb = dlg.content()
        if not title.strip():
            return
        html = "".join(f"<p>{line}</p>" for line in body.splitlines()) if body else ""
        note = self.new_note(notebook_id=nb, title=title, body_html=html)
        self.toast.show_message("已记录", self.theme, "success", 1200)

    def show_welcome(self) -> None:
        stats = self.ws.stats()
        recent = self.notes.timeline(6)
        self.welcome.set_data(self.ws.name, stats, recent)
        self.canvas.setCurrentWidget(self.welcome)

    # ================================================================== #
    # 设置 / 工作空间
    # ================================================================== #
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.ws, self.theme, self)
        dlg.openWorkspaceDir.connect(self.open_workspace_dir)
        dlg.backupRequested.connect(self.backup_workspace)
        dlg.cleanupRequested.connect(self.cleanup_orphans)
        dlg.switchWorkspaceRequested.connect(lambda: (dlg.accept(), self._switch_workspace_dialog()))
        dlg.deleteWorkspaceRequested.connect(lambda: (dlg.accept(), self.remove_workspace()))
        old_theme = self.theme
        old_font = (self.settings.editor_font, self.settings.editor_font_size)
        dlg.changed.connect(lambda: self._apply_settings(old_theme, old_font))
        dlg.exec()

    def _apply_settings(self, old_theme: str, old_font: tuple) -> None:
        if self.settings.editor_font != old_font[0] or \
                self.settings.editor_font_size != old_font[1]:
            self.editor.set_editor_font(self.settings.editor_font, self.settings.editor_font_size)
        if self.settings.theme != self.theme:
            self.apply_theme(self.settings.theme)
        self._update_word_count()
        self.toast.show_message("设置已保存", self.theme, "success", 1400)

    def open_about(self) -> None:
        AboutDialog(self.theme, self.ws.stats(), self).exec()

    def open_workspace_dir(self) -> None:
        open_in_system(self.ws.path)

    def backup_workspace(self) -> None:
        target = QFileDialog.getExistingDirectory(
            self, "选择备份目标目录", str(Path.home()))
        if not target:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = self.ws.export_backup(target)
            QApplication.restoreOverrideCursor()
            self.toast.show_message(f"备份完成：{out.name}", self.theme, "success", 3200)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.toast.show_message(f"备份失败：{e}", self.theme, "error")

    def cleanup_orphans(self) -> None:
        orphans = self.media.orphan_files()
        if not orphans:
            self.toast.show_message("没有发现未使用的文件", self.theme, "info")
            return
        total = sum(p.stat().st_size for p in orphans if p.exists())
        r = QMessageBox.question(
            self, "清理未使用文件",
            f"发现 {len(orphans)} 个未被引用的文件，共 {human_size(total)}。\n"
            f"目录：{self.ws.assets_dir}\n\n确定删除吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.media.delete_asset_files([self.media.rel_of(p) for p in orphans])
        self._refresh_context_data()
        self._update_status()
        self.toast.show_message(f"已清理 {len(orphans)} 个文件", self.theme, "success")

    def _show_workspace_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        head = menu.addAction(f"当前：{self.ws.name}")
        head.setEnabled(False)
        menu.addSeparator()
        for ref in self.registry.recent():
            label = ref.name + ("" if ref.exists() else "（路径失效）")
            act = menu.addAction(label, lambda _=False, r=ref: self._open_workspace(r))
            if not ref.exists():
                act.setEnabled(False)
            act.setCheckable(True)
            act.setChecked(ref.id == self.ws.id)
        menu.addSeparator()
        menu.addAction("新建工作空间…", self._create_workspace_dialog)
        menu.addAction("打开已有文件夹…", self._open_workspace_folder)
        menu.addAction("打开当前数据目录", self.open_workspace_dir)
        menu.exec(pos)

    def _open_workspace(self, ref) -> None:
        if ref.id == self.ws.id:
            return
        try:
            ws = self._switch_workspace_to(ref.path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "无法打开工作空间", str(e))
            return
        if ws:
            self.toast.show_message(f"已切换到「{ws.name}」", self.theme, "success")

    def _switch_workspace_dialog(self) -> None:
        dlg = WorkspaceSetupDialog(self.theme, self.registry.recent(), mode="welcome", parent=self)
        dlg.recent_box.setVisible(True)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.result_action == "open":
            ref = next((r for r in self.registry.recent()
                        if r.id == getattr(dlg, "selected_ws_id", None)), None)
            if ref:
                self._open_workspace(ref)
        elif dlg.result_action == "create":
            try:
                ws = self.registry.create(dlg.workspace_path, dlg.workspace_name)
                self._reload_workspace(ws)
                self.toast.show_message(f"已创建工作空间「{ws.name}」", self.theme, "success")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "创建失败", str(e))

    def _create_workspace_dialog(self) -> None:
        dlg = WorkspaceSetupDialog(self.theme, [], mode="new", parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            ws = self.registry.create(dlg.workspace_path, dlg.workspace_name)
            self._reload_workspace(ws)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "创建失败", str(e))

    def _open_workspace_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择 NovaNote 工作空间目录", str(Path.home()))
        if not d:
            return
        try:
            ws = self._switch_workspace_to(d)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "无法打开", str(e))
            return
        if ws:
            self.toast.show_message(f"已打开「{ws.name}」", self.theme, "success")

    def _switch_workspace_to(self, path: str):
        ws = self.registry.open(path)
        self._reload_workspace(ws)
        return ws

    def _reload_workspace(self, ws) -> None:
        self._flush_pending_save()
        self.ws.close()
        self.ws = ws
        self.registry.current = ws
        self.notes = NoteService(ws)
        self.lit = LiteratureService(ws)
        self.media = MediaService(ws)
        self.editor.body.document().set_resolver(self._resolve_asset_image)
        self.current_note_id = None
        self.current_ref_id = None
        self.current_asset_id = None
        self._thumb_cache.clear()
        self.titlebar.set_workspace(ws.name)
        self._refresh_context_data()
        self.refresh_notes()
        self.refresh_refs()
        self._update_status()
        self.show_welcome()

    def remove_workspace(self) -> None:
        r = QMessageBox.warning(
            self, "移除工作空间",
            f"仅从列表中移除「{self.ws.name}」的记录，磁盘上的数据不会被删除。\n\n继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        ws_id = self.ws.id
        self.registry.forget(ws_id)
        remaining = [w for w in self.registry.recent() if w.exists()]
        if remaining:
            try:
                self._switch_workspace_to(remaining[0].path)
                return
            except Exception:
                pass
        QMessageBox.information(self, "已移除", "没有其他可用的工作空间，程序将退出。")
        self.close()
        QApplication.quit()

    # ================================================================== #
    # 窗口行为
    # ================================================================== #
    def toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, lambda: self.titlebar.set_maximized(self.isMaximized()))

    def _on_escape(self) -> None:
        if self.canvas.currentWidget() is self.media_viewer:
            self.close_media()
        elif self.titlebar.search.text():
            self.titlebar.search.clear()
        elif self.titlebar.search.hasFocus():
            self.editor.focus_body()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edge)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _edge_at(self, pos: QPoint):
        w, h = self.width(), self.height()
        m = RESIZE_MARGIN
        left, right = pos.x() <= m, pos.x() >= w - m
        top, bottom = pos.y() <= m, pos.y() >= h - m
        if top and left:
            return Qt.TopLeftCorner
        if top and right:
            return Qt.TopRightCorner
        if bottom and left:
            return Qt.BottomLeftCorner
        if bottom and right:
            return Qt.BottomRightCorner
        if left:
            return Qt.LeftEdge
        if right:
            return Qt.RightEdge
        if top:
            return Qt.TopEdge
        if bottom:
            return Qt.BottomEdge
        return None

    def _restore_geometry(self) -> None:
        geo = self.settings.window_geometry
        if geo:
            try:
                x, y, w, h = (int(v) for v in geo.split(","))
                if w >= self.minimumWidth() and h >= self.minimumHeight():
                    self.setGeometry(x, y, w, h)
                    return
            except ValueError:
                pass
        screen = QGuiApplication.primaryScreen().availableGeometry()
        w = min(1440, int(screen.width() * 0.82))
        h = min(920, int(screen.height() * 0.84))
        self.resize(w, h)
        self.move(screen.center().x() - w // 2, max(0, screen.center().y() - h // 2 - 20))

    def closeEvent(self, event):  # noqa: N802
        try:
            self._flush_pending_save()
            self.save_note()
            g = self.geometry()
            self.settings.window_geometry = f"{g.x()},{g.y()},{g.width()},{g.height()}"
            self.registry.touch_current()
            self.settings.save()
            self.ws.write_meta()
        except Exception:
            pass
        super().closeEvent(event)

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, lambda: self.titlebar.set_maximized(self.isMaximized()))
        super().changeEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast._reposition()


def _safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join(c for c in (name or "note") if c not in bad).strip()
    return (out or "note")[:60]


def _parse_ris(text: str) -> list[dict]:
    """极简 RIS 解析（兼容 EndNote / Zotero 导出）。"""
    entries: list[dict] = []
    current: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TY  -"):
            current = {"TY": [line[6:].strip()]}
            continue
        if line.startswith("ER  -"):
            if current:
                entries.append(_ris_to_entry(current))
            current = {}
            continue
        if len(line) > 6 and line[:2].isalpha() and line[2:6] == "  -":
            key = line[:2].upper()
            current.setdefault(key, []).append(line[6:].strip())
        elif line and current:
            last_key = list(current.keys())[-1] if current else None
            if last_key:
                current[last_key][-1] += " " + line
    if current:
        entries.append(_ris_to_entry(current))
    return entries


_RIS_TYPES = {
    "JOUR": "article", "CONF": "inproceedings", "CPAPER": "inproceedings",
    "BOOK": "book", "CHAP": "incollection", "THES": "phdthesis", "RPRT": "techreport",
    "ELEC": "misc", "GEN": "misc", "PAT": "patent", "STANDARD": "standard", "DATA": "dataset",
}


def _ris_to_entry(d: dict) -> dict:
    def g(*keys: str) -> str:
        for k in keys:
            v = d.get(k)
            if v:
                return v[0]
        return ""

    year = g("PY", "Y1", "DA")
    import re as _re

    m = _re.search(r"\d{4}", year)
    return {
        "entry_type": _RIS_TYPES.get(g("TY").upper(), "article"),
        "title": g("TI", "T1"),
        "authors": " and ".join(d.get("AU", []) or d.get("A1", [])),
        "year": m.group(0) if m else "",
        "container": g("JO", "JF", "T2", "JA"),
        "publisher": g("PB"),
        "volume": g("VL"),
        "issue": g("IS"),
        "pages": g("SP") + ("-" + g("EP") if g("EP") else ""),
        "doi": g("DO"),
        "url": g("UR"),
        "abstract": g("AB", "N2"),
        "keywords": "; ".join(d.get("KW", [])),
        "language": g("LA"),
        "note": g("N1"),
    }
