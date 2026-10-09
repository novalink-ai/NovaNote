"""媒体资源服务：导入附件、生成缩略图、读取图像/视频元数据。

附件一律复制进工作空间 assets/ 目录并按年月归档，保证工作空间自包含、可整体搬迁。
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QImageReader, QPixmap

from ..database import now_iso

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg", ".heic", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
DOC_EXT = {".pdf", ".epub", ".djvu", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".rtf", ".bib"}

KIND_BY_EXT: dict[str, str] = {}
for _e in IMAGE_EXT:
    KIND_BY_EXT[_e] = "image"
for _e in VIDEO_EXT:
    KIND_BY_EXT[_e] = "video"
for _e in AUDIO_EXT:
    KIND_BY_EXT[_e] = "audio"
for _e in DOC_EXT:
    KIND_BY_EXT[_e] = "document"


def kind_for(path: str | Path) -> str:
    return KIND_BY_EXT.get(Path(path).suffix.lower(), "file")


def human_size(n: int) -> str:
    v = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def file_digest(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


class MediaService:
    """所有路径操作均相对工作空间根目录（rel_path 使用 '/' 分隔）。"""

    def __init__(self, workspace):
        self.ws = workspace

    # ------------------------------------------------------------------ #
    # 路径换算
    # ------------------------------------------------------------------ #
    def abs_path(self, rel_path: str) -> Path:
        if not rel_path:
            return self.ws.path
        p = Path(rel_path)
        return p if p.is_absolute() else (self.ws.path / p)

    def rel_of(self, abs_path: str | Path) -> str:
        try:
            return Path(abs_path).resolve().relative_to(self.ws.path).as_posix()
        except ValueError:
            return str(abs_path)

    # ------------------------------------------------------------------ #
    # 导入
    # ------------------------------------------------------------------ #
    def import_file(self, src: str | Path, subdir: str | None = None) -> dict:
        """复制文件进工作空间，返回可直接落库的字段字典。"""
        src = Path(src)
        if not src.is_file():
            raise FileNotFoundError(src)

        digest = file_digest(src)
        ext = src.suffix.lower()
        kind = kind_for(src)
        rel_dir = Path("assets") / (subdir or time.strftime("%Y/%m"))
        dest_dir = self.ws.path / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        stem = _safe_stem(src.stem)
        filename = f"{stem}_{digest[:8]}{ext}"
        dest = dest_dir / filename
        if not dest.exists():
            shutil.copy2(src, dest)
        rel = (rel_dir / filename).as_posix()

        info = {
            "kind": kind,
            "filename": src.name,
            "rel_path": rel,
            "thumb_rel_path": "",
            "mime": mimetypes.guess_type(src.name)[0] or "",
            "size": dest.stat().st_size,
            "width": 0,
            "height": 0,
            "duration_ms": 0,
            "caption": "",
            "created_at": now_iso(),
        }

        if kind == "image":
            w, h = image_size(dest)
            info["width"], info["height"] = w, h
            thumb = self.make_image_thumb(dest, rel)
            info["thumb_rel_path"] = thumb or ""
        elif kind == "video":
            thumb, duration = grab_video_thumb(dest)
            info["duration_ms"] = duration
            if thumb is not None and not thumb.isNull():
                info["width"], info["height"] = thumb.width(), thumb.height()
                info["thumb_rel_path"] = self._save_thumb(thumb, rel) or ""

        return info

    def import_many(self, paths: list[str | Path]) -> list[dict]:
        out = []
        for p in paths:
            try:
                out.append(self.import_file(p))
            except Exception:
                continue
        return out

    def import_qimage(self, img: QImage, name: str = "粘贴图片") -> dict | None:
        """把内存中的图像（如剪贴板截图）落盘为工作空间附件。"""
        if img is None or img.isNull():
            return None
        rel_dir = Path("assets") / time.strftime("%Y/%m")
        dest_dir = self.ws.path / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        ext = ".png" if img.hasAlphaChannel() else ".jpg"
        filename = f"{_safe_stem(name)}_{stamp}{ext}"
        dest = dest_dir / filename
        if ext == ".jpg":
            rgb = img.convertToFormat(QImage.Format_RGB888) if img.format() != QImage.Format_RGB888 else img
            ok = rgb.save(str(dest), "JPG", 92)
            if not ok:
                dest = dest.with_suffix(".png")
                img.save(str(dest), "PNG")
        else:
            img.save(str(dest), "PNG")

        if not dest.exists():
            return None
        rel = (rel_dir / dest.name).as_posix()
        thumb = self._save_thumb(img, rel)
        return {
            "kind": "image",
            "filename": f"{name}{dest.suffix}",
            "rel_path": rel,
            "thumb_rel_path": thumb or "",
            "mime": mimetypes.guess_type(dest.name)[0] or "image/png",
            "size": dest.stat().st_size,
            "width": img.width(),
            "height": img.height(),
            "duration_ms": 0,
            "caption": "",
            "created_at": now_iso(),
        }

    def copy_into_workspace(self, src: str | Path, subdir: str = "imports") -> str:
        src = Path(src)
        if not src.is_file():
            raise FileNotFoundError(src)
        rel_dir = Path("assets") / subdir
        dest_dir = self.ws.path / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        i = 1
        while dest.exists():
            dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
            i += 1
        shutil.copy2(src, dest)
        return (rel_dir / dest.name).as_posix()

    # ------------------------------------------------------------------ #
    # 缩略图
    # ------------------------------------------------------------------ #
    def make_image_thumb(self, abs_image: Path, rel_source: str) -> str | None:
        reader = QImageReader(str(abs_image))
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            return None
        return self._save_thumb(img, rel_source)

    def _save_thumb(self, img: QImage, rel_source: str) -> str | None:
        max_side = 720
        scaled = img.scaled(
            QSize(max_side, max_side), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        name = hashlib.sha1(rel_source.encode("utf-8")).hexdigest()[:16] + ".jpg"
        out = self.ws.thumbs_dir / name
        out.parent.mkdir(parents=True, exist_ok=True)
        if scaled.hasAlphaChannel():
            rgb = QImage(scaled.size(), QImage.Format_RGB32)
            rgb.fill(Qt.white)
            from PySide6.QtGui import QPainter

            p = QPainter(rgb)
            p.drawImage(0, 0, scaled)
            p.end()
            scaled = rgb
        if scaled.save(str(out), "JPG", 86):
            return (Path("assets") / "thumbs" / name).as_posix()
        return None

    # ------------------------------------------------------------------ #
    # 清理
    # ------------------------------------------------------------------ #
    def delete_asset_files(self, rel_paths: list[str]) -> None:
        for rel in rel_paths:
            if not rel:
                continue
            p = self.abs_path(rel)
            try:
                if p.is_file() and self.ws.assets_dir in p.parents:
                    p.unlink()
            except OSError:
                pass

    def orphan_files(self) -> list[Path]:
        """未被数据库引用的附件（用于"清理未使用文件"）。"""
        used = set()
        for row in self.ws.db.query("SELECT rel_path, thumb_rel_path FROM assets"):
            if row["rel_path"]:
                used.add(row["rel_path"])
            if row["thumb_rel_path"]:
                used.add(row["thumb_rel_path"])
        out = []
        if self.ws.assets_dir.exists():
            for p in self.ws.assets_dir.rglob("*"):
                if p.is_file() and self.rel_of(p) not in used:
                    out.append(p)
        return out


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _safe_stem(stem: str) -> str:
    keep = []
    for ch in stem[:40]:
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " \t":
            keep.append("_")
    cleaned = "".join(keep).strip("_")
    return cleaned or "file"


def image_size(path: str | Path) -> tuple[int, int]:
    reader = QImageReader(str(path))
    size = reader.size()
    if size.isValid():
        return size.width(), size.height()
    img = QImage(str(path))
    return (img.width(), img.height()) if not img.isNull() else (0, 0)


def load_pixmap(path: str | Path, max_side: int | None = None) -> QPixmap:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if max_side:
        s = reader.size()
        if s.isValid() and max(s.width(), s.height()) > max_side:
            reader.setScaledSize(
                s.scaled(QSize(max_side, max_side), Qt.KeepAspectRatio)
            )
    img = reader.read()
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def grab_video_thumb(path: str | Path, at_ms: int = 1200, timeout_ms: int = 2600):
    """抓取视频首帧作为缩略图。返回 (QImage|None, duration_ms)。

    依赖 Qt Multimedia 后端；若后端缺失或超时，静默返回 (None, 0)。
    """
    try:
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtVideo import QVideoSink
    except Exception:
        return None, 0

    player = None
    try:
        player = QMediaPlayer()
        sink = QVideoSink()
        player.setVideoSink(sink)
        state: dict = {"img": None, "duration": 0}
        loop = QEventLoop()

        def on_frame(frame):
            if state["img"] is None and frame.isValid():
                img = frame.toImage()
                if not img.isNull():
                    state["img"] = img
                    state["duration"] = max(state["duration"], int(player.duration()))
                    player.stop()
                    QTimer.singleShot(0, loop.quit)

        def on_status(status):
            st = int(status)
            if st == int(QMediaPlayer.LoadedMedia):
                state["duration"] = max(state["duration"], int(player.duration()))
                player.setPosition(at_ms)
                player.play()
            elif st in (int(QMediaPlayer.InvalidMedia), int(QMediaPlayer.NoMedia)):
                QTimer.singleShot(0, loop.quit)

        sink.videoFrameChanged.connect(on_frame)
        player.mediaStatusChanged.connect(on_status)
        player.errorOccurred.connect(lambda *_: QTimer.singleShot(0, loop.quit))
        player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

        if state["img"] is not None:
            frame_img = state["img"]
            if frame_img.width() > 1280:
                frame_img = frame_img.scaledToWidth(1280, Qt.SmoothTransformation)
            return frame_img, state["duration"]
        return None, state["duration"]
    except Exception:
        return None, 0
    finally:
        if player is not None:
            try:
                player.stop()
                player.setSource(QUrl())
                player.deleteLater()
            except Exception:
                pass


def format_duration(ms: int) -> str:
    if not ms:
        return "--:--"
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_duration_short(ms: int) -> str:
    if not ms:
        return ""
    total = int(ms // 1000)
    if total < 60:
        return f"{total} 秒"
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h} 小时 {m} 分" if h else f"{m} 分钟"
