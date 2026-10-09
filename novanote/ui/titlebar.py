"""自定义标题栏：品牌标识、工作空间切换、全局搜索、窗口控制。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
)

from .. import icons
from ..config import APP_NAME
from ..theme import tokens
from ..widgets.common import IconButton, SearchBox


class WorkspaceChip(QPushButton):
    """标题栏上的工作空间指示/切换器。"""

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setMinimumHeight(32)
        self.setText("  我的知识库")
        self._refresh_style()

    def _refresh_style(self) -> None:
        t = tokens(self._theme)
        self.setStyleSheet(
            f"QPushButton {{ background: {t['bg_panel']}; border: 1px solid {t['border']};"
            f" border-radius: 9px; padding: 4px 10px; color: {t['text']};"
            f" font-size: 12px; font-weight: 600; text-align: left; }}"
            f"QPushButton:hover {{ background: {t['bg_hover']}; border-color: {t['border_strong']}; }}"
        )

    def refresh(self, theme: str) -> None:
        self._theme = theme
        self._refresh_style()


class TitleBar(QFrame):
    searchChanged = Signal(str)
    newNoteRequested = Signal()
    newRefRequested = Signal()
    quickRequested = Signal(QPoint)
    themeToggled = Signal()
    settingsRequested = Signal()
    workspaceMenuRequested = Signal(QPoint)
    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()
    aboutRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(54)
        self._theme = theme

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)

        # —— 品牌 ——
        self.logo = QLabel()
        self.logo.setFixedSize(28, 28)
        lay.addWidget(self.logo)

        self.brand = QLabel(APP_NAME)
        self.brand.setProperty("role", "brand")
        lay.addWidget(self.brand)

        self.ws_chip = WorkspaceChip(theme)
        self.ws_chip.clicked.connect(self._emit_ws_menu)
        lay.addWidget(self.ws_chip)

        lay.addSpacing(6)

        # —— 快速新建 ——
        self.btn_new = QPushButton("新建")
        self.btn_new.setProperty("variant", "primary")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setIconSize(QSize(16, 16))
        self.btn_new.setMinimumHeight(32)
        self.btn_new.clicked.connect(self._on_new_clicked)
        lay.addWidget(self.btn_new)

        self._new_menu = QMenu(self)
        self._new_menu.addAction("新建笔记", self.newNoteRequested.emit)
        self._new_menu.addAction("添加文献条目", self.newRefRequested.emit)

        lay.addStretch(1)

        # —— 搜索 ——
        # placeholder 保持简短：在 200% 缩放的 1280 逻辑宽度屏幕上，标题栏的
        # 可用空间只够容下约 300px 的搜索框，过长的文案会被裁成"搜索笔记、文献…（Ctrl…"。
        # 快捷键提示改由 tooltip 承载。
        self.search = SearchBox("搜索笔记、文献…", theme)
        self.search.setToolTip("搜索笔记、文献（Ctrl+K）")
        self.search.setMinimumWidth(300)
        self.search.setMaximumWidth(520)
        self.search.textChanged.connect(self.searchChanged.emit)
        lay.addWidget(self.search, 2)

        lay.addStretch(1)

        # —— 功能按钮 ——
        self.btn_quick = IconButton("spark", theme, 32, 18, tip="快速记录（Ctrl+Shift+N）")
        self.btn_quick.clicked.connect(self._emit_quick)
        lay.addWidget(self.btn_quick)

        self.btn_theme = IconButton("moon", theme, 32, 18, tip="切换明暗主题")
        self.btn_theme.clicked.connect(self.themeToggled.emit)
        lay.addWidget(self.btn_theme)

        self.btn_settings = IconButton("settings", theme, 32, 18, tip="设置")
        self.btn_settings.clicked.connect(self.settingsRequested.emit)
        lay.addWidget(self.btn_settings)

        # —— 窗口控制 ——
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        self._sep = sep
        lay.addWidget(sep)
        lay.addSpacing(2)

        self.btn_min = IconButton("minimize", theme, 32, 16, tip="最小化")
        self.btn_min.setProperty("winbtn", "true")
        self.btn_min.clicked.connect(self.minimizeRequested.emit)
        lay.addWidget(self.btn_min)

        self.btn_max = IconButton("maximize", theme, 32, 16, tip="最大化")
        self.btn_max.setProperty("winbtn", "true")
        self.btn_max.clicked.connect(self.maximizeRequested.emit)
        lay.addWidget(self.btn_max)

        self.btn_close = IconButton("close", theme, 32, 16, tip="关闭")
        self.btn_close.setProperty("winbtn", "close")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        lay.addWidget(self.btn_close)

        self.set_workspace("我的知识库")
        self.refresh(theme)

    # ------------------------------------------------------------------ #
    def _emit_ws_menu(self) -> None:
        self.workspaceMenuRequested.emit(self.ws_chip.mapToGlobal(QPoint(0, self.ws_chip.height() + 4)))

    def _emit_quick(self) -> None:
        self.quickRequested.emit(self.btn_quick.mapToGlobal(QPoint(0, self.btn_quick.height() + 4)))

    def _on_new_clicked(self) -> None:
        self._new_menu.setMinimumWidth(190)
        self._new_menu.exec(self.btn_new.mapToGlobal(QPoint(0, self.btn_new.height() + 4)))

    # ------------------------------------------------------------------ #
    def set_workspace(self, name: str) -> None:
        self.ws_chip.setText(f"  {name}")
        px: QPixmap = icons.logo_pixmap(18)
        self.ws_chip.setIcon(px)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.logo.setPixmap(icons.logo_pixmap(28))
        self._sep.setStyleSheet(f"background: {t['border_strong']}; border: none;")
        self.ws_chip.refresh(theme)
        for b in (self.btn_quick, self.btn_theme, self.btn_settings,
                  self.btn_min, self.btn_max, self.btn_close):
            b.refresh(theme)
        self.search.refresh(theme)
        self.btn_new.setIcon(icons.icon("plus", t["text_invert"], 16))
        self.btn_quick.setToolTip("快速记录（Ctrl+Shift+N）")

    def set_theme_icon(self, theme: str) -> None:
        self.btn_theme._name = "sun" if theme == "dark" else "moon"
        self.btn_theme.refresh(theme)

    def set_maximized(self, value: bool) -> None:
        self.btn_max._name = "restore" if value else "maximize"
        self.btn_max.refresh(self._theme)

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):  # noqa: N802
        # 空白区域拖动窗口
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.maximizeRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
