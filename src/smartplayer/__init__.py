"""SmartPlayer — 基于 mpv/libmpv 的 Windows 视频播放器。

内置本地 AI 管线：
- faster-whisper（本地 ASR）：无字幕视频的实时语音转写
- Argos Translate（本地翻译）：字幕实时翻译
- Piper TTS（本地语音合成）：翻译字幕 AI 配音
"""

__version__ = "0.1.0"
__app_name__ = "SmartPlayer"
