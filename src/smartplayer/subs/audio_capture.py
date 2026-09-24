"""用 ffmpeg 把媒体音频抽成 16kHz 单声道 PCM，供 ASR 使用。

优先使用 imageio-ffmpeg 自带的 ffmpeg 二进制（Windows 打包友好），
找不到时回退到系统 PATH 中的 ffmpeg。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


class AudioCapture:
    """顺序读取媒体文件的原始 PCM 音频（16kHz / 单声道 / s16le）。"""

    SAMPLE_RATE = 16000
    BYTES_PER_SAMPLE = 2

    def __init__(self, media: str | Path, start: float = 0.0):
        self._media = str(media)
        self._start = max(0.0, float(start))
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        cmd = [
            ffmpeg_exe(),
            "-v", "error",
            "-ss", f"{self._start:.3f}",
            "-i", self._media,
            "-vn",
            "-map", "0:a:0?",
            "-ac", "1",
            "-ar", str(self.SAMPLE_RATE),
            "-f", "s16le",
            "-",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

    def read(self, n_samples: int) -> bytes:
        """精确读取 n_samples 个采样点；到文件尾时返回不足长度的数据。"""
        if self._proc is None or self._proc.stdout is None:
            return b""
        want = n_samples * self.BYTES_PER_SAMPLE
        buf = bytearray()
        while len(buf) < want:
            chunk = self._proc.stdout.read(want - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    @property
    def eof(self) -> bool:
        return self._proc is not None and self._proc.poll() is not None

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None


def extract_subtitle_track(media: str | Path, index: int = 0) -> str | None:
    """抽取第 index 条内嵌字幕轨为 srt 文本；没有字幕轨时返回 None。"""
    cmd = [
        ffmpeg_exe(),
        "-v", "error",
        "-i", str(media),
        "-map", f"0:s:{index}",
        "-f", "srt",
        "-",
    ]
    try:
        out = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120
        ).stdout.decode("utf-8", errors="ignore")
    except Exception:
        return None
    return out if out.strip() else None
