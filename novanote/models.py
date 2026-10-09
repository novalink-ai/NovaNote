"""领域模型：与数据库行一一对应的轻量数据类。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

NOTE_KIND_TEXT = "text"
NOTE_KIND_IMAGE = "image"
NOTE_KIND_VIDEO = "video"
NOTE_KIND_MIXED = "mixed"

ENTRY_TYPES = [
    ("article", "期刊论文"),
    ("inproceedings", "会议论文"),
    ("book", "专著"),
    ("incollection", "文集章节"),
    ("phdthesis", "博士学位论文"),
    ("mastersthesis", "硕士学位论文"),
    ("techreport", "技术报告"),
    ("misc", "其他"),
    ("patent", "专利"),
    ("standard", "标准"),
    ("dataset", "数据集"),
]

READ_STATES = {0: "未读", 1: "在读", 2: "已读"}


def _row_get(row, key, default=""):
    try:
        v = row[key]
    except (IndexError, KeyError):
        return default
    return default if v is None else v


@dataclass
class Notebook:
    id: int = 0
    name: str = ""
    icon: str = "folder"
    color: str = "#3A6E93"
    sort_order: int = 0
    is_default: bool = False
    created_at: str = ""
    note_count: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Notebook":
        return cls(
            id=_row_get(row, "id", 0),
            name=_row_get(row, "name"),
            icon=_row_get(row, "icon", "folder"),
            color=_row_get(row, "color", "#3A6E93"),
            sort_order=_row_get(row, "sort_order", 0),
            is_default=bool(_row_get(row, "is_default", 0)),
            created_at=_row_get(row, "created_at"),
            note_count=_row_get(row, "note_count", 0),
        )


@dataclass
class Tag:
    id: int = 0
    name: str = ""
    color: str = "#D0854C"
    count: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Tag":
        return cls(
            id=_row_get(row, "id", 0),
            name=_row_get(row, "name"),
            color=_row_get(row, "color", "#D0854C"),
            count=_row_get(row, "count", 0),
        )


@dataclass
class Asset:
    id: int = 0
    note_id: int = 0
    ref_id: int = 0
    kind: str = "file"
    filename: str = ""
    rel_path: str = ""
    thumb_rel_path: str = ""
    mime: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    caption: str = ""
    position: int = 0
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Asset":
        return cls(
            id=_row_get(row, "id", 0),
            note_id=_row_get(row, "note_id", 0) or 0,
            ref_id=_row_get(row, "ref_id", 0) or 0,
            kind=_row_get(row, "kind", "file"),
            filename=_row_get(row, "filename"),
            rel_path=_row_get(row, "rel_path"),
            thumb_rel_path=_row_get(row, "thumb_rel_path"),
            mime=_row_get(row, "mime"),
            size=_row_get(row, "size", 0),
            width=_row_get(row, "width", 0),
            height=_row_get(row, "height", 0),
            duration_ms=_row_get(row, "duration_ms", 0),
            caption=_row_get(row, "caption"),
            position=_row_get(row, "position", 0),
            created_at=_row_get(row, "created_at"),
        )

    @property
    def size_text(self) -> str:
        n = float(self.size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def is_video(self) -> bool:
        return self.kind == "video"


@dataclass
class Note:
    id: int = 0
    notebook_id: int | None = None
    title: str = "新建笔记"
    body_html: str = ""
    plain_text: str = ""
    kind: str = NOTE_KIND_TEXT
    source_url: str = ""
    is_starred: bool = False
    is_trashed: bool = False
    trashed_at: str | None = None
    word_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    notebook_name: str = ""
    notebook_color: str = "#3A6E93"
    tags: list[str] = field(default_factory=list)
    asset_count: int = 0
    ref_count: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Note":
        return cls(
            id=_row_get(row, "id", 0),
            notebook_id=_row_get(row, "notebook_id", None),
            title=_row_get(row, "title") or "无标题笔记",
            body_html=_row_get(row, "body_html"),
            plain_text=_row_get(row, "plain_text"),
            kind=_row_get(row, "kind", NOTE_KIND_TEXT),
            source_url=_row_get(row, "source_url"),
            is_starred=bool(_row_get(row, "is_starred", 0)),
            is_trashed=bool(_row_get(row, "is_trashed", 0)),
            trashed_at=_row_get(row, "trashed_at", None),
            word_count=_row_get(row, "word_count", 0),
            created_at=_row_get(row, "created_at"),
            updated_at=_row_get(row, "updated_at"),
            notebook_name=_row_get(row, "notebook_name", ""),
            notebook_color=_row_get(row, "notebook_color", "#3A6E93"),
            asset_count=_row_get(row, "asset_count", 0),
            ref_count=_row_get(row, "ref_count", 0),
        )

    @property
    def preview(self) -> str:
        text = " ".join((self.plain_text or "").split())
        return text[:160]

    @property
    def display_time(self) -> str:
        for fmt_in, fmt_out in (
            ("%Y-%m-%d %H:%M:%S", "%m-%d %H:%M"),
        ):
            try:
                return datetime.strptime(self.updated_at or "", fmt_in).strftime(fmt_out)
            except ValueError:
                continue
        return (self.updated_at or "")[:16]

    @property
    def full_time(self) -> str:
        return (self.updated_at or "").replace("-", "/")


@dataclass
class Reference:
    id: int = 0
    citekey: str = ""
    entry_type: str = "article"
    title: str = ""
    authors: str = ""
    year: str = ""
    container: str = ""
    publisher: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    keywords: str = ""
    language: str = ""
    note: str = ""
    read_state: int = 0
    rating: int = 0
    is_starred: bool = False
    added_at: str = ""
    updated_at: str = ""
    extra_json: str = ""
    tags: list[str] = field(default_factory=list)
    pdf_count: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Reference":
        return cls(
            id=_row_get(row, "id", 0),
            citekey=_row_get(row, "citekey"),
            entry_type=_row_get(row, "entry_type", "article"),
            title=_row_get(row, "title"),
            authors=_row_get(row, "authors"),
            year=_row_get(row, "year"),
            container=_row_get(row, "container"),
            publisher=_row_get(row, "publisher"),
            volume=_row_get(row, "volume"),
            issue=_row_get(row, "issue"),
            pages=_row_get(row, "pages"),
            doi=_row_get(row, "doi"),
            url=_row_get(row, "url"),
            abstract=_row_get(row, "abstract"),
            keywords=_row_get(row, "keywords"),
            language=_row_get(row, "language"),
            note=_row_get(row, "note"),
            read_state=_row_get(row, "read_state", 0),
            rating=_row_get(row, "rating", 0),
            is_starred=bool(_row_get(row, "is_starred", 0)),
            added_at=_row_get(row, "added_at"),
            updated_at=_row_get(row, "updated_at"),
            extra_json=_row_get(row, "extra_json", "{}"),
            pdf_count=_row_get(row, "pdf_count", 0),
        )

    # -------------------- 展示辅助 -------------------- #
    @property
    def authors_short(self) -> str:
        names = [a.strip() for a in (self.authors or "").replace(";", " and ").split(" and ") if a.strip()]
        if not names:
            return "佚名"
        if len(names) == 1:
            return _surname(names[0])
        if len(names) == 2:
            return f"{_surname(names[0])} & {_surname(names[1])}"
        return f"{_surname(names[0])} 等"

    @property
    def author_list(self) -> list[str]:
        return [a.strip() for a in (self.authors or "").replace(";", " and ").split(" and ") if a.strip()]

    @property
    def year_text(self) -> str:
        return self.year or "—"

    @property
    def type_text(self) -> str:
        return dict(ENTRY_TYPES).get(self.entry_type, self.entry_type or "其他")

    @property
    def read_text(self) -> str:
        return READ_STATES.get(self.read_state, "未读")

    @property
    def keyword_list(self) -> list[str]:
        raw = (self.keywords or "").replace("；", ";").replace("，", ",")
        parts: list[str] = []
        for chunk in raw.replace(",", ";").split(";"):
            for p in chunk.split("|"):
                p = p.strip()
                if p:
                    parts.append(p)
        return parts

    @property
    def venue_short(self) -> str:
        return self.container or self.publisher or "—"

    def citation_apa(self) -> str:
        names = self.author_list
        if names:
            formatted = []
            for n in names:
                formatted.append(_apa_name(n))
            if len(formatted) == 1:
                a = formatted[0]
            elif len(formatted) <= 20:
                a = ", ".join(formatted[:-1]) + ", & " + formatted[-1]
            else:
                a = ", ".join(formatted[:19]) + ", ... " + formatted[-1]
        else:
            a = self.publisher or "佚名"
        year = f"({self.year})." if self.year else "(n.d.)."
        parts = [f"{a} {year}", f"{self.title}."]
        if self.container:
            parts.append(f"*{self.container}*")
        tail = ""
        if self.volume:
            tail += f", {self.volume}"
        if self.issue:
            tail += f"({self.issue})"
        if self.pages:
            tail += f", {self.pages}"
        if tail:
            parts.append(tail.strip().lstrip(",").strip() + ".")
        if self.doi:
            parts.append(f"https://doi.org/{self.doi}")
        elif self.url:
            parts.append(self.url)
        return " ".join(p for p in parts if p).replace(" .", ".")

    def citation_gbt(self) -> str:
        """GB/T 7714-2015 风格（中文期刊常用）。"""
        names = self.author_list
        if names:
            shown = names[:3]
            au = ", ".join(_gbt_name(n) for n in shown)
            if len(names) > 3:
                au += ", 等"
        else:
            au = "佚名"
        seg = [f"{au}. {self.title}"
               f"[{_gbt_marker(self.entry_type)}]"]
        line = "".join(seg)
        if self.container:
            line += f". {self.container}"
        if self.year:
            line += f", {self.year}"
        if self.volume:
            line += f", {self.volume}"
        if self.issue:
            line += f"({self.issue})"
        if self.pages:
            line += f": {self.pages}"
        line += "."
        if self.doi:
            line += f" DOI:{self.doi}."
        return line

    def citation_short(self) -> str:
        first = self.author_list[0] if self.author_list else "佚名"
        return f"{_surname(first)} {self.year or 'n.d.'}"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("tags", "pdf_count")}

    def extra(self) -> dict:
        if not self.extra_json:
            return {}
        try:
            return json.loads(self.extra_json)
        except Exception:
            return {}


def _surname(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    if "," in name:                      # "Smith, John"
        return name.split(",")[0].strip().split()[-1]
    if " " in name:
        return name.split()[-1]
    return name                          # 中文名整体保留


def _apa_name(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    if "," in name:
        return name
    if " " in name:
        parts = name.split()
        initials = " ".join(f"{p[0]}." for p in parts[1:] if p)
        return f"{parts[-1]}, {initials}".strip().rstrip(",")
    return name


def _gbt_name(name: str) -> str:
    name = name.strip()
    if " " in name and "," not in name:
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[-1]} {' '.join(p[0] for p in parts[:-1])}".upper()
    if "," in name:
        sur, _, given = name.partition(",")
        return f"{sur.strip()} {given.strip()}".upper()
    return name


_GBT_MARKERS = {
    "article": "J", "inproceedings": "C", "book": "M", "incollection": "M",
    "phdthesis": "D", "mastersthesis": "D", "techreport": "R", "patent": "P",
    "standard": "S", "dataset": "DS", "misc": "Z",
}


def _gbt_marker(t: str) -> str:
    return _GBT_MARKERS.get(t, "Z")
