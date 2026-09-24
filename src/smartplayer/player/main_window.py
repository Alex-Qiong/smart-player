"""主界面：PySide6 + libmpv 视频窗口、控制条、字幕叠加层、TTS 配音。"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath
from PySide6.QtMultimedia import QAudioFormat, QAudioSink
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import models_dir, save_config
from ..subs.pipeline import PipelineController, SubSegment
from ..subs.translator import LANG_NAMES
from ..subs.tts import PiperTTS
from .mpv_engine import MpvEngine, find_libmpv

SUB_MODES = {"original": "原文", "translated": "译文", "bilingual": "双语"}


# ---------------- 字幕叠加层 ----------------
class SubtitleOverlay(QWidget):
    """画在视频上方的透明字幕层（Qt 自绘，支持实时更新）。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._lines: list[str] = []

    def set_segments(self, segs: list[SubSegment], mode: str) -> None:
        lines: list[str] = []
        for s in segs[:2]:
            if mode == "original":
                if s.src:
                    lines.append(s.src)
            elif mode == "translated":
                lines.append(s.tgt or s.src)
            else:  # bilingual
                if s.src:
                    lines.append(s.src)
                if s.tgt and s.tgt != s.src:
                    lines.append(s.tgt)
        if lines != self._lines:
            self._lines = lines
            self.update()

    def paintEvent(self, event):  # noqa: ANN001, ANN202, N802
        if not self._lines:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont("Microsoft YaHei", 20, QFont.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        # 自动换行
        wrapped: list[str] = []
        max_w = int(self.width() * 0.9)
        for line in self._lines:
            buf = ""
            for ch in line:
                if fm.horizontalAdvance(buf + ch) > max_w and buf:
                    wrapped.append(buf)
                    buf = ch
                else:
                    buf += ch
            if buf:
                wrapped.append(buf)
        line_h = fm.height() + 8
        total_h = line_h * len(wrapped)
        y = self.height() - total_h - 40
        for line in wrapped:
            w = fm.horizontalAdvance(line)
            x = (self.width() - w) / 2
            path = QPainterPath()
            path.addText(x, y + fm.ascent(), font, line)
            p.setPen(QColor(0, 0, 0, 220))
            p.setBrush(QColor(0, 0, 0, 220))
            stroker = QPainterPath()
            # 描边：多次偏移绘制
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                tmp = QPainterPath()
                tmp.addText(x + dx, y + dy + fm.ascent(), font, line)
                stroker = stroker.united(tmp)
            p.drawPath(stroker.united(path))
            p.setPen(QColor(255, 255, 255))
            p.setBrush(QColor(255, 255, 255))
            p.drawPath(path)
            y += line_h
        p.end()


# ---------------- TTS 配音播放 ----------------
class DubPlayer(QObject):
    finished = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._sink: QAudioSink | None = None
        self._dev = None

    def play(self, sample_rate: int, pcm: bytes) -> None:
        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(sample_rate)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._sink = QAudioSink(fmt)
        self._sink.stateChanged.connect(self._on_state)
        self._dev = self._sink.start()
        if self._dev is not None:
            self._dev.write(pcm)

    def _on_state(self, state):  # noqa: ANN001
        from PySide6.QtMultimedia import QAudio

        if state == QAudio.State.IdleState:
            self.finished.emit()
            self.stop()

    def stop(self) -> None:
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None
            self._dev = None


# ---------------- 主窗口 ----------------
class MainWindow(QMainWindow):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("SmartPlayer")
        self.resize(1100, 700)

        self.engine: MpvEngine | None = None
        self._engine_ready = False
        self.pipe = PipelineController(cfg)
        self.pipe.status.connect(self.statusBar().showMessage)
        self.tts: PiperTTS | None = None
        self.dubber = DubPlayer(self)
        self.dubber.finished.connect(self._on_dub_finished)
        self._last_dub_id = 0
        self._saved_volume = 100
        self._media: str | None = None

        self._build_ui()
        self._build_menu()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(120)

    # ---------------- 界面搭建 ----------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 视频区
        self.video_container = QWidget(central)
        self.video_container.setStyleSheet("background: black;")
        self.video_container.setMinimumSize(640, 360)
        vbox.addWidget(self.video_container, 1)

        self.video_widget = QWidget(self.video_container)
        self.video_widget.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.overlay = SubtitleOverlay(self.video_container)
        self.overlay.raise_()
        self.video_container.resizeEvent = self._on_video_resize  # type: ignore[method-assign]

        # 控制条
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self.btn_open = QPushButton("打开")
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(44)
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setFixedWidth(44)
        self.lbl_time = QLabel("00:00 / 00:00")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(100)
        bar.addWidget(self.btn_open)
        bar.addWidget(self.btn_play)
        bar.addWidget(self.btn_stop)
        bar.addWidget(self.lbl_time)
        bar.addWidget(self.slider, 1)
        bar.addWidget(QLabel("音量"))
        bar.addWidget(self.vol)
        vbox.addLayout(bar)

        # 字幕 / AI 条
        bar2 = QHBoxLayout()
        bar2.setContentsMargins(8, 0, 8, 8)
        bar2.addWidget(QLabel("字幕"))
        self.cmb_mode = QComboBox()
        for k, v in SUB_MODES.items():
            self.cmb_mode.addItem(v, k)
        self.cmb_mode.setCurrentIndex(
            list(SUB_MODES).index(self.cfg.get("sub_mode", "bilingual"))
        )
        bar2.addWidget(self.cmb_mode)

        bar2.addWidget(QLabel("源语言"))
        self.cmb_src = QComboBox()
        for code, name in LANG_NAMES.items():
            self.cmb_src.addItem(name, code)
        self._set_combo(self.cmb_src, self.cfg.get("src_lang", "auto"))
        bar2.addWidget(self.cmb_src)

        bar2.addWidget(QLabel("目标"))
        self.cmb_tgt = QComboBox()
        for code, name in LANG_NAMES.items():
            if code != "auto":
                self.cmb_tgt.addItem(name, code)
        self._set_combo(self.cmb_tgt, self.cfg.get("tgt_lang", "zh"))
        bar2.addWidget(self.cmb_tgt)

        self.chk_live = QCheckBox("实时翻译")
        self.chk_live.setChecked(bool(self.cfg.get("live_translate", True)))
        self.chk_embed = QCheckBox("优先用内嵌字幕")
        self.chk_embed.setChecked(bool(self.cfg.get("use_embedded_subs", True)))
        self.chk_tts = QCheckBox("AI 配音")
        self.chk_tts.setChecked(False)  # 默认关闭，打开时再校验模型
        bar2.addWidget(self.chk_live)
        bar2.addWidget(self.chk_embed)
        bar2.addWidget(self.chk_tts)
        bar2.addStretch(1)
        vbox.addLayout(bar2)

        # 信号
        self.btn_open.clicked.connect(self.open_file)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop_play)
        self.slider.sliderReleased.connect(self._on_seek_release)
        self.vol.valueChanged.connect(self._on_volume)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.cmb_src.currentIndexChanged.connect(self._on_lang_changed)
        self.cmb_tgt.currentIndexChanged.connect(self._on_lang_changed)
        self.chk_live.toggled.connect(self._on_live_toggled)
        self.chk_embed.toggled.connect(
            lambda v: self._save_opt("use_embedded_subs", v)
        )
        self.chk_tts.toggled.connect(self._on_tts_toggled)

        self.statusBar().showMessage("就绪")

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("文件")
        act_open = QAction("打开视频…", self)
        act_open.triggered.connect(self.open_file)
        m.addAction(act_open)
        m.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        m.addAction(act_quit)

    @staticmethod
    def _set_combo(combo: QComboBox, code: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == code:
                combo.setCurrentIndex(i)
                return

    # ---------------- 引擎 ----------------
    def showEvent(self, event):  # noqa: ANN001, ANN202, N802
        super().showEvent(event)
        if not self._engine_ready:
            self._engine_ready = True
            self._on_video_resize()
            self._init_engine()

    def _on_video_resize(self, event=None):  # noqa: ANN001, ANN202
        r = self.video_container.rect()
        self.video_widget.setGeometry(r)
        self.overlay.setGeometry(r)

    def _init_engine(self) -> None:
        try:
            self.engine = MpvEngine(
                int(self.video_widget.winId()),
                hwdec=bool(self.cfg.get("hwdec", True)),
            )
            self.engine.on_end_file(self._on_end_file)
            dll = find_libmpv()
            self.statusBar().showMessage(
                f"播放引擎就绪（{dll.name if dll else '系统 libmpv'}）",
                4000,
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "播放引擎初始化失败",
                f"{e}\n\n请运行 tools/fetch_libmpv.py 下载 libmpv-2.dll，"
                "或设置环境变量 SMARTPLAYER_LIBMPV 指向它。",
            )

    # ---------------- 播放 ----------------
    def open_file(self) -> None:
        if self.engine is None:
            self.statusBar().showMessage("播放引擎未就绪")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开视频",
            "",
            "视频文件 (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m2ts "
            "*.rmvb *.3gp *.mpg *.mpeg *.vob *.m4v *.hevc *.av1 *.vp9);;所有文件 (*)",
        )
        if not path:
            return
        self._media = path
        self._last_dub_id = 0
        self.setWindowTitle(f"SmartPlayer - {Path(path).name}")
        self.engine.play(path)
        self.pipe.start(path)

    def toggle_play(self) -> None:
        if self.engine:
            self.engine.toggle_pause()
            self.btn_play.setText("⏸" if not self.engine.paused else "▶")

    def stop_play(self) -> None:
        if self.engine:
            self.engine.stop()
        self.pipe.stop()
        self.overlay.set_segments([], self.cfg.get("sub_mode", "bilingual"))

    def _on_end_file(self) -> None:
        self.pipe.stop()

    def _on_seek_release(self) -> None:
        if not self.engine:
            return
        dur = self.engine.duration
        if dur:
            pos = self.slider.value() / 1000.0 * dur
            self.engine.seek(pos, absolute=True)
            self._last_dub_id = 0
            self.pipe.on_seek(pos)

    def _on_volume(self, v: int) -> None:
        if self.engine:
            self.engine.volume = v

    # ---------------- 选项 ----------------
    def _save_opt(self, key: str, value) -> None:  # noqa: ANN001
        self.cfg[key] = value
        save_config(self.cfg)

    def _on_mode_changed(self) -> None:
        self._save_opt("sub_mode", self.cmb_mode.currentData())

    def _on_lang_changed(self) -> None:
        self._save_opt("src_lang", self.cmb_src.currentData())
        self._save_opt("tgt_lang", self.cmb_tgt.currentData())
        self.statusBar().showMessage("语言设置已保存，重新打开文件后生效", 4000)

    def _on_live_toggled(self, on: bool) -> None:
        self._save_opt("live_translate", on)
        if not on:
            self.pipe.stop()
            self.overlay.set_segments([], self.cfg.get("sub_mode", "bilingual"))
            self.statusBar().showMessage("实时翻译已关闭")
        elif self._media and self.engine:
            self.pipe.start(self._media)

    def _on_tts_toggled(self, on: bool) -> None:
        if not on:
            self._save_opt("tts_enabled", False)
            self.dubber.stop()
            return
        if self.tts is None:
            self.tts = PiperTTS(
                voice_id=self.cfg.get("tts_voice", "zh_CN-huayan-medium"),
                models_dir=models_dir(),
            )
        ok, msg = self.tts.available()
        if not ok:
            self.chk_tts.blockSignals(True)
            self.chk_tts.setChecked(False)
            self.chk_tts.blockSignals(False)
            self.statusBar().showMessage(msg, 8000)
            QMessageBox.information(self, "AI 配音不可用", msg)
            return
        self._save_opt("tts_enabled", True)
        self.statusBar().showMessage("AI 配音已开启", 3000)

    # ---------------- 主循环 ----------------
    def _tick(self) -> None:
        if not self.engine:
            return
        t = self.engine.time_pos
        dur = self.engine.duration
        if t is None:
            return
        # 字幕
        segs = self.pipe.active(t)
        self.overlay.set_segments(segs, self.cfg.get("sub_mode", "bilingual"))
        # 进度条 / 时间
        if dur and not self.slider.isSliderDown():
            self.slider.setValue(int(t / dur * 1000))
        self.lbl_time.setText(f"{_fmt(t)} / {_fmt(dur or 0)}")
        # TTS 配音
        if self.chk_tts.isChecked() and self.tts is not None and segs:
            seg = segs[0]
            if seg.id != self._last_dub_id and (seg.tgt or seg.src):
                self._last_dub_id = seg.id
                threading.Thread(
                    target=self._dub_async,
                    args=(seg.tgt or seg.src,),
                    daemon=True,
                ).start()

    def _dub_async(self, text: str) -> None:
        try:
            assert self.tts is not None and self.engine is not None
            sr, pcm = self.tts.synthesize(text)
            if self.cfg.get("ducking", True):
                self._saved_volume = self.engine.volume
                self.engine.volume = max(10, int(self._saved_volume * 0.3))
            # 必须在主线程操作 QAudioSink
            QTimer.singleShot(0, lambda: self.dubber.play(sr, pcm))
        except Exception as e:  # noqa: BLE001
            self.pipe.status.emit(f"配音失败：{e}")

    def _on_dub_finished(self) -> None:
        if self.engine and self.cfg.get("ducking", True):
            self.engine.volume = self._saved_volume

    def closeEvent(self, event):  # noqa: ANN001, ANN202, N802
        try:
            self.pipe.stop()
        except Exception:
            pass
        try:
            if self.engine:
                self.engine.shutdown()
        except Exception:
            pass
        save_config(self.cfg)
        super().closeEvent(event)


def _fmt(sec: float) -> str:
    s = int(max(0, sec))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
