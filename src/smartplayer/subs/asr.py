"""本地语音识别：faster-whisper（CTranslate2 后端，纯本地运行）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscribedSegment:
    start: float  # 相对窗口起点（秒）
    end: float
    text: str


class WhisperASR:
    """faster-whisper 封装。模型延迟加载，缺依赖时给出明确提示。"""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        models_dir: str | Path | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.models_dir = Path(models_dir) if models_dir else None
        self._model = None
        self._err: str | None = None

    # ---------------- 可用性 ----------------
    def available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "未安装 faster-whisper，请执行：pip install faster-whisper"
        if self._model is None and self._err:
            return False, self._err
        return True, "ok"

    # ---------------- 推理 ----------------
    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            device = self.device
            if device == "auto":
                device = "cuda" if self._cuda_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            download_root = (
                str(self.models_dir / "asr") if self.models_dir else None
            )
            self._model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute,
                download_root=download_root,
            )
        except Exception as e:  # noqa: BLE001
            self._err = f"ASR 模型加载失败：{e}"
            raise RuntimeError(self._err) from e

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    def transcribe(
        self, pcm16, language: str | None = None  # noqa: ANN001 - numpy 数组
    ) -> list[TranscribedSegment]:
        """转写一段 16kHz 单声道 int16 PCM。language=None 时自动检测。"""
        self._load()
        import numpy as np

        audio = np.asarray(pcm16, dtype=np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=True,
            beam_size=1,  # 速度优先；要更高精度可改为 5
            condition_on_previous_text=False,
        )
        return [
            TranscribedSegment(s.start, s.end, s.text.strip())
            for s in segments
            if s.text and s.text.strip()
        ]
