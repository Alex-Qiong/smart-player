"""应用配置：读写 %APPDATA%/SmartPlayer/config.json。"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "SmartPlayer"

DEFAULTS = {
    # ---- 本地 ASR（faster-whisper）----
    "asr_model": "small",      # tiny / base / small / medium，越大越准越慢
    "asr_device": "auto",      # auto / cpu / cuda
    # ---- 翻译 ----
    "src_lang": "auto",        # auto 或 whisper 语言代码（en/zh/ja/ko/...）
    "tgt_lang": "zh",
    "use_embedded_subs": True,  # 优先使用内嵌/外挂字幕并翻译
    "sub_mode": "bilingual",   # original / translated / bilingual
    "live_translate": True,    # 实时翻译总开关
    # ---- TTS 配音 ----
    "tts_enabled": False,
    "tts_voice": "zh_CN-huayan-medium",
    "ducking": True,           # 配音时自动降低原声音量
    # ---- 播放 ----
    "hwdec": True,
}


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = app_data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if config_path().exists():
            loaded = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        config_path().write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
