"""实时字幕管线调度。

策略（按优先级）：
1. 有缓存（媒体同目录 .smartsubs.json）→ 直接载入；
2. 有内嵌/外挂 srt 字幕 → 提取后用本地模型批量翻译；
3. 无字幕 → 后台“超前转写”：ffmpeg 顺序解码音频，faster-whisper
   按 12s 窗口（10s 步进）转写并实时翻译，播放进度条走哪儿字幕跟到哪儿。

转写速度通常是播放速度的数倍，所以字幕会一直领先于播放位置；
快进到未转写区域时自动从新位置继续。
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import models_dir
from .asr import WhisperASR
from .audio_capture import AudioCapture, extract_subtitle_track
from .translator import ArgosTranslator

WINDOW_SEC = 12.0   # 转写窗口
STEP_SEC = 10.0     # 窗口步进（2s 重叠，避免断句）


@dataclass
class SubSegment:
    start: float
    end: float
    src: str
    tgt: str = ""
    id: int = 0


class SubtitleStore:
    """线程安全的字幕段存储。"""

    def __init__(self):
        self._segs: list[SubSegment] = []
        self._lock = threading.Lock()
        self._next_id = 1

    def add(self, segs: list[SubSegment]) -> None:
        with self._lock:
            for s in segs:
                s.id = self._next_id
                self._next_id += 1
                self._segs.append(s)
            self._segs.sort(key=lambda s: s.start)

    def active(self, t: float) -> list[SubSegment]:
        with self._lock:
            return [s for s in self._segs if s.start <= t < s.end]

    def coverage(self) -> float:
        with self._lock:
            return max((s.end for s in self._segs), default=0.0)

    def clear(self) -> None:
        with self._lock:
            self._segs.clear()
            self._next_id = 1

    # ---- 缓存 ----
    def to_dict(self, src_lang: str, tgt_lang: str) -> dict:
        with self._lock:
            return {
                "version": 1,
                "src_lang": src_lang,
                "tgt_lang": tgt_lang,
                "segments": [asdict(s) for s in self._segs],
            }

    def load_dict(self, d: dict) -> bool:
        try:
            segs = [
                SubSegment(
                    start=float(s["start"]),
                    end=float(s["end"]),
                    src=str(s.get("src", "")),
                    tgt=str(s.get("tgt", "")),
                    id=int(s.get("id", 0)),
                )
                for s in d.get("segments", [])
            ]
        except Exception:
            return False
        with self._lock:
            self._segs = sorted(segs, key=lambda s: s.start)
            self._next_id = max((s.id for s in self._segs), default=0) + 1
        return True


# ---------------- srt 解析 ----------------
_SRT_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*"
    r"(\d+):(\d+):(\d+)[,.](\d+)"
)


def _ts(h, m, s, ms) -> float:  # noqa: ANN001, ANN202
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text: str) -> list[SubSegment]:
    segs: list[SubSegment] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = _SRT_RE.search(lines[1] if "-->" in lines[1] else lines[0])
        if not m:
            continue
        g = m.groups()
        start, end = _ts(*g[0:4]), _ts(*g[4:8])
        body = " ".join(
            l for l in lines if "-->" not in l and not l.strip().isdigit()
        ).strip()
        if body:
            segs.append(SubSegment(start, end, body))
    return segs


def find_external_srt(media: str | Path) -> Path | None:
    p = Path(media)
    for ext in (".srt", ".SRT"):
        cand = p.with_suffix(ext)
        if cand.is_file():
            return cand
    return None


# ---------------- 后台转写 ----------------
class TranscriptionWorker(threading.Thread):
    """从 start 位置顺序转写到文件尾（或被 stop）。"""

    daemon = True

    def __init__(
        self,
        media: str,
        start: float,
        store: SubtitleStore,
        asr: WhisperASR,
        translator: ArgosTranslator | None,
        src_lang: str,
        on_status,
        on_done,
    ):
        super().__init__(name="TranscriptionWorker")
        self._media = media
        self._start = start
        self._store = store
        self._asr = asr
        self._translator = translator
        self._src_lang = None if src_lang == "auto" else src_lang
        self._on_status = on_status
        self._on_done = on_done
        self._stop_event = threading.Event()
        self._cap: AudioCapture | None = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._cap is not None:
            self._cap.stop()  # 杀掉 ffmpeg，让阻塞中的 read 立刻返回

    def run(self) -> None:  # noqa: C901
        import numpy as np

        cap = AudioCapture(self._media, self._start)
        self._cap = cap
        try:
            cap.start()
        except Exception as e:  # noqa: BLE001
            self._on_status(f"音频抽取失败：{e}")
            return
        cursor = self._start
        win_samples = int(WINDOW_SEC * AudioCapture.SAMPLE_RATE)
        overlap = WINDOW_SEC - STEP_SEC
        try:
            while not self._stop_event.is_set():
                raw = cap.read(win_samples)
                if len(raw) < int(1.0 * AudioCapture.SAMPLE_RATE * 2):
                    break  # 到文件尾
                pcm = np.frombuffer(raw, dtype=np.int16)
                try:
                    tsegs = self._asr.transcribe(pcm, language=self._src_lang)
                except Exception as e:  # noqa: BLE001
                    self._on_status(f"转写出错：{e}")
                    break
                fresh = [s for s in tsegs if s.start >= overlap - 1e-6]
                if fresh:
                    tgts = (
                        self._translator.translate([s.text for s in fresh])
                        if self._translator
                        else [""] * len(fresh)
                    )
                    self._store.add(
                        [
                            SubSegment(
                                start=cursor + s.start,
                                end=cursor + s.end,
                                src=s.text,
                                tgt=t,
                            )
                            for s, t in zip(fresh, tgts)
                        ]
                    )
                cursor += STEP_SEC
        finally:
            cap.stop()
            self._on_done()


# ---------------- 控制器 ----------------
class PipelineController(QObject):
    status = Signal(str)    # 状态栏消息
    updated = Signal()      # 字幕数据有更新

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.store = SubtitleStore()
        self.media: str | None = None
        self._worker: TranscriptionWorker | None = None
        self._asr: WhisperASR | None = None
        self._translator: ArgosTranslator | None = None
        self._src_lang = cfg.get("src_lang", "auto")
        self._tgt_lang = cfg.get("tgt_lang", "zh")

    # ---------------- 对外接口 ----------------
    def start(self, media: str) -> None:
        self.stop()
        self.media = media
        self.store.clear()
        self._src_lang = self.cfg.get("src_lang", "auto")
        self._tgt_lang = self.cfg.get("tgt_lang", "zh")

        if not self.cfg.get("live_translate", True):
            self.status.emit("实时翻译已关闭")
            return

        # 1) 缓存
        if self._load_cache():
            self.status.emit("已载入缓存字幕")
            self.updated.emit()
            return

        # 2) 内嵌 / 外挂字幕
        if self.cfg.get("use_embedded_subs", True):
            srt_text = self._get_existing_sub_text()
            if srt_text:
                segs = parse_srt(srt_text)
                if segs:
                    self._translate_segments(segs)
                    self.store.add(segs)
                    self._save_cache()
                    self.status.emit(f"已翻译现有字幕（{len(segs)} 条）")
                    self.updated.emit()
                    return

        # 3) 本地 ASR 实时转写
        ok, msg = self._ensure_asr()
        if not ok:
            self.status.emit(msg)
            return
        if self._src_lang != "auto":
            ok, msg = self._ensure_translator(self._src_lang, self._tgt_lang)
            if not ok:
                self.status.emit(msg + "（将只显示原文）")
                self._translator = None
        self._start_worker(0.0)
        self.status.emit("正在转写音频并实时翻译字幕…")

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.join(timeout=5)
            self._worker = None
        if self.media:
            self._save_cache()
        self.media = None

    def on_seek(self, pos: float) -> None:
        """快进到未转写区域时，从新位置继续转写。"""
        if self._worker is None or not self._worker.is_alive():
            return
        if pos > self.store.coverage() - 2.0:
            self._start_worker(max(0.0, pos - 1.0))
            self.status.emit("已跳转，从新位置继续转写…")

    def active(self, t: float) -> list[SubSegment]:
        return self.store.active(t)

    # ---------------- 内部 ----------------
    def _cache_path(self, media: str) -> Path:
        return Path(str(media) + ".smartsubs.json")

    def _load_cache(self) -> bool:
        if not self.media:
            return False
        p = self._cache_path(self.media)
        if not p.is_file():
            return False
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return False
        if d.get("src_lang") != self._src_lang or d.get("tgt_lang") != self._tgt_lang:
            return False
        return self.store.load_dict(d)

    def _save_cache(self) -> None:
        if not self.media:
            return
        try:
            self._cache_path(self.media).write_text(
                json.dumps(
                    self.store.to_dict(self._src_lang, self._tgt_lang),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _get_existing_sub_text(self) -> str | None:
        assert self.media
        ext = find_external_srt(self.media)
        if ext is not None:
            try:
                return ext.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        try:
            return extract_subtitle_track(self.media, 0)
        except Exception:
            return None

    def _ensure_asr(self) -> tuple[bool, str]:
        if self._asr is None:
            self._asr = WhisperASR(
                model_size=self.cfg.get("asr_model", "small"),
                device=self.cfg.get("asr_device", "auto"),
                models_dir=models_dir(),
            )
        ok, msg = self._asr.available()
        if ok:
            try:
                self._asr._load()  # noqa: SLF001 - 预热，失败早暴露
            except RuntimeError as e:
                return False, str(e)
        return ok, msg

    def _ensure_translator(self, src: str, tgt: str) -> tuple[bool, str]:
        if (
            self._translator is None
            or self._translator.from_code != src
            or self._translator.to_code != tgt
        ):
            self._translator = ArgosTranslator(src, tgt)
        ok, msg = self._translator.available()
        if ok:
            try:
                self._translator._load()  # noqa: SLF001 - 预热
            except RuntimeError as e:
                return False, str(e)
        return ok, msg

    def _translate_segments(self, segs: list[SubSegment]) -> None:
        """翻译已有字幕（源语言未知时跳过翻译、仅显示原文）。"""
        if self._src_lang == "auto":
            return
        ok, _ = self._ensure_translator(self._src_lang, self._tgt_lang)
        if not ok:
            return
        try:
            tgts = self._translator.translate([s.src for s in segs])
            for s, t in zip(segs, tgts):
                s.tgt = t
        except Exception:
            pass

    def _start_worker(self, start: float) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.join(timeout=5)
        translator = None
        if self._src_lang != "auto":
            ok, _ = self._ensure_translator(self._src_lang, self._tgt_lang)
            translator = self._translator if ok else None
        assert self._asr is not None and self.media
        self._worker = TranscriptionWorker(
            media=self.media,
            start=start,
            store=self.store,
            asr=self._asr,
            translator=translator,
            src_lang=self._src_lang,
            on_status=self.status.emit,
            on_done=self._on_worker_done,
        )
        self._worker.start()

    def _on_worker_done(self) -> None:
        self._save_cache()
        self.updated.emit()
