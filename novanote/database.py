"""SQLite 数据层：连接管理、建表、版本迁移。

设计要点
  * 单文件数据库，随工作空间目录一起迁移/备份
  * WAL 模式 + 外键约束
  * schema_version 驱动的前向迁移，保证旧工作空间可平滑升级
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .config import SCHEMA_VERSION

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS notebooks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    icon       TEXT    NOT NULL DEFAULT 'folder',
    color      TEXT    NOT NULL DEFAULT '#3A6E93',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER REFERENCES notebooks(id) ON DELETE SET NULL,
    title       TEXT    NOT NULL DEFAULT '',
    body_html   TEXT    NOT NULL DEFAULT '',
    plain_text  TEXT    NOT NULL DEFAULT '',
    kind        TEXT    NOT NULL DEFAULT 'text',
    source_url  TEXT    NOT NULL DEFAULT '',
    is_starred  INTEGER NOT NULL DEFAULT 0,
    is_trashed  INTEGER NOT NULL DEFAULT 0,
    trashed_at  TEXT,
    word_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_notebook ON notes(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notes_updated  ON notes(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_flags    ON notes(is_trashed, is_starred);
-- (notebook_id, is_trashed)：侧栏按笔记本计数时避免对每个笔记本全表扫 notes
CREATE INDEX IF NOT EXISTS idx_notes_nb_flags ON notes(notebook_id, is_trashed);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#D0854C'
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);
-- 主键是 (note_id, tag_id)，按 tag_id 反查（标签计数、按标签筛选）走不到主键前缀
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id);

CREATE TABLE IF NOT EXISTS assets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id        INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    ref_id         INTEGER REFERENCES refs(id)  ON DELETE CASCADE,
    kind           TEXT    NOT NULL DEFAULT 'file',
    filename       TEXT    NOT NULL DEFAULT '',
    rel_path       TEXT    NOT NULL,
    thumb_rel_path TEXT    NOT NULL DEFAULT '',
    mime           TEXT    NOT NULL DEFAULT '',
    size           INTEGER NOT NULL DEFAULT 0,
    width          INTEGER NOT NULL DEFAULT 0,
    height         INTEGER NOT NULL DEFAULT 0,
    duration_ms    INTEGER NOT NULL DEFAULT 0,
    caption        TEXT    NOT NULL DEFAULT '',
    position       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_note ON assets(note_id);
CREATE INDEX IF NOT EXISTS idx_assets_ref  ON assets(ref_id);

CREATE TABLE IF NOT EXISTS refs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    citekey    TEXT    NOT NULL DEFAULT '',
    entry_type TEXT    NOT NULL DEFAULT 'article',
    title      TEXT    NOT NULL DEFAULT '',
    authors    TEXT    NOT NULL DEFAULT '',
    year       TEXT    NOT NULL DEFAULT '',
    container  TEXT    NOT NULL DEFAULT '',
    publisher  TEXT    NOT NULL DEFAULT '',
    volume     TEXT    NOT NULL DEFAULT '',
    issue      TEXT    NOT NULL DEFAULT '',
    pages      TEXT    NOT NULL DEFAULT '',
    doi        TEXT    NOT NULL DEFAULT '',
    url        TEXT    NOT NULL DEFAULT '',
    abstract   TEXT    NOT NULL DEFAULT '',
    keywords   TEXT    NOT NULL DEFAULT '',
    language   TEXT    NOT NULL DEFAULT '',
    note       TEXT    NOT NULL DEFAULT '',
    read_state INTEGER NOT NULL DEFAULT 0,
    rating     INTEGER NOT NULL DEFAULT 0,
    is_starred INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT    NOT NULL DEFAULT '{}',
    added_at   TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_year  ON refs(year);
CREATE INDEX IF NOT EXISTS idx_refs_title ON refs(title);
-- 文献筛选常用维度（阅读状态 / 星标）
CREATE INDEX IF NOT EXISTS idx_refs_state ON refs(read_state, is_starred);

CREATE TABLE IF NOT EXISTS ref_tags (
    ref_id INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (ref_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_ref_tags_tag ON ref_tags(tag_id);

CREATE TABLE IF NOT EXISTS note_refs (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    ref_id  INTEGER NOT NULL REFERENCES refs(id)  ON DELETE CASCADE,
    PRIMARY KEY (note_id, ref_id)
);
-- 同上：反向查"某文献关联了哪些笔记"需要 ref_id 上的独立索引
CREATE INDEX IF NOT EXISTS idx_note_refs_ref ON note_refs(ref_id);
"""

DEFAULT_NOTEBOOKS = [
    ("灵感速记", "spark", "#D0854C", 0, 0),
    ("工作笔记", "note", "#3A6E93", 1, 1),
    ("文献阅读", "book", "#57896A", 2, 0),
    ("待办清单", "todo", "#C79A3F", 3, 0),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    """薄封装：线程本地连接 + 便捷查询。"""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()

    # ------------------------------------------------------------------ #
    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=15.0)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
            self._local.conn = None

    # ------------------------------------------------------------------ #
    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._write_lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, seq) -> None:
        with self._write_lock:
            self.conn.executemany(sql, seq)
            self.conn.commit()

    # ------------------------------------------------------------------ #
    def init_schema(self, workspace_name: str = "我的知识库") -> None:
        with self._write_lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

        version = self.get_meta("schema_version")
        if version is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self.set_meta("name", workspace_name)
            self.set_meta("created_at", now_iso())
            self.set_meta("workspace_id", "")
            if not self.query_one("SELECT 1 FROM notebooks LIMIT 1"):
                stamp = now_iso()
                self.executemany(
                    "INSERT INTO notebooks(name, icon, color, sort_order, is_default, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    [(n, i, c, s, d, stamp) for (n, i, c, s, d) in DEFAULT_NOTEBOOKS],
                )
        else:
            self._migrate(int(version))

    def _migrate(self, from_version: int) -> None:
        # 预留：未来版本在此按序补齐 ALTER TABLE / 数据搬迁
        if from_version < SCHEMA_VERSION:
            with self._write_lock:
                self.conn.executescript(SCHEMA)
                self.conn.commit()
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    # ------------------------------------------------------------------ #
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        def one(sql: str) -> int:
            r = self.query_one(sql)
            return int(r[0]) if r else 0

        return {
            "notes": one("SELECT COUNT(*) FROM notes WHERE is_trashed = 0"),
            "trash": one("SELECT COUNT(*) FROM notes WHERE is_trashed = 1"),
            "starred": one("SELECT COUNT(*) FROM notes WHERE is_starred = 1 AND is_trashed = 0"),
            "refs": one("SELECT COUNT(*) FROM refs"),
            "assets": one("SELECT COUNT(*) FROM assets"),
            "notebooks": one("SELECT COUNT(*) FROM notebooks"),
            "words": one("SELECT COALESCE(SUM(word_count),0) FROM notes WHERE is_trashed = 0"),
            "size": self.path.stat().st_size if self.path.exists() else 0,
        }
