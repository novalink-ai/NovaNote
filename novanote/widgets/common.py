"""通用 UI 组件库：按钮、卡片、空状态、标签片、评分、提示气泡等。"""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import tokens

__all__ = [
    "IconButton", "TextButton", "Card", "SectionLabel", "HRule", "VRule",
    "SearchBox", "Pill", "TagChip", "StarButton", "StarRating", "EmptyState",
    "Toast", "Badge", "Avatar", "apply_shadow", "elide", "MetaRow", "KeyValue",
]


# --------------------------------------------------------------------------- #
# 按钮
# --------------------------------------------------------------------------- #
class IconButton(QToolButton):
    """统一风格的图标按钮。"""

    def __init__(self, name: str, theme: str = "light", size: int = 22,
                 icon_size: int = 18, color: str | None = None, tip: str = "", parent=None):
        super().__init__(parent)
        self._name = name
        self._size = size
        self._icon_size = icon_size
        self._theme = theme
        self._color = color
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.PointingHandCursor)
        if tip:
            self.setToolTip(tip)
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        color = self._color or t["text_secondary"]
        self.setIcon(icons.icon(self._name, color, self._icon_size))

    def set_color(self, color: str) -> None:
        self._color = color
        self.refresh(self._theme)


class TextButton(QPushButton):
    def __init__(self, text: str, icon_name: str = "", theme: str = "light",
                 variant: str = "default", icon_size: int = 17, parent=None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._theme = theme
        self._icon_size = icon_size
        self.setProperty("variant", variant)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        if not self._icon_name:
            return
        t = tokens(theme)
        color = {
            "primary": t["text_invert"],
            "accent": "#FFFFFF",
            "danger": "#FFFFFF",
        }.get(self.property("variant"), t["text_secondary"])
        self.setIcon(icons.icon(self._icon_name, color, self._icon_size))


# --------------------------------------------------------------------------- #
# 容器
# --------------------------------------------------------------------------- #
class Card(QFrame):
    def __init__(self, parent=None, alt: bool = False, padding: int = 14, spacing: int = 10,
                 vertical: bool = True):
        super().__init__(parent)
        self.setObjectName("CardAlt" if alt else "Card")
        lay = (QVBoxLayout if vertical else QHBoxLayout)(self)
        lay.setContentsMargins(padding, padding, padding, padding)
        lay.setSpacing(spacing)
        self._lay = lay

    def layout(self):  # type: ignore[override]
        return self._lay


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper() if text.isascii() else text, parent)
        self.setProperty("role", "overline")


class HRule(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class VRule(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VDivider")
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)


def rgba(color: str | QColor, alpha: int) -> str:
    """生成 Qt 样式表可用的 rgba(...) 字面量（alpha: 0-255）。"""
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _tint(color: str, theme: str) -> tuple[str, str]:
    """返回 (背景, 前景)：浅色主题下用淡色底 + 深色字。"""
    c = QColor(color)
    if theme == "light":
        return rgba(c, 30), c.darker(122).name()
    return rgba(c, 58), c.lighter(132).name()


class Pill(QLabel):
    """小圆角标签。"""

    def __init__(self, text: str, color: str = "#3A6E93", theme: str = "light",
                 filled: bool = False, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_colors(color, theme, filled)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_colors(self, color: str, theme: str, filled: bool = False) -> None:
        c = QColor(color)
        if filled:
            bg, fg = c.name(), "#FFFFFF"
        else:
            bg, fg = _tint(color, theme)
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: 7px;"
            f" padding: 2px 8px; font-size: 11px; font-weight: 600; }}"
        )


class TagChip(QPushButton):
    """可点击的标签片（右键移除）。"""

    clickedTag = Signal(str)
    removed = Signal(str)

    def __init__(self, text: str, color: str = "#D0854C", theme: str = "light",
                 removable: bool = False, parent=None):
        super().__init__(parent)
        self._text = text
        self._theme = theme
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.set_colors(color, theme)
        if removable:
            self.setToolTip("右键移除该标签")
        self.clicked.connect(lambda: self.clickedTag.emit(self._text))

    def contextMenuEvent(self, event):  # noqa: N802
        if self.toolTip():
            self.removed.emit(self._text)
        event.accept()

    def set_colors(self, color: str, theme: str) -> None:
        self._color = color
        self._theme = theme
        c = QColor(color)
        bg, fg = _tint(color, theme)
        self.setText(f"# {self._text}")
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none;"
            f" border-radius: 8px; padding: 3px 9px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c.name()}; color: #FFFFFF; }}"
        )


class Badge(QLabel):
    def __init__(self, text: str, theme: str = "light", color: str = "", parent=None):
        super().__init__(text, parent)
        t = tokens(theme)
        c = color or t["text_muted"]
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{ color: {c}; font-size: 11px; font-weight: 700;"
            f" background: transparent; padding: 0 4px; }}"
        )


# --------------------------------------------------------------------------- #
# 星标 / 评分
# --------------------------------------------------------------------------- #
class StarButton(QToolButton):
    toggledStar = Signal(bool)

    def __init__(self, checked: bool = False, theme: str = "light", size: int = 24, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._checked = checked
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(size - 6, size - 6))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("收藏 / 取消收藏")
        self.refresh(theme)
        self.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        self._checked = self.isChecked()
        self.refresh(self._theme)
        self.toggledStar.emit(self._checked)

    def set_checked_silent(self, value: bool) -> None:
        self._checked = value
        self.setChecked(value)
        self.refresh(self._theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        if self._checked:
            self.setIcon(icons.icon("star_fill", t["orange"], self.width() - 6))
        else:
            self.setIcon(icons.icon("star", t["text_muted"], self.width() - 6))


class StarRating(QWidget):
    ratingChanged = Signal(int)

    def __init__(self, rating: int = 0, theme: str = "light", star: int = 18, parent=None):
        super().__init__(parent)
        self._rating = max(0, min(5, rating))
        self._hover = 0
        self._theme = theme
        self._star = star
        self.setFixedHeight(star + 4)
        self.setMinimumWidth(star * 5 + 16)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip("点击设置重要程度，再次点击同一颗星可清零")

    def set_rating(self, value: int) -> None:
        self._rating = max(0, min(5, value))
        self.update()

    def rating(self) -> int:
        return self._rating

    def mouseMoveEvent(self, event):  # noqa: N802
        idx = self._index_at(event.position().x())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = 0
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        idx = self._index_at(event.position().x())
        new = 0 if idx == self._rating else idx
        self._rating = new
        self.update()
        self.ratingChanged.emit(new)

    def _index_at(self, x: float) -> int:
        pad = 2
        idx = int((x - pad) // self._star) + 1
        return max(0, min(5, idx))

    def paintEvent(self, event):  # noqa: N802
        t = tokens(self._theme)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        active = self._hover or self._rating
        for i in range(5):
            filled = i < active
            ic = icons.icon(
                "star_fill" if filled else "star",
                t["orange"] if filled else t["border_strong"],
                self._star - 2,
            )
            ic.paint(p, i * self._star + 2, 2, self._star - 2, self._star - 2)
        p.end()


# --------------------------------------------------------------------------- #
# 搜索框
# --------------------------------------------------------------------------- #
class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "搜索…", theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._search_action = None
        self.setProperty("search", "true")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(34)
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        icon = icons.icon("search", t["text_muted"], 16)
        # 注意：QLineEdit.addAction() 是**追加**语义，不做去重。
        # 每次切换主题都会调用 refresh()，若无条件 addAction 就会在输入框左侧
        # 不断堆积放大镜（实测启动路径上 refresh 被调用 4 次 → 4 个图标）。
        # 因此只在首次创建 action，之后仅更新其图标。
        if self._search_action is None:
            self._search_action = self.addAction(icon, QLineEdit.LeadingPosition)
        else:
            self._search_action.setIcon(icon)


# --------------------------------------------------------------------------- #
# 空状态
# --------------------------------------------------------------------------- #
class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, subtitle: str = "",
                 theme: str = "light", action_text: str = "", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._icon_name = icon_name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(8)
        lay.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setProperty("role", "h2")
        lay.addWidget(self.title_label)

        self.sub_label = QLabel(subtitle)
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setProperty("role", "muted")
        self.sub_label.setWordWrap(True)
        self.sub_label.setVisible(bool(subtitle))
        lay.addWidget(self.sub_label)

        self.action = TextButton(action_text, "plus", theme, "default")
        self.action.setVisible(bool(action_text))
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(self.action)
        wrap.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(wrap)
        lay.addStretch(1)
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        px = icons.render_pixmap(self._icon_name, t["border_strong"], 52)
        self.icon_label.setPixmap(px)

    def set_texts(self, title: str, subtitle: str = "", icon_name: str = "") -> None:
        self.title_label.setText(title)
        self.sub_label.setText(subtitle)
        self.sub_label.setVisible(bool(subtitle))
        if icon_name:
            self._icon_name = icon_name
            self.refresh(self._theme)


# --------------------------------------------------------------------------- #
# 悬浮提示
# --------------------------------------------------------------------------- #
class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAlignment(Qt.AlignCenter)
        self.setVisible(False)
        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_message(self, text: str, theme: str = "light", kind: str = "info", msec: int = 2200) -> None:
        t = tokens(theme)
        accent = {"info": t["blue"], "error": t["danger"], "success": t["success"]}.get(kind, t["blue"])
        self.setStyleSheet(
            f"QLabel {{ background: {t['bg_surface']}; color: {t['text']};"
            f" border: 1px solid {t['border_strong']}; border-left: 3px solid {accent};"
            f" border-radius: 9px; padding: 9px 16px; font-size: 12px; font-weight: 600; }}"
        )
        self.setText(text)
        self.adjustSize()
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self.setWindowOpacity(1.0)
        self._timer.start(msec)

    def _reposition(self) -> None:
        p = self.parentWidget()
        if not p:
            return
        x = (p.width() - self.width()) // 2
        y = p.height() - self.height() - 34
        self.move(max(10, x), max(10, y))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._reposition()

    def _fade_out(self) -> None:
        self.setVisible(False)


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def apply_shadow(widget: QWidget, blur: int = 22, dy: int = 4, alpha: int = 26) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(20, 30, 45, alpha))
    widget.setGraphicsEffect(eff)


def elide(text: str, width: int, font: QFont | None = None, mode=Qt.ElideRight) -> str:
    from PySide6.QtGui import QFontMetrics

    if not text:
        return ""
    fm = QFontMetrics(font) if font else QFontMetrics(QFont())
    return fm.elidedText(text, mode, max(20, width))


class Avatar(QWidget):
    """首字母头像（用于作者、工作空间标识）。"""

    def __init__(self, text: str = "N", color: str = "#3A6E93", size: int = 36, parent=None):
        super().__init__(parent)
        self._text = (text or "N")[:1].upper()
        self._color = color
        self._size = size
        self.setFixedSize(size, size)

    def set_data(self, text: str, color: str) -> None:
        self._text = (text or "N")[:1].upper()
        self._color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        r = self._size / 2
        path.addRoundedRect(0, 0, self._size, self._size, r * 0.42, r * 0.42)
        p.fillPath(path, QColor(self._color))
        p.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, self._size * 0.42))
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class MetaRow(QWidget):
    """「图标 + 文本」的元信息行。"""

    def __init__(self, icon_name: str, text: str = "", theme: str = "light", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.icon = QLabel()
        self.icon.setFixedSize(15, 15)
        self.label = QLabel(text)
        self.label.setProperty("role", "muted")
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        t = tokens(theme)
        self.icon.setPixmap(icons.render_pixmap(self._icon_name, t["text_muted"], 15))

    def set_icon(self, name: str, theme: str) -> None:
        self._icon_name = name
        self.refresh(theme)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


class KeyValue(QWidget):
    """表单只读展示行：左标签右值。"""

    def __init__(self, key: str, value: str = "—", theme: str = "light", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.k = QLabel(key)
        self.k.setProperty("role", "muted")
        self.k.setFixedWidth(64)
        self.v = QLabel(value or "—")
        self.v.setWordWrap(True)
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.k, 0, Qt.AlignTop)
        lay.addWidget(self.v, 1)

    def set_value(self, value: str) -> None:
        self.v.setText(value or "—")
