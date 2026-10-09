"""工作空间：独立的数据目录（数据库 + 媒体附件 + 元信息）。

一个工作空间 = 一个文件夹，内部结构：

    <工作空间>/
        novanote.db          SQLite 主库
        workspace.json       元信息（名称、创建时间、ID）
        assets/
            2026/09/...      原始附件（按年月归档）
            thumbs/          图片/视频缩略图
        exports/             导出产物

删除/移动/备份工作空间只需操作这个文件夹。
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from ..config import WorkspaceRef
from ..database import Database


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, path: str | Path, name: str = "", ws_id: str = ""):
        self.path = Path(path).resolve()
        self.name = name or self.path.name
        self.id = ws_id or ""
        self._db: Database | None = None

    # ------------------------------------------------------------------ #
    @property
    def db_path(self) -> Path:
        return self.path / "novanote.db"

    @property
    def assets_dir(self) -> Path:
        return self.path / "assets"

    @property
    def thumbs_dir(self) -> Path:
        return self.assets_dir / "thumbs"

    @property
    def exports_dir(self) -> Path:
        return self.path / "exports"

    @property
    def meta_path(self) -> Path:
        return self.path / "workspace.json"

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(self.db_path)
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    # ------------------------------------------------------------------ #
    @classmethod
    def create(cls, path: str | Path, name: str) -> "Workspace":
        root = Path(path).resolve()
        if root.exists() and any(root.iterdir()):
            if not (root / "workspace.json").exists():
                raise WorkspaceError(
                    f"目录 {root} 非空且不是 NovaNote 工作空间，请选择空目录。"
                )
        root.mkdir(parents=True, exist_ok=True)
        (root / "assets" / "thumbs").mkdir(parents=True, exist_ok=True)
        (root / "exports").mkdir(parents=True, exist_ok=True)

        ws = cls(root, name=name, ws_id=uuid.uuid4().hex[:12])
        ws.db.init_schema(name)
        ws.db.set_meta("workspace_id", ws.id)
        ws.db.set_meta("name", name)
        ws.write_meta()
        return ws

    @classmethod
    def open(cls, path: str | Path, create_meta: bool = True) -> "Workspace":
        root = Path(path).resolve()
        if not root.is_dir():
            raise WorkspaceError(f"工作空间目录不存在：{root}")
        meta = {}
        mp = root / "workspace.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        ws = cls(root, name=meta.get("name") or root.name, ws_id=meta.get("id") or "")
        (root / "assets" / "thumbs").mkdir(parents=True, exist_ok=True)
        (root / "exports").mkdir(parents=True, exist_ok=True)
        if not ws.db_path.exists():
            # 指向了一个尚未初始化的工作空间目录：就地建库
            ws.db.init_schema(ws.name)
        ws.name = ws.db.get_meta("name") or ws.name
        ws.id = ws.db.get_meta("workspace_id") or ws.id or uuid.uuid4().hex[:12]
        ws.db.set_meta("workspace_id", ws.id)
        if create_meta:
            ws.write_meta()
        return ws

    def write_meta(self) -> None:
        data = {
            "app": "NovaNote",
            "format": 1,
            "id": self.id,
            "name": self.name,
            "created_at": self.db.get_meta("created_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            self.meta_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    def to_ref(self) -> WorkspaceRef:
        return WorkspaceRef(id=self.id, name=self.name, path=str(self.path), last_opened=time.time())

    def size_bytes(self) -> int:
        total = 0
        for p in self.path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
        return total

    def stats(self) -> dict:
        s = self.db.stats()
        s["name"] = self.name
        s["path"] = str(self.path)
        s["id"] = self.id
        s["total_assets_bytes"] = self.size_bytes()
        s["created_at"] = self.db.get_meta("created_at", "")
        return s

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.db.set_meta("name", new_name)
        self.write_meta()

    def export_backup(self, target_dir: str | Path) -> Path:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = Path(target_dir) / f"NovaNote_备份_{self.name}_{stamp}"
        shutil.copytree(self.path, target, dirs_exist_ok=True)
        return target


# --------------------------------------------------------------------------- #
# 全局工作空间注册表
# --------------------------------------------------------------------------- #
class WorkspaceRegistry:
    """负责新建 / 打开 / 切换工作空间，并把注册信息写回全局配置。"""

    def __init__(self, settings):
        from ..config import Settings  # noqa: F401  (类型提示)

        self.settings = settings
        self.current: Workspace | None = None

    # ---------------- 新建 ---------------- #
    def create(self, root: str | Path, name: str, open_now: bool = True) -> Workspace:
        ws = Workspace.create(root, name)
        ref = ws.to_ref()
        self.settings.add_or_update_workspace(ref)
        if open_now:
            self.settings.current_workspace = ref.id
        self.settings.save()
        if open_now:
            self.current = ws
        return ws

    # ---------------- 打开 ---------------- #
    def open(self, root: str | Path) -> Workspace:
        ws = Workspace.open(root)
        ref = ws.to_ref()
        self.settings.add_or_update_workspace(ref)
        self.settings.current_workspace = ref.id
        self.settings.save()
        self.current = ws
        return ws

    def activate(self, ws_id: str) -> Workspace:
        for ref in self.settings.refs():
            if ref.id == ws_id:
                return self.open(ref.path)
        raise WorkspaceError("未找到该工作空间的记录。")

    def touch_current(self) -> None:
        if self.current:
            self.settings.add_or_update_workspace(self.current.to_ref())
            self.settings.current_workspace = self.current.id
            self.settings.save()

    # ---------------- 管理 ---------------- #
    def recent(self) -> list[WorkspaceRef]:
        refs = self.settings.refs()
        refs.sort(key=lambda r: r.last_opened or 0, reverse=True)
        return refs

    def forget(self, ws_id: str) -> None:
        """仅从列表移除记录，不删除磁盘数据。"""
        self.settings.remove_workspace(ws_id)
        self.settings.save()

    def delete_from_disk(self, ws_id: str) -> None:
        for ref in self.settings.refs():
            if ref.id == ws_id:
                if self.current and self.current.id == ws_id:
                    self.current.close()
                    self.current = None
                shutil.rmtree(ref.path, ignore_errors=True)
                self.forget(ws_id)
                return

    def resolve_startup_workspace(self) -> Workspace | None:
        cur = self.settings.current_workspace
        if cur:
            try:
                return self.activate(cur)
            except WorkspaceError:
                pass
        recents = [r for r in self.recent() if r.exists()]
        if recents:
            try:
                return self.open(recents[0].path)
            except WorkspaceError:
                return None
        return None
