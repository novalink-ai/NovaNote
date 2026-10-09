"""NovaNote — 全局配置、路径与用户设置。

所有与"应用级"（跨工作空间）相关的状态都放在这里：应用数据目录、
最近工作空间列表、UI 偏好等。工作空间内部的数据由 services/workspace.py 管理。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "NovaNote"
APP_NAME_CN = "星笺"
APP_VERSION = "1.0.0"
APP_TAGLINE = "本地优先的知识与文献工作台"
ORG_NAME = "NovaLab"
SCHEMA_VERSION = 4

_PKG_DIR = Path(__file__).resolve().parent
ASSETS_DIR = _PKG_DIR / "assets"


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def app_data_dir() -> Path:
    """跨平台的应用数据目录（存放全局配置、日志、缓存）。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_workspace_root() -> Path:
    """首次启动时建议的工作空间根目录。"""
    docs = Path.home() / "Documents"
    root = (docs if docs.exists() else Path.home()) / "NovaNote"
    return root


CONFIG_PATH = app_data_dir() / "config.json"
LOG_PATH = app_data_dir() / "novanote.log"


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #
@dataclass
class WorkspaceRef:
    id: str
    name: str
    path: str
    accent: str = "blue"
    last_opened: float = 0.0

    @property
    def db_path(self) -> Path:
        return Path(self.path) / "novanote.db"

    @property
    def assets_path(self) -> Path:
        return Path(self.path) / "assets"

    def exists(self) -> bool:
        return Path(self.path).is_dir() and self.db_path.exists()


@dataclass
class Settings:
    """全局（跨工作空间）用户设置。"""

    workspaces: list[dict] = field(default_factory=list)
    current_workspace: str | None = None
    theme: str = "light"                 # light | dark
    accent: str = "orange-blue"          # 保留位：品牌配色方案
    editor_font: str = "Sitka Text"      # 正文字体（回退见 theme.py）
    editor_font_size: int = 15
    editor_line_height: float = 168      # 百分数，QTextBlockFormat
    autosave_ms: int = 900
    show_word_count: bool = True
    confirm_delete: bool = True
    recent_files_limit: int = 20
    window_geometry: str | None = None
    first_run_done: bool = False

    # ---------------- 持久化 ---------------- #
    @classmethod
    def load(cls) -> "Settings":
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        else:
            raw = {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in raw.items() if k in known}
        obj = cls(**clean)
        obj.workspaces = [w for w in obj.workspaces if isinstance(w, dict) and w.get("path")]
        return obj

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(CONFIG_PATH)

    # ---------------- 工作空间 ---------------- #
    def refs(self) -> list[WorkspaceRef]:
        out: list[WorkspaceRef] = []
        for w in self.workspaces:
            try:
                out.append(WorkspaceRef(**w))
            except TypeError:
                continue
        return out

    def add_or_update_workspace(self, ref: WorkspaceRef) -> None:
        import time

        ref.last_opened = ref.last_opened or time.time()
        keep = [w for w in self.workspaces if w.get("id") != ref.id]
        keep.append(asdict(ref))
        self.workspaces = keep

    def remove_workspace(self, ws_id: str) -> None:
        self.workspaces = [w for w in self.workspaces if w.get("id") != ws_id]
        if self.current_workspace == ws_id:
            self.current_workspace = None
