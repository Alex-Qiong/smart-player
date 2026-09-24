"""一键下载本地 AI 模型（ASR / 翻译 / TTS），存放到 %APPDATA%/SmartPlayer/models/。

用法（Windows）：
    python tools/download_models.py --all
    python tools/download_models.py --asr --asr-model small --translate en zh --tts zh_CN-huayan-medium
"""
from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # Windows 控制台默认 cp1252，print 中文会炸
    except Exception:
        pass

from smartplayer.config import models_dir  # noqa: E402


def download_asr(model_size: str = "small") -> None:
    from huggingface_hub import snapshot_download

    dest = models_dir() / "asr"
    dest.mkdir(parents=True, exist_ok=True)
    repo = f"Systran/faster-whisper-{model_size}"
    print(f"[ASR] 正在下载 {repo} -> {dest}")
    snapshot_download(repo_id=repo, local_dir=dest / repo.replace("/", "--"))
    print("[ASR] 完成")


def download_translate(from_code: str, to_code: str) -> None:
    import argostranslate.package as package

    print(f"[翻译] 正在准备 {from_code}->{to_code} 离线模型…")
    package.update_package_index()
    avail = package.get_available_packages()
    pkg = next(
        (
            p
            for p in avail
            if p.from_code == from_code and p.to_code == to_code
        ),
        None,
    )
    if pkg is None:
        raise SystemExit(f"找不到 {from_code}->{to_code} 的离线翻译模型")
    path = pkg.download()
    package.install_from_path(path)
    print("[翻译] 完成")


def download_tts(voice_id: str) -> None:
    from smartplayer.subs.tts import VOICES

    if voice_id not in VOICES:
        raise SystemExit(f"未知语音 {voice_id}，可选：{list(VOICES)}")
    dest = models_dir() / "tts"
    dest.mkdir(parents=True, exist_ok=True)
    onnx_url, json_url = VOICES[voice_id]
    print(f"[TTS] 正在下载 {voice_id}\n      {onnx_url}")
    urllib.request.urlretrieve(onnx_url, dest / f"{voice_id}.onnx")
    urllib.request.urlretrieve(json_url, dest / f"{voice_id}.onnx.json")
    print(f"[TTS] 完成 -> {dest}")


def main() -> None:
    ap = argparse.ArgumentParser(description="下载 SmartPlayer 本地 AI 模型")
    ap.add_argument("--all", action="store_true", help="下载全部（ASR+翻译+TTS）")
    ap.add_argument("--asr", action="store_true", help="下载 ASR 模型")
    ap.add_argument("--asr-model", default="small", help="tiny/base/small/medium")
    ap.add_argument("--translate", nargs=2, metavar=("FROM", "TO"), help="如：en zh")
    ap.add_argument("--tts", metavar="VOICE", help="如：zh_CN-huayan-medium")
    args = ap.parse_args()

    if args.all or args.asr:
        download_asr(args.asr_model)
    if args.all or args.translate:
        fc, tc = args.translate or ("en", "zh")
        download_translate(fc, tc)
    if args.all or args.tts:
        download_tts(args.tts or "zh_CN-huayan-medium")
    if not (args.all or args.asr or args.translate or args.tts):
        ap.print_help()


if __name__ == "__main__":
    main()
