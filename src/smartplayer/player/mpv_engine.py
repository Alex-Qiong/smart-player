"""libmpv 播放引擎封装（基于 python-mpv）。

Windows 下需要 libmpv-2.dll，可通过 tools/fetch_libmpv.py 下载，
或设置环境变量 SMARTPLAYER_LIBMPV 指向 dll 路径。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

try:
    import mpv as _mpv
except ImportError:  # pragma: no cover
    _mpv = None

from ..config import app_data_dir


def find_libmpv() -> Path | None:
    """按优先级查找 libmpv-2.dll。"""
    candidates: list[Path] = []
    env = os.environ.get("SMARTPLAYER_LIBMPV")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates += [
        Path.cwd() / "libmpv-2.dll",
        here.parent.parent.parent / "libmpv-2.dll",  # 项目根目录
        app_data_dir() / "libmpv-2.dll",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_libmpv_loaded() -> Path | None:
    """Windows 下把 dll 所在目录加入 DLL 搜索路径，返回找到的 dll 路径。"""
    lib = find_libmpv()
    if lib is not None and os.name == "nt":
        try:
            os.add_dll_directory(str(lib.parent))
        except Exception:
            pass
        os.environ["PATH"] = str(lib.parent) + os.pathsep + os.environ.get("PATH", "")
    return lib


class MpvEngine:
    """对 python-mpv 的薄封装，只暴露播放器需要的操作。"""

    def __init__(self, wid: int, hwdec: bool = True):
        if _mpv is None:
            raise RuntimeError("未安装 python-mpv，请先执行：pip install python-mpv")
        ensure_libmpv_loaded()

        vo = "gpu-next" if os.name == "nt" else "gpu"
        self._mpv = _mpv.MPV(
            wid=str(int(wid)),
            vo=vo,
            hwdec="auto" if hwdec else "no",
            input_default_bindings=True,
            input_vo_keyboard=True,
            osc=False,
            ytdl=False,
            keep_open="yes",
            idle="yes",
            log_handler=self._on_log,
            loglevel="warn",
        )
        self._end_cbs: list[Callable[[], None]] = []

        @self._mpv.event_callback("end-file")
        def _on_end(event):  # noqa: F841
            for cb in list(self._end_cbs):
                try:
                    cb()
                except Exception:
                    pass

    # ---------------- 播放控制 ----------------
    def play(self, path: str | Path) -> None:
        self._mpv.play(str(path))

    def toggle_pause(self) -> None:
        self._mpv.pause = not self._mpv.pause

    def stop(self) -> None:
        try:
            self._mpv.stop()
        except Exception:
            pass

    def seek(self, seconds: float, absolute: bool = False) -> None:
        try:
            self._mpv.seek(
                seconds,
                reference="absolute" if absolute else "relative",
                precision="exact",
            )
        except Exception:
            pass

    # ---------------- 属性 ----------------
    @property
    def time_pos(self) -> float | None:
        try:
            return self._mpv.time_pos
        except Exception:
            return None

    @property
    def duration(self) -> float | None:
        try:
            return self._mpv.duration
        except Exception:
            return None

    @property
    def paused(self) -> bool:
        try:
            return bool(self._mpv.pause)
        except Exception:
            return False

    @paused.setter
    def paused(self, v: bool) -> None:
        try:
            self._mpv.pause = bool(v)
        except Exception:
            pass

    @property
    def volume(self) -> int:
        try:
            return int(self._mpv.volume)
        except Exception:
            return 100

    @volume.setter
    def volume(self, v: int) -> None:
        try:
            self._mpv.volume = max(0, min(100, int(v)))
        except Exception:
            pass

    @property
    def filename(self) -> str | None:
        try:
            return self._mpv.filename
        except Exception:
            return None

    def on_end_file(self, cb: Callable[[], None]) -> None:
        self._end_cbs.append(cb)

    def show_text(self, text: str, duration_ms: int = 1500) -> None:
        try:
            self._mpv.command("show-text", text, str(duration_ms))
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass

    @staticmethod
    def _on_log(loglevel, component, message):  # noqa: ANN001, ANN205
        # 保持安静：只在需要时把日志打到 stderr
        pass
