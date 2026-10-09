"""媒体查看器：图片灯箱（缩放/旋转）与视频播放器。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..models import Asset
from ..services.assets import format_duration, load_pixmap
from ..theme import tokens
from ..widgets.common import IconButton

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_MEDIA = True
except Exception:  # pragma: no cover
    HAS_MEDIA = False


def open_in_system(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class ImageCanvas(QScrollArea):
    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._zoom = 1.0
        self._fit = True
        self._rotation = 0
        self._source = QPixmap()
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QFrame.NoFrame)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setWidget(self.label)

    def set_image(self, path: Path) -> None:
        self._source = load_pixmap(path)
        self._zoom = 1.0
        self._fit = True
        self._rotation = 0
        self._render()

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / 1.25)

    def zoom_reset(self) -> None:
        self._zoom = 1.0
        self._fit = False
        self._render()

    def fit(self) -> None:
        self._fit = True
        self._zoom = 1.0
        self._render()

    def rotate(self, deg: int = 90) -> None:
        self._rotation = (self._rotation + deg) % 360
        self._render()

    def _set_zoom(self, value: float) -> None:
        self._zoom = max(0.06, min(12.0, value))
        self._fit = False
        self._render()

    def _render(self) -> None:
        if self._source.isNull():
            self.label.setText("无法预览此图片")
            return
        px = self._source
        if self._rotation:
            px = px.transformed(QTransform().rotate(self._rotation), Qt.SmoothTransformation)
        if self._fit:
            avail = self.viewport().size()
            px = px.scaled(avail, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        elif self._zoom != 1.0:
            px = px.scaled(
                int(px.width() * self._zoom), int(px.height() * self._zoom),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(px)
        self.label.resize(px.size())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self._render()

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self._set_zoom(self._zoom * (1.12 if delta > 0 else 0.89))
            event.accept()
            return
        super().wheelEvent(event)


class VideoPlayer(QWidget):
    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._duration = 0
        self._scrubbing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if HAS_MEDIA:
            self.video = QVideoWidget()
            self.video.setStyleSheet("background: #10141A; border-radius: 8px;")
            lay.addWidget(self.video, 1)
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.video)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.85)
            self.player.setAudioOutput(self.audio)
            self.player.positionChanged.connect(self._on_position)
            self.player.durationChanged.connect(self._on_duration)
            self.player.playbackStateChanged.connect(self._on_state)
            self.player.mediaStatusChanged.connect(self._on_status)
        else:
            self.video = None
            self.player = None
            self.audio = None
            ph = QLabel("当前环境未安装 Qt Multimedia 组件，无法内嵌播放。\n可点击「用系统播放器打开」。")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("background: #10141A; color: #93A3B4; border-radius: 8px;")
            lay.addWidget(ph, 1)

        # 控制条
        bar = QFrame()
        self.bar = bar
        bar.setObjectName("Card")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(10)

        self.btn_play = IconButton("play", theme, 34, 18, tip="播放 / 暂停（空格）")
        self.btn_play.clicked.connect(self.toggle)
        bl.addWidget(self.btn_play)

        self.lbl_pos = QLabel("00:00")
        self.lbl_pos.setProperty("role", "muted")
        self.lbl_pos.setFixedWidth(52)
        self.lbl_pos.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bl.addWidget(self.lbl_pos)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderPressed.connect(self._on_scrub_start)
        self.slider.sliderReleased.connect(self._on_scrub_end)
        self.slider.sliderMoved.connect(self._on_scrub_move)
        bl.addWidget(self.slider, 1)

        self.lbl_dur = QLabel("00:00")
        self.lbl_dur.setProperty("role", "muted")
        self.lbl_dur.setFixedWidth(52)
        bl.addWidget(self.lbl_dur)

        self.btn_vol = IconButton("volume", theme, 30, 17, tip="音量")
        bl.addWidget(self.btn_vol)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(85)
        self.vol.setFixedWidth(84)
        self.vol.valueChanged.connect(self._on_volume)
        bl.addWidget(self.vol)

        lay.addWidget(bar)

    # ---- 控制 ---- #
    def load(self, path: Path) -> None:
        if not self.player:
            return
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def toggle(self) -> None:
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())

    def _on_status(self, status) -> None:
        if not self.player:
            return
        if status == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)
            self.btn_play._name = "play"
            self.btn_play.refresh(self._theme)

    def _on_state(self, state) -> None:
        if not self.player:
            return
        playing = state == QMediaPlayer.PlayingState
        self.btn_play._name = "pause" if playing else "play"
        self.btn_play.refresh(self._theme)

    def _on_duration(self, ms: int) -> None:
        self._duration = ms
        self.lbl_dur.setText(format_duration(ms))

    def _on_position(self, ms: int) -> None:
        if self._scrubbing or not self._duration:
            return
        self.lbl_pos.setText(format_duration(ms))
        self.slider.blockSignals(True)
        self.slider.setValue(int(ms / self._duration * 1000))
        self.slider.blockSignals(False)

    def _on_scrub_start(self) -> None:
        self._scrubbing = True

    def _on_scrub_end(self) -> None:
        self._scrubbing = False
        self._seek(self.slider.value())

    def _on_scrub_move(self, value: int) -> None:
        if self._duration:
            self.lbl_pos.setText(format_duration(int(value / 1000 * self._duration)))

    def _seek(self, value: int) -> None:
        if self.player and self._duration:
            self.player.setPosition(int(value / 1000 * self._duration))

    def _on_volume(self, value: int) -> None:
        if self.audio:
            self.audio.setVolume(value / 100.0)

    def seek_relative(self, seconds: int) -> None:
        if self.player:
            self.player.setPosition(max(0, self.player.position() + seconds * 1000))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for b in (self.btn_play, self.btn_vol):
            b.refresh(theme)


class MediaViewer(QWidget):
    """媒体详情页：图片灯箱 / 视频播放。"""

    closeRequested = Signal()
    openExternal = Signal()
    deleteRequested = Signal()
    revealRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._asset: Asset | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 头部 ---- #
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 12, 16, 10)
        hl.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(18, 18)
        hl.addWidget(self.icon_label)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel("")
        self.title.setProperty("role", "h2")
        self.meta = QLabel("")
        self.meta.setProperty("role", "muted")
        col.addWidget(self.title)
        col.addWidget(self.meta)
        hl.addLayout(col, 1)

        self.btn_zoom_out = IconButton("zoom-out", theme, 30, 17, tip="缩小")
        self.btn_zoom_in = IconButton("zoom-in", theme, 30, 17, tip="放大")
        self.btn_fit = IconButton("fullscreen", theme, 30, 17, tip="适应窗口")
        self.btn_rotate = IconButton("rotate", theme, 30, 17, tip="旋转 90°")
        self.btn_save = IconButton("download", theme, 30, 17, tip="另存为")
        self.btn_external = IconButton("export", theme, 30, 17, tip="用系统程序打开")
        self.btn_reveal = IconButton("folder", theme, 30, 17, tip="在文件夹中显示")
        self.btn_delete = IconButton("trash", theme, 30, 17, tip="从笔记中移除")
        self.btn_close = IconButton("close", theme, 30, 17, tip="关闭（Esc）")
        for b in (self.btn_zoom_out, self.btn_zoom_in, self.btn_fit, self.btn_rotate):
            hl.addWidget(b)
        hl.addWidget(_vsep(theme))
        for b in (self.btn_save, self.btn_external, self.btn_reveal, self.btn_delete):
            hl.addWidget(b)
        hl.addWidget(_vsep(theme))
        hl.addWidget(self.btn_close)
        root.addWidget(head)

        # ---- 内容 ---- #
        self.stack = QStackedWidget()
        self.image_canvas = ImageCanvas(theme)
        self.video_player = VideoPlayer(theme)
        self.other = QLabel("此类型的附件暂不支持预览\n可点击右上角按钮用系统程序打开")
        self.other.setAlignment(Qt.AlignCenter)
        self.other.setProperty("role", "muted")
        for w in (self.image_canvas, self.video_player, self.other):
            self.stack.addWidget(w)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(18, 0, 18, 18)
        wl.addWidget(self.stack)
        root.addWidget(wrap, 1)

        # ---- 接线 ---- #
        self.btn_close.clicked.connect(self._on_close)
        self.btn_zoom_in.clicked.connect(self.image_canvas.zoom_in)
        self.btn_zoom_out.clicked.connect(self.image_canvas.zoom_out)
        self.btn_fit.clicked.connect(self.image_canvas.fit)
        self.btn_rotate.clicked.connect(lambda: self.image_canvas.rotate(90))
        self.btn_external.clicked.connect(self.openExternal.emit)
        self.btn_reveal.clicked.connect(self.revealRequested.emit)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        self.btn_save.clicked.connect(self.openExternal.emit)

    # ------------------------------------------------------------------ #
    def show_asset(self, asset: Asset, abs_path: Path) -> None:
        self._asset = asset
        t = tokens(self._theme)
        is_image = asset.kind == "image"
        is_video = asset.kind == "video"

        self.icon_label.setPixmap(icons.render_pixmap(
            "image" if is_image else ("video" if is_video else "paperclip"), t["blue"], 18))
        self.title.setText(asset.filename)
        bits = [asset.size_text, asset.kind.upper()]
        if asset.width and asset.height:
            bits.append(f"{asset.width}×{asset.height}")
        if asset.duration_ms:
            bits.append(format_duration(asset.duration_ms))
        self.meta.setText("  ·  ".join(bits))

        for b, visible in ((self.btn_zoom_in, is_image), (self.btn_zoom_out, is_image),
                           (self.btn_fit, is_image), (self.btn_rotate, is_image)):
            b.setVisible(visible)

        if is_image:
            self.stack.setCurrentWidget(self.image_canvas)
            self.image_canvas.set_image(abs_path)
        elif is_video and HAS_MEDIA:
            self.stack.setCurrentWidget(self.video_player)
            self.video_player.load(abs_path)
        else:
            self.stack.setCurrentWidget(self.other)

    def close_media(self) -> None:
        self.video_player.stop()

    def _on_close(self) -> None:
        self.close_media()
        self.closeRequested.emit()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._on_close()
            return
        if event.key() == Qt.Key_Space and self.stack.currentWidget() is self.video_player:
            self.video_player.toggle()
            return
        if event.key() == Qt.Key_Left and self.stack.currentWidget() is self.video_player:
            self.video_player.seek_relative(-5)
            return
        if event.key() == Qt.Key_Right and self.stack.currentWidget() is self.video_player:
            self.video_player.seek_relative(5)
            return
        super().keyPressEvent(event)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for b in (self.btn_zoom_out, self.btn_zoom_in, self.btn_fit, self.btn_rotate,
                  self.btn_save, self.btn_external, self.btn_reveal, self.btn_delete,
                  self.btn_close):
            b.refresh(theme)
        self.video_player.refresh(theme)
        if self._asset:
            t = tokens(theme)
            self.icon_label.setPixmap(icons.render_pixmap(
                {"image": "image", "video": "video"}.get(self._asset.kind, "paperclip"),
                t["blue"], 18))


def _vsep(theme: str) -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setFixedHeight(18)
    f.setStyleSheet(f"background: {tokens(theme)['border']};")
    return f
