"""学术文献管理：元数据 CRUD、BibTeX 导入导出、DOI 元数据抓取、引用格式化、PDF 附件。"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ..database import now_iso
from ..models import Asset, Reference

_SELECT_REF = """
SELECT r.*,
       (SELECT COUNT(*) FROM assets a WHERE a.ref_id = r.id AND a.kind IN ('pdf','document')) AS pdf_count
FROM refs r
"""

_SORT_SQL = {
    "added_desc": "r.added_at DESC",
    "year_desc": "CAST(NULLIF(r.year,'') AS INTEGER) DESC, r.added_at DESC",
    "year_asc": "CAST(NULLIF(r.year,'') AS INTEGER) ASC, r.added_at DESC",
    "title_asc": "r.title COLLATE NOCASE ASC",
    "authors_asc": "r.authors COLLATE NOCASE ASC",
}


@dataclass
class RefFilter:
    query: str = ""
    tag: str | None = None
    entry_type: str | None = None
    year: str | None = None
    read_state: int | None = None
    starred: bool | None = None
    has_pdf: bool | None = None
    sort: str = "added_desc"
    limit: int = 0


class LiteratureService:
    def __init__(self, workspace):
        self.ws = workspace
        self.db = workspace.db

    # ================================================================== #
    # 查询
    # ================================================================== #
    def get(self, ref_id: int) -> Reference | None:
        r = self.db.query_one(_SELECT_REF + " WHERE r.id = ?", (ref_id,))
        if not r:
            return None
        ref = Reference.from_row(r)
        ref.tags = self._tags_of(ref_id)
        return ref

    def list(self, flt: RefFilter | None = None) -> list[Reference]:
        flt = flt or RefFilter()
        where, params = ["1=1"], []
        if flt.entry_type:
            where.append("r.entry_type = ?")
            params.append(flt.entry_type)
        if flt.year:
            where.append("r.year = ?")
            params.append(flt.year)
        if flt.read_state is not None:
            where.append("r.read_state = ?")
            params.append(flt.read_state)
        if flt.starred:
            where.append("r.is_starred = 1")
        if flt.has_pdf:
            where.append(
                "EXISTS (SELECT 1 FROM assets a WHERE a.ref_id = r.id AND a.kind IN ('pdf','document'))"
            )
        if flt.tag:
            where.append(
                "EXISTS (SELECT 1 FROM ref_tags rt JOIN tags t ON t.id = rt.tag_id"
                " WHERE rt.ref_id = r.id AND t.name = ?)"
            )
            params.append(flt.tag)
        q = (flt.query or "").strip()
        if q:
            like = f"%{q}%"
            where.append(
                "(r.title LIKE ? OR r.authors LIKE ? OR r.keywords LIKE ?"
                " OR r.abstract LIKE ? OR r.container LIKE ? OR r.doi LIKE ?"
                " OR r.citekey LIKE ?)"
            )
            params += [like] * 7

        order = _SORT_SQL.get(flt.sort, _SORT_SQL["added_desc"])
        sql = _SELECT_REF + " WHERE " + " AND ".join(where) + f" ORDER BY {order}"
        if flt.limit:
            sql += f" LIMIT {int(flt.limit)}"
        refs = [Reference.from_row(r) for r in self.db.query(sql, params)]
        self._attach_tags(refs)
        return refs

    def _tags_of(self, ref_id: int) -> list[str]:
        return [r["name"] for r in self.db.query(
            "SELECT t.name FROM tags t JOIN ref_tags rt ON rt.tag_id = t.id"
            " WHERE rt.ref_id = ? ORDER BY t.name", (ref_id,))]

    def _attach_tags(self, refs: list[Reference]) -> None:
        ids = [r.id for r in refs]
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        rows = self.db.query(
            f"SELECT rt.ref_id, t.name FROM ref_tags rt JOIN tags t ON t.id = rt.tag_id"
            f" WHERE rt.ref_id IN ({marks}) ORDER BY t.name", ids)
        bucket: dict[int, list[str]] = {}
        for r in rows:
            bucket.setdefault(int(r["ref_id"]), []).append(r["name"])
        for r in refs:
            r.tags = bucket.get(r.id, [])

    def years(self) -> list[tuple[str, int]]:
        rows = self.db.query(
            "SELECT year, COUNT(*) AS c FROM refs WHERE year <> '' GROUP BY year"
            " ORDER BY year DESC"
        )
        return [(r["year"], int(r["c"])) for r in rows]

    def authors_top(self, limit: int = 24) -> list[tuple[str, int]]:
        counter: dict[str, int] = {}
        for row in self.db.query("SELECT authors FROM refs WHERE authors <> ''"):
            for a in re.split(r"\s+and\s+|;", row["authors"]):
                a = a.strip()
                if a:
                    counter[a] = counter.get(a, 0) + 1
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    def venues_top(self, limit: int = 20) -> list[tuple[str, int]]:
        counter: dict[str, int] = {}
        for row in self.db.query("SELECT container FROM refs WHERE container <> ''"):
            c = row["container"].strip()
            if c:
                counter[c] = counter.get(c, 0) + 1
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    # ================================================================== #
    # 增删改
    # ================================================================== #
    _FIELDS = ("citekey", "entry_type", "title", "authors", "year", "container",
               "publisher", "volume", "issue", "pages", "doi", "url", "abstract",
               "keywords", "language", "note", "read_state", "rating", "is_starred",
               "extra_json")

    def create(self, data: dict, tags: list[str] | None = None) -> Reference:
        row = {k: (data.get(k) if data.get(k) is not None else "") for k in self._FIELDS}
        row["entry_type"] = row["entry_type"] or "article"
        row["read_state"] = int(row["read_state"] or 0)
        row["rating"] = int(row["rating"] or 0)
        row["is_starred"] = 1 if row["is_starred"] else 0
        row["extra_json"] = row["extra_json"] or "{}"
        if not row["citekey"]:
            row["citekey"] = make_citekey(row["authors"], row["year"], row["title"])
        stamp = now_iso()
        row["added_at"] = stamp
        row["updated_at"] = stamp
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        rid = int(self.db.execute(
            f"INSERT INTO refs({cols}) VALUES ({marks})", list(row.values())).lastrowid)
        if tags:
            self.set_tags(rid, tags)
        return self.get(rid)  # type: ignore[return-value]

    def update(self, ref_id: int, data: dict) -> None:
        sets, params = [], []
        for k, v in data.items():
            if k not in self._FIELDS:
                continue
            if k in ("read_state", "rating"):
                v = int(v or 0)
            if k == "is_starred":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            params.append(v)
        if not sets:
            return
        sets.append("updated_at = ?")
        params += [now_iso(), ref_id]
        self.db.execute(f"UPDATE refs SET {', '.join(sets)} WHERE id = ?", params)

    def set_read_state(self, ref_id: int, state: int) -> None:
        self.db.execute(
            "UPDATE refs SET read_state = ?, updated_at = ? WHERE id = ?",
            (int(state), now_iso(), ref_id))

    def set_starred(self, ref_id: int, value: bool) -> None:
        self.db.execute(
            "UPDATE refs SET is_starred = ?, updated_at = ? WHERE id = ?",
            (1 if value else 0, now_iso(), ref_id))

    def delete(self, ref_id: int) -> list[str]:
        # 只查一次附件（旧写法把 attachments() 调了两遍，白跑一次查询）
        rels: list[str] = []
        for a in self.attachments(ref_id):
            rels += [a.rel_path, a.thumb_rel_path]
        self.db.execute("DELETE FROM refs WHERE id = ?", (ref_id,))
        return [r for r in rels if r]

    def set_tags(self, ref_id: int, names: list[str]) -> None:
        self.db.execute("DELETE FROM ref_tags WHERE ref_id = ?", (ref_id,))
        for nm in names:
            nm = nm.strip()
            if not nm:
                continue
            tid = self._ensure_tag(nm)
            self.db.execute(
                "INSERT OR IGNORE INTO ref_tags(ref_id, tag_id) VALUES (?,?)", (ref_id, tid))

    def _ensure_tag(self, name: str) -> int:
        row = self.db.query_one("SELECT id FROM tags WHERE name = ?", (name,))
        if row:
            return int(row["id"])
        return int(self.db.execute(
            "INSERT INTO tags(name, color) VALUES (?,?)", (name, "#6E7FA8")).lastrowid)

    # ================================================================== #
    # 附件
    # ================================================================== #
    def attachments(self, ref_id: int) -> list[Asset]:
        rows = self.db.query(
            "SELECT * FROM assets WHERE ref_id = ? ORDER BY position, id", (ref_id,))
        return [Asset.from_row(r) for r in rows]

    def attach(self, ref_id: int, info: dict, kind: str | None = None) -> Asset:
        pos = self.db.query_one(
            "SELECT COALESCE(MAX(position),-1)+1 AS p FROM assets WHERE ref_id = ?", (ref_id,))
        fields = {
            "note_id": None,
            "ref_id": ref_id,
            "kind": kind or info.get("kind", "document"),
            "filename": info.get("filename", ""),
            "rel_path": info.get("rel_path", ""),
            "thumb_rel_path": info.get("thumb_rel_path", ""),
            "mime": info.get("mime", ""),
            "size": int(info.get("size", 0) or 0),
            "width": int(info.get("width", 0) or 0),
            "height": int(info.get("height", 0) or 0),
            "duration_ms": 0,
            "caption": info.get("caption", ""),
            "position": int(pos["p"]) if pos else 0,
            "created_at": now_iso(),
        }
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" * len(fields))
        aid = int(self.db.execute(
            f"INSERT INTO assets({cols}) VALUES ({marks})", list(fields.values())).lastrowid)
        return Asset.from_row(self.db.query_one("SELECT * FROM assets WHERE id = ?", (aid,)))

    def detach(self, asset_id: int) -> list[str]:
        row = self.db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
        if not row:
            return []
        self.db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        return [r for r in (row["rel_path"], row["thumb_rel_path"]) if r]


# --------------------------------------------------------------------------- #
# 引用格式化辅助
# --------------------------------------------------------------------------- #
def make_citekey(authors: str, year: str, title: str) -> str:
    first = ""
    for a in re.split(r"\s+and\s+|;|,", authors or ""):
        a = a.strip()
        if a:
            first = a
            break
    surname = re.sub(r"[^A-Za-z\u4e00-\u9fff]", "", first)[:12].lower()
    word = ""
    for w in re.findall(r"[A-Za-z\u4e00-\u9fff]{3,}", title or ""):
        if w.lower() not in {"the", "and", "for", "with", "a", "an", "of", "on", "in", "using", "based"}:
            word = w.lower()
            break
    return f"{surname or 'ref'}{year or ''}{word}".lower()


# --------------------------------------------------------------------------- #
# BibTeX
# --------------------------------------------------------------------------- #
_BIB_TYPE_MAP = {
    "article": "article", "inproceedings": "inproceedings", "conference": "inproceedings",
    "book": "book", "inbook": "incollection", "incollection": "incollection",
    "phdthesis": "phdthesis", "mastersthesis": "mastersthesis", "techreport": "techreport",
    "misc": "misc", "online": "misc", "electronic": "misc", "patent": "patent",
    "standard": "standard", "dataset": "dataset", "unpublished": "misc", "manual": "misc",
}

_LATEX_ESC = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}",
}


def _strip_braces(value: str) -> str:
    value = value.strip()
    # 去掉最外层成对花括号
    while len(value) >= 2 and value[0] == "{" and value[-1] == "}":
        depth = 0
        ok = True
        for i, ch in enumerate(value):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and i != len(value) - 1:
                    ok = False
                    break
        if not ok:
            break
        value = value[1:-1].strip()
    return value


def _unescape_latex(s: str) -> str:
    s = re.sub(r"\\([&%$#_{}])", r"\1", s)
    s = re.sub(r"\\['`^\"~=.\-uvHtcdb]\{?(\w)\}?", r"\1", s)
    s = re.sub(r"\\emph\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\textit\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\textbf\{([^}]*)\}", r"\1", s)
    s = s.replace("~", " ").replace(r"\&", "&")
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_bibtex(text: str) -> list[dict]:
    """解析 .bib 文本，返回字段字典列表。宽容解析，遇到坏条目跳过。"""
    entries: list[dict] = []
    i, n = 0, len(text)
    strings: dict[str, str] = {}
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@\s*([A-Za-z]+)\s*[{(]", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        start = at + m.end()
        # 扫描到配对的右括号
        depth, j = 1, start
        while j < n and depth > 0:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == '"' and depth == 1:
                j += 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    j += 1
            j += 1
        body = text[start : max(start, j - 1)]
        i = j

        if etype == "comment":
            continue
        if etype == "string":
            k, _, v = body.partition("=")
            strings[k.strip().lower()] = _strip_braces(v)
            continue
        if etype == "preamble":
            continue

        head = _split_top_level(body, ",", 1)
        key = head[0].strip()
        rest = head[1] if len(head) > 1 else ""
        fields = _parse_fields(rest, strings)
        if not fields:
            continue
        entry = _map_bib_entry(fields, etype)
        entry["citekey"] = key
        entries.append(entry)
    return entries


def _split_top_level(s: str, sep: str, maxsplit: int = -1) -> list[str]:
    parts: list[str] = []
    depth = 0
    in_quote = False
    cur = []
    count = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '"' and depth == 0:
            in_quote = not in_quote
            cur.append(ch)
        elif ch == "\\" and i + 1 < len(s):
            cur.append(ch)
            i += 1
            cur.append(s[i])
        elif not in_quote and ch == "{":
            depth += 1
            cur.append(ch)
        elif not in_quote and ch == "}":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0 and not in_quote and (maxsplit < 0 or count < maxsplit):
            parts.append("".join(cur))
            cur = []
            count += 1
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _parse_fields(rest: str, strings: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in _split_top_level(rest, ","):
        if not chunk.strip():
            continue
        name, eq, value = chunk.partition("=")
        if not eq:
            continue
        name = name.strip().lower()
        value = _resolve_bib_value(value.strip(), strings)
        if name and value:
            out[name] = value
    return out


def _resolve_bib_value(raw: str, strings: dict[str, str]) -> str:
    # 处理 a # b 拼接
    pieces = _split_top_level(raw, "#")
    resolved = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if piece.startswith('"') and piece.endswith('"') and len(piece) > 1:
            resolved.append(piece[1:-1])
        elif piece.startswith("{"):
            resolved.append(_strip_braces(piece))
        elif piece.lower() in strings:
            resolved.append(strings[piece.lower()])
        elif re.fullmatch(r"\d+", piece):
            resolved.append(piece)
        else:
            resolved.append(_strip_braces(piece) if piece.startswith("{") else piece)
    return _unescape_latex("".join(resolved))


def _map_bib_entry(f: dict[str, str], bib_type: str = "article") -> dict:
    def g(*names: str) -> str:
        for nm in names:
            v = f.get(nm)
            if v:
                return v
        return ""

    year = g("year", "date")
    m = re.search(r"\d{4}", year or "")
    entry = {
        "entry_type": _BIB_TYPE_MAP.get((bib_type or "article").lower(), "article"),
        "title": g("title"),
        "authors": g("author", "editor"),
        "year": m.group(0) if m else "",
        "container": g("journal", "journaltitle", "booktitle"),
        "publisher": g("publisher", "school", "institution", "organization"),
        "volume": g("volume"),
        "issue": g("number", "issue"),
        "pages": g("pages").replace("--", "-"),
        "doi": g("doi"),
        "url": g("url"),
        "abstract": g("abstract"),
        "keywords": g("keywords", "keyword"),
        "language": g("language", "langid"),
        "note": g("note"),
    }
    entry["authors"] = re.sub(r"\s+and\s+", " and ", entry["authors"])
    return entry


def bibtex_for(ref: Reference) -> str:
    btype = ref.entry_type if ref.entry_type in _BIB_TYPE_MAP.values() else "article"
    key = ref.citekey or make_citekey(ref.authors, ref.year, ref.title)
    lines = []

    def esc(s: str) -> str:
        for k, v in _LATEX_ESC.items():
            s = s.replace(k, v)
        return s

    pairs = [
        ("title", ref.title),
        ("author", ref.authors.replace(",", " and") if "," in (ref.authors or "") and " and " not in (ref.authors or "") else ref.authors),
        ("year", ref.year),
    ]
    venue_field = "journal" if btype == "article" else "booktitle"
    pairs.append((venue_field, ref.container))
    pairs.append(("publisher", ref.publisher))
    pairs.append(("volume", ref.volume))
    pairs.append(("number", ref.issue))
    pairs.append(("pages", ref.pages))
    pairs.append(("doi", ref.doi))
    pairs.append(("url", ref.url))
    pairs.append(("keywords", ref.keywords))
    pairs.append(("language", ref.language))
    pairs.append(("note", ref.note))
    pairs.append(("abstract", ref.abstract))

    for name, value in pairs:
        if value:
            lines.append(f"  {name} = {{{esc(str(value))}}},")
    body = "\n".join(lines).rstrip(",")
    return f"@{btype}{{{key},\n{body}\n}}"


def export_bibtex(refs: list[Reference]) -> str:
    return "\n\n".join(bibtex_for(r) for r in refs) + "\n"


# --------------------------------------------------------------------------- #
# DOI 抓取（Crossref）
# --------------------------------------------------------------------------- #
_CROSSREF = "https://api.crossref.org/works/"


def normalize_doi(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^\s*(https?://)?(dx\.)?doi\.org/", "", text, flags=re.I)
    text = re.sub(r"^\s*doi:\s*", "", text, flags=re.I)
    return text.strip()


def fetch_doi_metadata(doi: str, timeout: float = 12.0) -> dict:
    """通过 Crossref 抓取 DOI 元数据。返回字段字典；失败抛异常。"""
    doi = normalize_doi(doi)
    if not doi:
        raise ValueError("DOI 为空")
    url = _CROSSREF + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NovaNote/1.0 (academic reference manager; mailto:user@example.com)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f"DOI 未找到：{doi}") from e
        raise RuntimeError(f"Crossref 返回错误 {e.code}") from e
    except Exception as e:
        raise RuntimeError(f"网络请求失败：{e}") from e

    msg = payload.get("message", {}) or {}
    return crossref_to_fields(msg)


def crossref_to_fields(msg: dict) -> dict:
    def first(v):
        if isinstance(v, list):
            return v[0] if v else ""
        return v or ""

    authors = []
    for a in msg.get("author", []) or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        name = (a.get("name") or "").strip()
        if family or given:
            authors.append(f"{given} {family}".strip())
        elif name:
            authors.append(name)

    year = ""
    for k in ("published-print", "published-online", "issued", "created"):
        parts = ((msg.get(k) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            year = str(parts[0])
            break

    types = {
        "journal-article": "article", "proceedings-article": "inproceedings",
        "book": "book", "book-chapter": "incollection", "monograph": "book",
        "dissertation": "phdthesis", "report": "techreport", "posted-content": "misc",
        "dataset": "dataset", "standard": "standard",
    }
    keywords = msg.get("subject") or []
    return {
        "entry_type": types.get(msg.get("type", ""), "article"),
        "title": _unescape_latex(first(msg.get("title", ""))),
        "authors": " and ".join(authors),
        "year": year,
        "container": _unescape_latex(first(msg.get("container-title", ""))),
        "publisher": msg.get("publisher", "") or "",
        "volume": msg.get("volume", "") or "",
        "issue": msg.get("issue", "") or "",
        "pages": msg.get("page", "") or "",
        "doi": msg.get("DOI", "") or "",
        "url": msg.get("URL", "") or "",
        "abstract": _clean_abstract(msg.get("abstract", "") or ""),
        "keywords": "; ".join(keywords),
        "language": msg.get("language", "") or "",
        "citekey": make_citekey(" and ".join(authors), year, _unescape_latex(first(msg.get("title", "")))),
    }


def _clean_abstract(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"<[^>]+>", " ", raw)
    s = re.sub(r"^\s*(Abstract|ABSTRACT)\s*[:\-]?\s*", "", s)
    s = _unescape_latex(s)
    return re.sub(r"\s+", " ", s).strip()
