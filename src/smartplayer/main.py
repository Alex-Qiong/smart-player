"""SmartPlayer 程序入口。"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接从源码目录运行：python src/smartplayer/main.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from smartplayer import __version__
from smartplayer.config import load_config
from smartplayer.player.main_window import MainWindow


def main() -> int:
    cfg = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName("SmartPlayer")
    app.setApplicationVersion(__version__)
    win = MainWindow(cfg)
    win.show()
    if len(sys.argv) > 1:
        # 支持：smartplayer.exe "D:\\movie.mp4"
        from PySide6.QtCore import QTimer

        path = sys.argv[1]
        QTimer.singleShot(600, lambda: _open(win, path))
    return app.exec()


def _open(win: MainWindow, path: str) -> None:
    if win.engine is None:
        return
    win._media = path  # noqa: SLF001
    win.setWindowTitle(f"SmartPlayer - {Path(path).name}")
    win.engine.play(path)
    win.pipe.start(path)


if __name__ == "__main__":
    raise SystemExit(main())
