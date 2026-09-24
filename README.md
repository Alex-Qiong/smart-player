# SmartPlayer

基于 [mpv](https://github.com/mpv-player/mpv) / libmpv 的 Windows 视频播放器，
**全格式播放** + **本地 AI 实时字幕翻译** + **本地 TTS 配音**，全部离线可跑。

## 功能

- **全格式播放**：mpv 内核，MP4/MKV/AVI/MOV/WMV/HEVC/AV1…通吃，自动硬解（`hwdec=auto`）
- **实时字幕翻译**（纯本地）：
  - 有内嵌/外挂字幕 → 提取后用 Argos Translate 离线批量翻译
  - 无字幕 → faster-whisper 后台"超前转写"（通常比播放快数倍），边播边出双语字幕
  - 翻译结果缓存为 `.smartsubs.json`，下次秒开
- **AI 配音**（纯本地，可选）：Piper TTS 把译文实时读出来，配音时自动压低原声音量
- 字幕显示模式：原文 / 译文 / 双语，Qt 自绘叠加层，支持自动换行

## 架构

```
┌─────────────┐   libmpv    ┌──────────────┐
│ PySide6 GUI │◄──────────►│  mpv 播放内核 │
└──────┬──────┘  (wid 嵌入)  └──────────────┘
       │ 120ms 轮询 time-pos
       ▼
┌──────────────┐   ┌───────────┐   ┌──────────────┐   ┌───────────┐
│SubtitleOverlay│◄──│Pipeline-  │◄──│faster-whisper│◄──│ffmpeg PCM │
│  (Qt 自绘)   │   │Controller │   │  (本地 ASR)  │   │ 16kHz音频 │
└──────────────┘   └─────┬─────┘   └──────────────┘   └───────────┘
                         │ Argos Translate（本地）
                         ▼
                   ┌────────────┐   ┌──────────┐
                   │ 双语字幕段  │──►│Piper TTS │──► QAudioSink 配音
                   └────────────┘   │ (本地)   │
                                    └──────────┘
```

转写策略：后台线程顺序解码音频，12s 窗口 / 10s 步进转写并翻译，
字幕数据领先于播放位置；快进到未转写区域时自动从新位置继续。

## Windows 快速开始

```bat
:: 1. 安装 Python 3.10+（官网 python.org，勾选 Add to PATH）

:: 2. 安装依赖
pip install -r requirements.txt

:: 3. 下载 libmpv-2.dll（放到项目根目录）
pip install py7zr requests
python tools/fetch_libmpv.py

:: 4. 下载本地 AI 模型（需联网一次，之后全离线）
python tools/download_models.py --all

:: 5. 运行
python src/smartplayer/main.py
:: 或：python src/smartplayer/main.py "D:\movie.mkv"
```

模型存放位置：`%APPDATA%\SmartPlayer\models\`
（`asr/` whisper 模型，`tts/` Piper 语音；Argos 翻译模型装在用户目录）

## 打包成 exe

**方式一：本机打包（Windows）**

```bat
pip install pyinstaller
python tools/fetch_libmpv.py          :: 确保根目录有 libmpv-2.dll
pyinstaller player.spec
:: 产物：dist\SmartPlayer\SmartPlayer.exe
:: 模型不打包，首次运行前执行：python tools/download_models.py --all
```

也可用 `pyinstaller --noconfirm player.spec` 覆盖构建。

**方式二：GitHub Actions 云打包（不用装任何构建环境）**

1. 把项目推到你自己的 GitHub 仓库（`main` 分支）
2. 打开仓库的 Actions 页面 → 点 "Build Windows EXE" → Run workflow（推送代码也会自动触发）
3. 等几分钟构建完成，在 Artifacts 里下载 `SmartPlayer-windows.zip`，解压即用

注意：云打包的产物不含 AI 模型，首次运行前在解压目录旁执行
`python tools/download_models.py --all`（需装 Python + requirements）。

## 目录结构

```
mpv-smart-player/
├── player.spec                 # PyInstaller 打包配置
├── requirements.txt
├── tools/
│   ├── download_models.py      # 一键下载本地 AI 模型
│   └── fetch_libmpv.py         # 下载 Windows libmpv-2.dll
└── src/smartplayer/
    ├── main.py                 # 程序入口
    ├── config.py               # 配置（%APPDATA%/SmartPlayer/config.json）
    ├── player/
    │   ├── mpv_engine.py       # libmpv 封装
    │   └── main_window.py      # 主界面 + 字幕叠加层 + TTS 播放
    └── subs/
        ├── pipeline.py         # 字幕管线调度（缓存/内嵌字幕/ASR）
        ├── audio_capture.py    # ffmpeg 音频抽取
        ├── asr.py              # faster-whisper 封装
        ├── translator.py       # Argos Translate 封装
        └── tts.py              # Piper TTS 封装
```

## 常见问题

- **提示找不到 libmpv**：运行 `tools/fetch_libmpv.py`，或设置环境变量
  `SMARTPLAYER_LIBMPV=D:\path\to\libmpv-2.dll`
- **转写慢**：把设置里的 ASR 模型从 `small` 换成 `base`/`tiny`；
  有 NVIDIA 显卡时 `asr_device` 设为 `cuda`（需安装 CUDA 版 ctranslate2）
- **翻译语言**：界面可切换源/目标语言；源语言选"自动检测"时，
  内嵌字幕不翻译（无法确定源语言），ASR 路径仍可自动检测
- **配音不同步**：TTS 是逐句合成，有 1~2 秒延迟属正常；长句可调小字幕分段

## 说明

- 关于你提的"TTS 模型做字幕翻译"：严格来说实时字幕翻译需要两步——
  **语音识别（ASR，把声音转成文字）+ 机器翻译（把文字译成中文）**，
  TTS（文字转语音）负责第三步：把译文**配音读出来**。三件套都已内置，
  可在界面上单独开关。
- mpv 为 GPLv2 授权，libmpv 为 LGPL；本项目动态链接 libmpv。
  faster-whisper / Argos / Piper 均为宽松开源授权，商用前请自行核对各组件 License。

## Roadmap

- [ ] 设置对话框（模型/设备/快捷键可视化配置）
- [ ] 播放列表、倍速、AB 复读
- [ ] LLM 本地翻译后端（llama.cpp，翻译质量更高）
- [ ] 说话人分离（diarization）与双语时间轴导出
