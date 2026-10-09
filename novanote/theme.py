"""橘蓝低饱和主题系统。

设计原则
  * 品牌双色：黛蓝（结构 / 主操作） + 陶橘（强调 / 灵感 / 星标）
  * 低饱和：所有色相饱和度控制在 25%~45%，避免"刺眼"
  * 单一数据源：全部颜色集中在 TOKENS，QSS 由 build_qss() 生成
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 设计令牌
# --------------------------------------------------------------------------- #
LIGHT = {
    "bg_app": "#F2F5F9",
    "bg_surface": "#FFFFFF",
    "bg_panel": "#EAEFF6",
    "bg_sunken": "#E3E9F1",
    "bg_hover": "#E6EDF4",
    "bg_active": "#DCE7F1",
    "border": "#DCE4ED",
    "border_strong": "#C4D0DD",
    "text": "#1D2936",
    "text_secondary": "#56687A",
    "text_muted": "#8B9AAB",
    "text_invert": "#FFFFFF",
    "blue": "#3A6E93",
    "blue_hover": "#4781AA",
    "blue_press": "#2E5A7A",
    "blue_soft": "#E2EDF5",
    "orange": "#D0854C",
    "orange_hover": "#DE9560",
    "orange_press": "#B5713C",
    "orange_soft": "#FAEDE0",
    "danger": "#BE5A50",
    "danger_soft": "#FAE9E7",
    "success": "#57896A",
    "warning": "#C79A3F",
    "shadow": "rgba(29, 41, 54, 0.10)",
    "editor_bg": "#FFFFFF",
    "selection": "#CADFF0",
}

DARK = {
    "bg_app": "#161A20",
    "bg_surface": "#1D232B",
    "bg_panel": "#191E25",
    "bg_sunken": "#13171C",
    "bg_hover": "#262E38",
    "bg_active": "#2E3945",
    "border": "#2B333D",
    "border_strong": "#3A4553",
    "text": "#E7ECF2",
    "text_secondary": "#A6B3C1",
    "text_muted": "#75838F",
    "text_invert": "#12161B",
    "blue": "#5C93BA",
    "blue_hover": "#6DA4C9",
    "blue_press": "#4C7E9F",
    "blue_soft": "#22303C",
    "orange": "#D9925C",
    "orange_hover": "#E5A271",
    "orange_press": "#BC7A4A",
    "orange_soft": "#35281D",
    "danger": "#D07068",
    "danger_soft": "#3A2523",
    "success": "#6FA37F",
    "warning": "#D3AC5C",
    "shadow": "rgba(0, 0, 0, 0.35)",
    "editor_bg": "#1D232B",
    "selection": "#31465A",
}


@dataclass
class Fonts:
    ui: str = "Microsoft YaHei UI"
    ui_fallback: str = "Segoe UI"
    mono: str = "Cascadia Mono"
    serif_body: str = "Sitka Text"


# 可用字体探测（在 main 启动时调用一次）
_resolved: dict[str, str] = {}


def resolve_font(preferred: str, fallbacks: list[str], mono: bool = False) -> str:
    if preferred in _resolved:
        return _resolved[preferred]
    try:
        from PySide6.QtGui import QFontDatabase

        families = set(QFontDatabase.families())
        for cand in [preferred, *fallbacks]:
            if cand in families:
                _resolved[preferred] = cand
                return cand
        _resolved[preferred] = "monospace" if mono else "sans-serif"
    except Exception:
        _resolved[preferred] = fallbacks[0] if fallbacks else "sans-serif"
    return _resolved[preferred]


def tokens(theme: str = "light") -> dict:
    return DARK if theme == "dark" else LIGHT


# --------------------------------------------------------------------------- #
# QSS
# --------------------------------------------------------------------------- #
def build_qss(theme: str = "light") -> str:
    t = tokens(theme)
    ui = resolve_font(Fonts.ui, [Fonts.ui_fallback, "Segoe UI", "PingFang SC", "sans-serif"])
    mono = resolve_font(Fonts.mono, ["Consolas", "monospace"], mono=True)

    return f"""
/* ================= 全局 ================= */
* {{
    outline: none;
}}
QWidget {{
    color: {t['text']};
    font-family: "{ui}";
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {t['bg_app']};
}}
QToolTip {{
    background: {t['bg_surface']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12px;
}}

/* ================= 卡片 / 容器 ================= */
QFrame#Root {{
    background: {t['bg_app']};
    border: 1px solid {t['border_strong']};
    border-radius: 12px;
}}
QFrame#TitleBar {{
    background: {t['bg_app']};
    border: none;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QFrame#SideRail {{
    background: {t['bg_panel']};
    border: none;
    border-right: 1px solid {t['border']};
    border-bottom-left-radius: 12px;
}}
QFrame#Panel {{
    background: {t['bg_panel']};
    border: none;
    border-right: 1px solid {t['border']};
}}
QFrame#Canvas {{
    background: {t['bg_surface']};
    border: none;
    border-bottom-right-radius: 12px;
}}
QFrame#Card {{
    background: {t['bg_surface']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}
QFrame#CardAlt {{
    background: {t['bg_panel']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}

/* —— 笔记列表卡片 ——
   选中态用动态属性 sel 驱动，QSS 里一条规则搞定。
   注意：不要在卡片构造 / 选中时调用 QWidget.setStyleSheet()——那会让 Qt 为
   整棵子树重新解析并级联样式（实测单卡约 20ms），列表滚动时会明显卡顿。 */
QWidget#NoteCard, QWidget#MediaCard, QWidget#RefCard {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}}
QWidget#NoteCard[sel="true"], QWidget#MediaCard[sel="true"], QWidget#RefCard[sel="true"] {{
    background: {t['blue_soft']};
    border: 1px solid {t['blue']};
}}
QWidget#NoteCard QLabel, QWidget#NoteCard QToolButton,
QWidget#MediaCard QLabel, QWidget#MediaCard QToolButton,
QWidget#RefCard QLabel, QWidget#RefCard QToolButton {{
    background: transparent;
}}
QLabel#MediaHolder {{
    background: {t['bg_panel']};
    border-radius: 8px;
}}
QLabel[role="cardTitle"]   {{ font-size: 13.5px; font-weight: 700; }}
QLabel[role="cardTitleSm"] {{ font-size: 12px;   font-weight: 600; }}
QFrame#Divider {{
    background: {t['border']};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame#VDivider {{
    background: {t['border']};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}
QFrame#HeroBand {{
    border: none;
    border-radius: 14px;
    background: {t['blue_soft']};
}}

/* ================= 文字层级 ================= */
QLabel[role="display"] {{ font-size: 25px; font-weight: 700; letter-spacing: 0.4px; }}
QLabel[role="h1"]      {{ font-size: 19px; font-weight: 700; }}
QLabel[role="h2"]      {{ font-size: 15px; font-weight: 600; }}
QLabel[role="h3"]      {{ font-size: 13px; font-weight: 600; }}
QLabel[role="body"]    {{ font-size: 13px; }}
QLabel[role="muted"]   {{ font-size: 12px; color: {t['text_muted']}; }}
QLabel[role="secondary"] {{ font-size: 12px; color: {t['text_secondary']}; }}
QLabel[role="overline"] {{
    font-size: 11px; font-weight: 700; letter-spacing: 1.4px;
    color: {t['text_muted']};
}}
QLabel[role="brand"] {{ font-size: 16px; font-weight: 700; letter-spacing: 0.6px; }}
QLabel[accent="orange"] {{ color: {t['orange']}; }}
QLabel[accent="blue"]   {{ color: {t['blue']}; }}

/* ================= 按钮 ================= */
QPushButton {{
    background: {t['bg_surface']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
}}
QPushButton:hover  {{ background: {t['bg_hover']}; }}
QPushButton:pressed {{ background: {t['bg_active']}; }}
QPushButton:disabled {{ color: {t['text_muted']}; border-color: {t['border']}; background: {t['bg_panel']}; }}

QPushButton[variant="primary"] {{
    background: {t['blue']}; color: {t['text_invert']}; border: 1px solid {t['blue']};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover   {{ background: {t['blue_hover']}; border-color: {t['blue_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {t['blue_press']}; }}

QPushButton[variant="accent"] {{
    background: {t['orange']}; color: #FFFFFF; border: 1px solid {t['orange']};
    font-weight: 600;
}}
QPushButton[variant="accent"]:hover   {{ background: {t['orange_hover']}; border-color: {t['orange_hover']}; }}
QPushButton[variant="accent"]:pressed {{ background: {t['orange_press']}; }}

QPushButton[variant="danger"] {{
    background: {t['danger']}; color: #FFFFFF; border: 1px solid {t['danger']};
}}
QPushButton[variant="danger"]:hover {{ background: {t['danger']}; }}

QPushButton[variant="ghost"] {{
    background: transparent; border: 1px solid transparent; color: {t['text_secondary']};
}}
QPushButton[variant="ghost"]:hover {{ background: {t['bg_hover']}; color: {t['text']}; }}

QPushButton[variant="subtle"] {{
    background: {t['bg_panel']}; border: 1px solid transparent; color: {t['text_secondary']};
}}
QPushButton[variant="subtle"]:hover {{ background: {t['bg_hover']}; color: {t['text']}; }}

/* ================= 工具按钮 ================= */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px;
}}
QToolButton:hover   {{ background: {t['bg_hover']}; }}
QToolButton:pressed {{ background: {t['bg_active']}; }}
QToolButton:checked {{ background: {t['blue_soft']}; border-color: {t['blue']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QToolButton[rail="true"] {{
    border-radius: 10px;
    padding: 0px;
}}
QToolButton[rail="true"]:checked {{ background: {t['blue_soft']}; }}

QToolButton[winbtn="true"] {{
    border-radius: 6px; padding: 0px;
}}
QToolButton[winbtn="close"]:hover {{ background: {t['danger']}; }}

/* ================= 输入框 ================= */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background: {t['bg_surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {t['selection']};
    selection-color: {t['text']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDateEdit:focus {{
    border: 1px solid {t['blue']};
    background: {t['bg_surface']};
}}
QLineEdit[search="true"] {{
    background: {t['bg_sunken']};
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 6px 12px;
}}
QLineEdit[search="true"]:focus {{
    background: {t['bg_surface']};
    border: 1px solid {t['blue']};
}}
QLineEdit#TitleEdit {{
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0px;
    font-size: 27px;
    font-weight: 700;
    color: {t['text']};
}}

/* ================= 列表 ================= */
QListWidget, QListView {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    border-radius: 9px;
    padding: 0px;
    margin: 2px 6px;
}}
QListWidget::item:hover    {{ background: {t['bg_hover']}; }}
QListWidget::item:selected {{ background: {t['blue_soft']}; color: {t['text']}; }}

QTreeWidget, QTreeView {{
    background: transparent;
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}
QTreeWidget::item {{
    padding: 6px 4px;
    border-radius: 8px;
    margin: 1px 4px;
}}
QTreeWidget::item:hover    {{ background: {t['bg_hover']}; }}
QTreeWidget::item:selected {{ background: {t['blue_soft']}; color: {t['text']}; }}
QTreeWidget::branch {{ background: transparent; }}

/* ================= 滚动条 ================= */
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 4px 3px 4px 0px;
}}
QScrollBar::handle:vertical {{
    background: {t['border_strong']}; border-radius: 4px; min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['text_muted']}; }}
QScrollBar:horizontal {{
    background: transparent; height: 11px; margin: 0px 4px 3px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border_strong']}; border-radius: 4px; min-width: 36px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['text_muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ================= 下拉 / 菜单 ================= */
QComboBox {{
    background: {t['bg_surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {t['blue']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t['bg_surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {t['blue_soft']};
    selection-color: {t['text']};
    outline: none;
}}

QMenu {{
    background: {t['bg_surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 9px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 6px;
    color: {t['text']};
}}
QMenu::item:selected {{ background: {t['blue_soft']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}

/* ================= 选项卡 ================= */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {t['text_secondary']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    margin-right: 4px;
    font-size: 13px;
}}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{
    color: {t['blue']};
    border-bottom: 2px solid {t['blue']};
    font-weight: 600;
}}

/* ================= 分段控件 ================= */
QPushButton[segment="true"] {{
    background: transparent; border: none; border-radius: 7px;
    padding: 5px 12px; color: {t['text_secondary']}; font-size: 12px;
}}
QPushButton[segment="true"]:hover {{ color: {t['text']}; }}
QPushButton[segment="true"]:checked {{
    background: {t['bg_surface']}; color: {t['text']};
    font-weight: 600; border: 1px solid {t['border']};
}}

/* ================= 复选框 / 滑动条 ================= */
QCheckBox, QRadioButton {{ spacing: 8px; color: {t['text']}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {t['border_strong']};
    background: {t['bg_surface']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {t['blue']}; border-color: {t['blue']};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['blue']}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t['bg_sunken']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['blue']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {t['bg_surface']}; border: 2px solid {t['blue']};
    width: 13px; height: 13px; margin: -6px 0; border-radius: 8px;
}}

/* ================= 编辑器 ================= */
QTextEdit#NoteBody {{
    background: {t['editor_bg']};
    border: none;
    border-radius: 0px;
    padding: 0px;
    font-size: 15px;
}}
QTextEdit#NoteBody[frame="true"] {{ border: 1px solid {t['border']}; border-radius: 10px; }}

QPlainTextEdit#Code, QTextEdit#Code {{
    font-family: "{mono}";
    font-size: 12px;
    background: {t['bg_sunken']};
}}

QFrame#FormatBar {{
    background: {t['bg_surface']};
    border: none;
    border-top: 1px solid {t['border']};
    border-bottom: 1px solid {t['border']};
}}

/* ================= 状态栏 ================= */
QStatusBar {{
    background: {t['bg_panel']};
    border: none;
    border-top: 1px solid {t['border']};
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    color: {t['text_muted']};
}}
QStatusBar::item {{ border: none; }}

/* ================= 分割线 ================= */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {t['blue_soft']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

/* ================= 进度 / 其它 ================= */
QProgressBar {{
    background: {t['bg_sunken']}; border: none; border-radius: 4px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {t['blue']}; border-radius: 4px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QListWidget#AttachmentStrip::item {{
    background: {t['bg_panel']};
    border: 1px solid {t['border']};
    border-radius: 10px;
    margin: 3px;
}}
QListWidget#AttachmentStrip::item:selected {{
    border: 1px solid {t['blue']};
    background: {t['blue_soft']};
}}

QPushButton#AccentSwatch {{ border-radius: 8px; border: 1px solid {t['border_strong']}; }}
QPushButton#AccentSwatch:checked {{ border: 2px solid {t['text']}; }}
"""


def editor_stylesheet(theme: str, font: str, size: int) -> str:
    """注入到 QTextDocument 的样式（正文渲染）。"""
    t = tokens(theme)
    body = font
    return f"""
    body {{ font-family: "{body}"; font-size: {size}px; color: {t['text']};
            line-height: 1.72; }}
    p  {{ margin: 0 0 9px 0; }}
    h1 {{ font-size: {int(size * 1.72)}px; font-weight: 700; color: {t['text']};
          margin: 20px 0 10px 0; }}
    h2 {{ font-size: {int(size * 1.42)}px; font-weight: 700; color: {t['text']};
          margin: 17px 0 8px 0; }}
    h3 {{ font-size: {int(size * 1.18)}px; font-weight: 600; color: {t['text_secondary']};
          margin: 14px 0 6px 0; }}
    a  {{ color: {t['blue']}; text-decoration: none; }}
    blockquote {{
        color: {t['text_secondary']};
        border-left: 3px solid {t['orange']};
        margin: 10px 0; padding: 4px 0 4px 14px;
    }}
    code {{
        font-family: "Consolas", monospace; font-size: {size - 1}px;
        background: {t['bg_sunken']}; color: {t['orange_press']};
        padding: 1px 5px; border-radius: 4px;
    }}
    pre {{
        font-family: "Consolas", monospace; font-size: {size - 1}px;
        background: {t['bg_sunken']}; color: {t['text']};
        padding: 12px 14px; border-radius: 8px;
        border-left: 3px solid {t['blue']};
    }}
    hr {{ border: none; border-top: 1px solid {t['border_strong']}; margin: 18px 0; }}
    table {{ border-collapse: collapse; margin: 10px 0; }}
    td, th {{ border: 1px solid {t['border_strong']}; padding: 7px 11px; }}
    th {{ background: {t['bg_panel']}; font-weight: 600; }}
    img {{ margin: 6px 0; }}
    ::selection {{ background: {t['selection']}; }}
    """
