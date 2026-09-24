"""本地 TTS 配音：Piper（ONNX 语音合成，纯本地运行）。

默认中文语音 zh_CN-huayan-medium，可通过 tools/download_models.py 下载，
或手动把 .onnx（及同名 .onnx.json）放到 %APPDATA%/SmartPlayer/models/tts/。
"""
from __future__ import annotations

from pathlib import Path

# 常用语音及下载地址（HuggingFace rhasspy/piper-voices 镜像，
# 原 GitHub release 已迁移失效）
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICES = {
    "zh_CN-huayan-medium": (
        f"{HF}/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx",
        f"{HF}/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json",
    ),
    "en_US-lessac-medium": (
        f"{HF}/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        f"{HF}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    ),
}


class PiperTTS:
    """Piper TTS 封装。synthesize 返回 (采样率, int16 单声道 PCM bytes)。"""

    def __init__(
        self, voice_id: str = "zh_CN-huayan-medium", models_dir: str | Path | None = None
    ):
        self.voice_id = voice_id
        self.models_dir = Path(models_dir) if models_dir else None
        self._voice = None
        self._err: str | None = None

    # ---------------- 可用性 ----------------
    def voice_file(self) -> Path | None:
        base = (self.models_dir / "tts") if self.models_dir else None
        if base is None:
            return None
        p = base / f"{self.voice_id}.onnx"
        return p if p.is_file() else None

    def available(self) -> tuple[bool, str]:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False, "未安装 piper-tts，请执行：pip install piper-tts"
        if self.voice_file() is None:
            return (
                False,
                f"未找到语音模型 {self.voice_id}.onnx，"
                "请运行 tools/download_models.py --tts 下载",
            )
        if self._voice is None and self._err:
            return False, self._err
        return True, "ok"

    # ---------------- 合成 ----------------
    def _load(self) -> None:
        if self._voice is not None:
            return
        try:
            from piper import PiperVoice

            onnx = self.voice_file()
            if onnx is None:
                raise RuntimeError(f"找不到语音模型 {self.voice_id}.onnx")
            self._voice = PiperVoice.load(str(onnx), use_cuda=False)
        except Exception as e:  # noqa: BLE001
            self._err = f"TTS 模型加载失败：{e}"
            raise RuntimeError(self._err) from e

    def synthesize(self, text: str) -> tuple[int, bytes]:
        """合成文本 -> (sample_rate, pcm16 bytes)。"""
        self._load()
        chunks: list[bytes] = []
        for chunk in self._voice.synthesize(text):
            chunks.append(chunk.audio_int16_bytes)
        return int(self._voice.config.sample_rate), b"".join(chunks)
