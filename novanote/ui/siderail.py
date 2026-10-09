"""左侧导航竖栏（图标 + 文字）。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout

from .. import icons
from ..theme import tokens

MODES = [
    ("notes", "note", "笔记", "全部笔记与素材"),
    ("literature", "book", "文献", "学术文献管理"),
    ("starred", "star", "收藏", "星标内容"),
    ("trash", "trash", "回收", "最近删除"),
]


class RailButton(QToolButton):
    def __init__(self, key: str, icon_name: str, text: str, tip: str,
                 theme: str = "light", parent=None):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._theme = theme
        self.setCheckable(True)
        self.setProperty("rail", "true")
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(21, 21))
        self.setText(text)
        self.setFixedSize(56, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.refresh(theme)

    def refresh(self, theme: str, active: bool | None = None) -> None:
        self._theme = theme
        t = tokens(theme)
        on = self.isChecked() if active is None else active
        color = t["blue"] if on else t["text_secondary"]
        self.setIcon(icons.icon(self._icon_name, color, 21))
        self.setStyleSheet(
            f"QToolButton {{ background: {'transparent' if not on else t['blue_soft']};"
            f" color: {color}; border: none; border-radius: 11px;"
            f" font-size: 11px; font-weight: {'700' if on else '500'}; padding-top: 5px; }}"
            f"QToolButton:hover {{ background: {t['bg_hover']}; color: {t['text']}; }}"
        )


class SideRail(QFrame):
    modeChanged = Signal(str)
    themeToggled = Signal()
    settingsRequested = Signal()
    aboutRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("SideRail")
        self.setFixedWidth(68)
        self._theme = theme
        self._buttons: list[RailButton] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 10, 6, 12)
        lay.setSpacing(6)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, icon_name, text, tip in MODES:
            btn = RailButton(key, icon_name, text, tip, theme)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self.group.addButton(btn)
            lay.addWidget(btn, 0, Qt.AlignHCenter)
            self._buttons.append(btn)

        lay.addStretch(1)

        self.divider = QFrame()
        self.divider.setFixedHeight(1)
        self.divider.setFixedWidth(36)
        lay.addWidget(self.divider, 0, Qt.AlignHCenter)
        lay.addSpacing(4)

        self.btn_theme = RailButton("__theme", "moon", "主题", "切换明暗主题", theme)
        self.btn_theme.setCheckable(False)
        self.btn_theme.clicked.connect(self.themeToggled.emit)
        lay.addWidget(self.btn_theme, 0, Qt.AlignHCenter)

        self.btn_settings = RailButton("__settings", "settings", "设置", "偏好设置", theme)
        self.btn_settings.setCheckable(False)
        self.btn_settings.clicked.connect(self.settingsRequested.emit)
        lay.addWidget(self.btn_settings, 0, Qt.AlignHCenter)

        self.btn_about = RailButton("__about", "spark", "关于", "关于 NovaNote", theme)
        self.btn_about.setCheckable(False)
        self.btn_about.clicked.connect(self.aboutRequested.emit)
        lay.addWidget(self.btn_about, 0, Qt.AlignHCenter)

        self.select("notes", emit=False)
        self.refresh(theme)

    # ------------------------------------------------------------------ #
    def _select(self, key: str) -> None:
        self.select(key, emit=True)

    def select(self, key: str, emit: bool = True) -> None:
        for b in self._buttons:
            b.setChecked(b.key == key)
            b.refresh(self._theme)
        if emit:
            self.modeChanged.emit(key)

    def current_mode(self) -> str:
        for b in self._buttons:
            if b.isChecked():
                return b.key
        return "notes"

    # ------------------------------------------------------------------ #
    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.divider.setStyleSheet(f"background: {t['border']}; border: none;")
        for b in self._buttons:
            b.refresh(theme)
        self.btn_theme._icon_name = "sun" if theme == "dark" else "moon"
        for b in (self.btn_theme, self.btn_settings, self.btn_about):
            b.refresh(theme, active=False)
