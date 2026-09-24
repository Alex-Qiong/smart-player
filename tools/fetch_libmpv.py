"""下载 Windows 版 libmpv-2.dll（来自 zhongfly/mpv-winbuild 的 mpv-dev 包）。

用法：
    python tools/fetch_libmpv.py            # 下载到项目根目录
    python tools/fetch_libmpv.py --out DIR  # 指定输出目录

需要 pip install py7zr requests（或手动下载解压）。
手动下载地址：https://github.com/zhongfly/mpv-winbuild/releases
找名字里带 mpv-dev-x86_64 的 7z 包，解压出 libmpv-2.dll 即可。
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

API = "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest"


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SmartPlayer"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("[libmpv] 查询最新 mpv-dev 包…")
    rel = json.loads(_http_get(API).decode("utf-8"))
    asset = next(
        (
            a
            for a in rel.get("assets", [])
            if "mpv-dev-x86_64" in a["name"] and a["name"].endswith(".7z")
        ),
        None,
    )
    if asset is None:
        raise SystemExit("未找到 mpv-dev-x86_64 包，请手动下载（见本文件顶部说明）")

    url = asset["browser_download_url"]
    print(f"[libmpv] 下载 {asset['name']} …")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset["name"]
        urllib.request.urlretrieve(url, archive)
        print("[libmpv] 解压…")
        try:
            import py7zr
        except ImportError:
            raise SystemExit(
                "需要 py7zr 来解压：pip install py7zr\n"
                f"或手动解压 {archive}，把 libmpv-2.dll 放到 {out}"
            )
        with py7zr.SevenZipFile(archive, "r") as z:
            z.extractall(tmp)
        dll = next(Path(tmp).rglob("libmpv-2.dll"), None)
        if dll is None:
            raise SystemExit("包中未找到 libmpv-2.dll")
        shutil.copy2(dll, out / "libmpv-2.dll")
    print(f"[libmpv] 完成 -> {out / 'libmpv-2.dll'}")


if __name__ == "__main__":
    main()
