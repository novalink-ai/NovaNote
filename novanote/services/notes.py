"""笔记仓储：笔记本、标签、正文、附件、与文献的双向关联。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..database import now_iso
from ..models import Asset, Notebook, Note, Tag

TAG_PALETTE = [
    "#D0854C", "#3A6E93", "#57896A", "#C79A3F", "#9A6E9E",
    "#4E8C8C", "#BE5A50", "#6E7FA8", "#A2714B", "#5F7D52",
]


@dataclass
class NoteFilter:
    notebook_id: int | None = None
    tag: str | None = None
    starred: bool | None = None
    trashed: bool = False
    kind: str | None = None
    query: str = ""
    sort: str = "updated_desc"      # updated_desc | updated_asc | created_desc | title_asc
    limit: int = 0                  # 0 = 不限
    has_assets: bool | None = None


_SORT_SQL = {
    "updated_desc": "n.updated_at DESC",
    "updated_asc": "n.updated_at ASC",
    "created_desc": "n.created_at DESC",
    "title_asc": "n.title COLLATE NOCASE ASC",
    "title_desc": "n.title COLLATE NOCASE DESC",
}

_SELECT_NOTE = """
SELECT n.*, b.name AS notebook_name, b.color AS notebook_color,
       (SELECT COUNT(*) FROM assets a WHERE a.note_id = n.id) AS asset_count,
       (SELECT COUNT(*) FROM note_refs nr WHERE nr.note_id = n.id) AS ref_count
FROM notes n
LEFT JOIN notebooks b ON b.id = n.notebook_id
"""

# 列表 / 关联查询专用的轻量列集合：**不含 body_html**。
# 列表卡片只用到标题与 plain_text 前 160 字（Note.preview），
# 正文 HTML 只在打开某篇笔记（notes.get）时才按需读取。
# 实测 2000 篇规模下，省掉 body_html 可让列表刷新快约 2 倍。
_SELECT_NOTE_LIST = """
SELECT n.id, n.notebook_id, n.title, n.kind, n.source_url, n.plain_text,
       n.is_starred, n.is_trashed, n.trashed_at, n.word_count,
       n.created_at, n.updated_at,
       b.name AS notebook_name, b.color AS notebook_color,
       (SELECT COUNT(*) FROM assets a WHERE a.note_id = n.id) AS asset_count,
       (SELECT COUNT(*) FROM note_refs nr WHERE nr.note_id = n.id) AS ref_count
FROM notes n
LEFT JOIN notebooks b ON b.id = n.notebook_id
"""


def count_words(text: str) -> int:
    """中英混排字数：CJK 逐字计，西文按词计。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-\u2019]*", text))
    return cjk + latin


def html_to_text(html: str) -> str:
    if not html:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|h[1-6]|li|tr|blockquote|pre)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("\u200b", "")
    )
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class NoteService:
    def __init__(self, workspace):
        self.ws = workspace
        self.db = workspace.db

    # ================================================================== #
    # 笔记本
    # ================================================================== #
    def notebooks(self) -> list[Notebook]:
        # 用 GROUP BY 一次性统计，避免对每个笔记本跑一次相关子查询
        # （旧写法会让 SQLite 对每个笔记本扫一遍 notes 索引）
        rows = self.db.query(
            "SELECT b.*, COALESCE(c.cnt, 0) AS note_count"
            " FROM notebooks b"
            " LEFT JOIN (SELECT notebook_id, COUNT(*) AS cnt FROM notes"
            "            WHERE is_trashed = 0 GROUP BY notebook_id) c"
            "   ON c.notebook_id = b.id"
            " ORDER BY b.sort_order, b.id"
        )
        return [Notebook.from_row(r) for r in rows]

    def notebook(self, nb_id: int) -> Notebook | None:
        r = self.db.query_one("SELECT * FROM notebooks WHERE id = ?", (nb_id,))
        return Notebook.from_row(r) if r else None

    def create_notebook(self, name: str, icon: str = "folder", color: str = "#3A6E93") -> Notebook:
        order = self.db.query_one("SELECT COALESCE(MAX(sort_order),0)+1 AS o FROM notebooks")
        nid = self.db.execute(
            "INSERT INTO notebooks(name, icon, color, sort_order, is_default, created_at)"
            " VALUES (?,?,?,?,0,?)",
            (name.strip() or "未命名笔记本", icon, color, int(order["o"]), now_iso()),
        ).lastrowid
        return self.notebook(nid)  # type: ignore[return-value]

    def update_notebook(self, nb_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in {"name", "icon", "color", "sort_order"}}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self.db.execute(f"UPDATE notebooks SET {sets} WHERE id = ?", (*allowed.values(), nb_id))

    def delete_notebook(self, nb_id: int, move_to: int | None = None) -> None:
        if move_to:
            self.db.execute("UPDATE notes SET notebook_id = ? WHERE notebook_id = ?", (move_to, nb_id))
        self.db.execute("DELETE FROM notebooks WHERE id = ?", (nb_id,))

    def default_notebook_id(self) -> int | None:
        r = self.db.query_one("SELECT id FROM notebooks ORDER BY is_default DESC, sort_order, id LIMIT 1")
        return int(r["id"]) if r else None

    # ================================================================== #
    # 标签
    # ================================================================== #
    def tags(self, include_refs: bool = True) -> list[Tag]:
        sql = (
            "SELECT t.*, ((SELECT COUNT(*) FROM note_tags nt WHERE nt.tag_id = t.id)"
            + (" + (SELECT COUNT(*) FROM ref_tags rt WHERE rt.tag_id = t.id)" if include_refs else "")
            + ") AS count FROM tags t ORDER BY t.name COLLATE NOCASE"
        )
        return [Tag.from_row(r) for r in self.db.query(sql)]

    def ensure_tag(self, name: str, color: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("标签名不能为空")
        row = self.db.query_one("SELECT id FROM tags WHERE name = ?", (name,))
        if row:
            return int(row["id"])
        if not color:
            n = self.db.query_one("SELECT COUNT(*) AS c FROM tags")
            color = TAG_PALETTE[int(n["c"]) % len(TAG_PALETTE)]
        return int(self.db.execute("INSERT INTO tags(name, color) VALUES (?,?)", (name, color)).lastrowid)

    def rename_tag(self, tag_id: int, new_name: str) -> None:
        self.db.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name.strip(), tag_id))

    def set_tag_color(self, tag_id: int, color: str) -> None:
        self.db.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))

    def delete_tag(self, tag_id: int) -> None:
        self.db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    def note_tags(self, note_id: int) -> list[str]:
        return [
            r["name"]
            for r in self.db.query(
                "SELECT t.name FROM tags t JOIN note_tags nt ON nt.tag_id = t.id"
                " WHERE nt.note_id = ? ORDER BY t.name",
                (note_id,),
            )
        ]

    def set_note_tags(self, note_id: int, names: list[str]) -> None:
        self.db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        for nm in names:
            nm = nm.strip()
            if not nm:
                continue
            tid = self.ensure_tag(nm)
            self.db.execute(
                "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?,?)", (note_id, tid)
            )

    # ================================================================== #
    # 笔记
    # ================================================================== #
    def get(self, note_id: int) -> Note | None:
        r = self.db.query_one(_SELECT_NOTE + " WHERE n.id = ?", (note_id,))
        if not r:
            return None
        note = Note.from_row(r)
        note.tags = self.note_tags(note_id)
        return note

    def list(self, flt: NoteFilter | None = None) -> list[Note]:
        flt = flt or NoteFilter()
        where = ["n.is_trashed = ?"]
        params: list = [1 if flt.trashed else 0]

        if flt.notebook_id is not None:
            where.append("n.notebook_id = ?")
            params.append(flt.notebook_id)
        if flt.starred:
            where.append("n.is_starred = 1")
        if flt.kind:
            where.append("n.kind = ?")
            params.append(flt.kind)
        if flt.tag:
            where.append(
                "EXISTS (SELECT 1 FROM note_tags nt JOIN tags t ON t.id = nt.tag_id"
                " WHERE nt.note_id = n.id AND t.name = ?)"
            )
            params.append(flt.tag)
        if flt.has_assets:
            where.append("EXISTS (SELECT 1 FROM assets a WHERE a.note_id = n.id)")

        q = (flt.query or "").strip()
        if q:
            like = f"%{q}%"
            where.append("(n.title LIKE ? OR n.plain_text LIKE ?)")
            params.extend([like, like])

        order = _SORT_SQL.get(flt.sort, _SORT_SQL["updated_desc"])
        sql = _SELECT_NOTE_LIST + " WHERE " + " AND ".join(where) + f" ORDER BY {order}"
        if flt.limit:
            sql += f" LIMIT {int(flt.limit)}"

        notes = [Note.from_row(r) for r in self.db.query(sql, params)]
        if notes:
            self._attach_tags(notes)
        return notes

    def _attach_tags(self, notes: list[Note]) -> None:
        ids = [n.id for n in notes]
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        rows = self.db.query(
            f"SELECT nt.note_id, t.name FROM note_tags nt JOIN tags t ON t.id = nt.tag_id"
            f" WHERE nt.note_id IN ({marks}) ORDER BY t.name",
            ids,
        )
        bucket: dict[int, list[str]] = {}
        for r in rows:
            bucket.setdefault(int(r["note_id"]), []).append(r["name"])
        for n in notes:
            n.tags = bucket.get(n.id, [])

    def create(
        self,
        title: str = "",
        body_html: str = "",
        notebook_id: int | None = None,
        kind: str = "text",
        tags: list[str] | None = None,
        source_url: str = "",
    ) -> Note:
        if notebook_id is None:
            notebook_id = self.default_notebook_id()
        plain = html_to_text(body_html)
        stamp = now_iso()
        nid = int(
            self.db.execute(
                "INSERT INTO notes(notebook_id, title, body_html, plain_text, kind, source_url,"
                " word_count, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (notebook_id, title or "新建笔记", body_html, plain, kind, source_url,
                 count_words(plain), stamp, stamp),
            ).lastrowid
        )
        if tags:
            self.set_note_tags(nid, tags)
        return self.get(nid)  # type: ignore[return-value]

    def update(self, note_id: int, **fields) -> None:
        allowed = {"title", "body_html", "notebook_id", "kind", "source_url",
                   "is_starred", "is_trashed", "trashed_at"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            params.append(v)
        if "body_html" in fields:
            plain = html_to_text(fields["body_html"])
            sets += ["plain_text = ?", "word_count = ?"]
            params += [plain, count_words(plain)]
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(note_id)
        self.db.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id = ?", params)

    def touch(self, note_id: int) -> None:
        self.db.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (now_iso(), note_id))

    def set_starred(self, note_id: int, value: bool) -> None:
        self.db.execute(
            "UPDATE notes SET is_starred = ?, updated_at = ? WHERE id = ?",
            (1 if value else 0, now_iso(), note_id),
        )

    def trash(self, note_id: int) -> None:
        self.db.execute(
            "UPDATE notes SET is_trashed = 1, trashed_at = ?, updated_at = ? WHERE id = ?",
            (now_iso(), now_iso(), note_id),
        )

    def restore(self, note_id: int) -> None:
        self.db.execute(
            "UPDATE notes SET is_trashed = 0, trashed_at = NULL, updated_at = ? WHERE id = ?",
            (now_iso(), note_id),
        )

    def purge(self, note_id: int) -> list[str]:
        """彻底删除笔记并返回需清理的附件相对路径。"""
        rels = self.asset_rels(note_id)
        self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return rels

    def empty_trash(self) -> list[str]:
        """清空回收站，返回需清理的附件相对路径。

        批量处理：旧写法逐篇 purge() 会为每篇笔记各跑一次 attachments 查询，
        回收站里几百篇时就是几百次往返。这里一次性取附件、一次性删除。
        按 400 一批切分，避开 SQLite 绑定参数上限。
        """
        ids = [int(r["id"]) for r in self.db.query("SELECT id FROM notes WHERE is_trashed = 1")]
        if not ids:
            return []

        rels: list[str] = []
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            for r in self.db.query(
                f"SELECT rel_path, thumb_rel_path FROM assets WHERE note_id IN ({marks})", chunk
            ):
                rels += [p for p in (r["rel_path"], r["thumb_rel_path"]) if p]
            self.db.execute(f"DELETE FROM notes WHERE id IN ({marks})", chunk)
        return rels

    def duplicate(self, note_id: int) -> Note | None:
        note = self.get(note_id)
        if not note:
            return None
        copy = self.create(
            title=f"{note.title} 副本",
            body_html=note.body_html,
            notebook_id=note.notebook_id,
            kind=note.kind,
            tags=list(note.tags),
            source_url=note.source_url,
        )
        for a in self.assets(note_id):
            row = dict(a.__dict__)
            row.pop("id", None)
            row["note_id"] = copy.id
            cols = ", ".join(row.keys())
            marks = ", ".join("?" * len(row))
            self.db.execute(f"INSERT INTO assets({cols}) VALUES ({marks})", list(row.values()))
        return copy

    # ================================================================== #
    # 附件
    # ================================================================== #
    def assets(self, note_id: int) -> list[Asset]:
        rows = self.db.query(
            "SELECT * FROM assets WHERE note_id = ? ORDER BY position, id", (note_id,)
        )
        return [Asset.from_row(r) for r in rows]

    def first_assets(self, note_ids: list[int]) -> dict[int, Asset]:
        """批量取每篇笔记的首个附件（媒体网格缩略图用）。

        媒体视图原先是"每篇笔记各查一次附件"，2000 篇就是 2000 次往返；
        这里用一条 GROUP BY 查询搞定。
        """
        ids = [int(i) for i in note_ids]
        if not ids:
            return {}
        out: dict[int, Asset] = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            rows = self.db.query(
                "SELECT * FROM assets WHERE id IN ("
                f"  SELECT MIN(id) FROM assets WHERE note_id IN ({marks}) GROUP BY note_id"
                ")",
                chunk,
            )
            for r in rows:
                a = Asset.from_row(r)
                out[a.note_id] = a
        return out

    def add_asset(self, note_id: int, info: dict) -> Asset:
        pos = self.db.query_one(
            "SELECT COALESCE(MAX(position),-1)+1 AS p FROM assets WHERE note_id = ?", (note_id,)
        )
        fields = {
            "note_id": note_id,
            "ref_id": None,
            "kind": info.get("kind", "file"),
            "filename": info.get("filename", ""),
            "rel_path": info.get("rel_path", ""),
            "thumb_rel_path": info.get("thumb_rel_path", ""),
            "mime": info.get("mime", ""),
            "size": int(info.get("size", 0) or 0),
            "width": int(info.get("width", 0) or 0),
            "height": int(info.get("height", 0) or 0),
            "duration_ms": int(info.get("duration_ms", 0) or 0),
            "caption": info.get("caption", ""),
            "position": int(pos["p"]) if pos else 0,
            "created_at": info.get("created_at") or now_iso(),
        }
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" * len(fields))
        aid = int(self.db.execute(f"INSERT INTO assets({cols}) VALUES ({marks})", list(fields.values())).lastrowid)
        row = self.db.query_one("SELECT * FROM assets WHERE id = ?", (aid,))
        self.refresh_kind(note_id)
        return Asset.from_row(row)

    def asset_rels(self, note_id: int) -> list[str]:
        rels: list[str] = []
        for a in self.assets(note_id):
            rels += [a.rel_path, a.thumb_rel_path]
        return [r for r in rels if r]

    def delete_asset(self, asset_id: int) -> list[str]:
        row = self.db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
        if not row:
            return []
        rels = [row["rel_path"], row["thumb_rel_path"]]
        note_id = row["note_id"]
        self.db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        if note_id:
            self.refresh_kind(int(note_id))
        return [r for r in rels if r]

    def refresh_kind(self, note_id: int) -> None:
        kinds = {
            r["kind"]
            for r in self.db.query(
                "SELECT DISTINCT kind FROM assets WHERE note_id = ?", (note_id,)
            )
        }
        if {"image", "video"} & kinds:
            kind = "mixed" if len({"image", "video"} & kinds) > 1 else (
                "image" if "image" in kinds else "video"
            )
        else:
            kind = "text"
        self.db.execute("UPDATE notes SET kind = ? WHERE id = ?", (kind, note_id))

    # ================================================================== #
    # 与文献的关联
    # ================================================================== #
    def link_ref(self, note_id: int, ref_id: int) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO note_refs(note_id, ref_id) VALUES (?,?)", (note_id, ref_id)
        )

    def unlink_ref(self, note_id: int, ref_id: int) -> None:
        self.db.execute("DELETE FROM note_refs WHERE note_id = ? AND ref_id = ?", (note_id, ref_id))

    def linked_refs(self, note_id: int) -> list[int]:
        return [int(r["ref_id"]) for r in self.db.query(
            "SELECT ref_id FROM note_refs WHERE note_id = ?", (note_id,))]

    def notes_for_ref(self, ref_id: int) -> list[Note]:
        # 文献详情里只展示标题列表，因此同样走轻量列集合
        rows = self.db.query(
            _SELECT_NOTE_LIST + " JOIN note_refs nr ON nr.note_id = n.id WHERE nr.ref_id = ?"
            " AND n.is_trashed = 0 ORDER BY n.updated_at DESC",
            (ref_id,),
        )
        notes = [Note.from_row(r) for r in rows]
        self._attach_tags(notes)
        return notes

    def create_note_for_ref(self, ref, notebook_id: int | None = None) -> Note:
        body = (
            f"<h3>{ref.authors_short} · {ref.year_text}</h3>"
            f"<p><b>引用：</b>{ref.citation_gbt()}</p>"
            f"<p><b>关键词：</b>{ref.keywords or '—'}</p>"
            "<h3>摘要</h3>"
            f"<p>{ref.abstract or '（暂无摘要）'}</p>"
            "<h3>我的批注</h3><p><br/></p>"
        )
        note = self.create(
            title=f"文献笔记 · {ref.title[:60]}",
            body_html=body,
            notebook_id=notebook_id,
            tags=["文献阅读"] + ref.keyword_list[:3],
        )
        self.link_ref(note.id, ref.id)
        return note

    # ================================================================== #
    # 检索
    # ================================================================== #
    def search(self, query: str, limit: int = 200) -> list[Note]:
        return self.list(NoteFilter(query=query, limit=limit))

    def timeline(self, limit: int = 60) -> list[Note]:
        return self.list(NoteFilter(sort="updated_desc", limit=limit))

    def all_tags_with_counts(self) -> list[Tag]:
        return self.tags()
