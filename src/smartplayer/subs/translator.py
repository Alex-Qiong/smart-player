"""本地翻译：Argos Translate（离线神经机器翻译）。

首次使用某语言对时会自动下载对应模型（需联网一次），之后完全离线。
"""
from __future__ import annotations

# 界面语言下拉框用
LANG_NAMES = {
    "auto": "自动检测",
    "en": "英语",
    "zh": "中文",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "it": "意大利语",
    "pt": "葡萄牙语",
}


class ArgosTranslator:
    """Argos Translate 封装，保证输入输出条数一一对应。"""

    def __init__(self, from_code: str = "en", to_code: str = "zh"):
        self.from_code = from_code
        self.to_code = to_code
        self._translation = None
        self._err: str | None = None

    # ---------------- 可用性 ----------------
    def available(self) -> tuple[bool, str]:
        try:
            import argostranslate.translate  # noqa: F401
        except ImportError:
            return False, "未安装 argostranslate，请执行：pip install argostranslate"
        if self._translation is None and self._err:
            return False, self._err
        return True, "ok"

    # ---------------- 翻译 ----------------
    def _load(self) -> None:
        if self._translation is not None:
            return
        try:
            import argostranslate.package as package
            import argostranslate.translate as translate

            installed = translate.get_installed_languages()
            src_lang = next(
                (l for l in installed if l.code == self.from_code), None
            )
            tgt_codes = (
                [t.code for t in src_lang.translations] if src_lang else []
            )
            if self.to_code not in tgt_codes:
                # 下载并安装语言包（只需联网一次）
                package.update_package_index()
                avail = package.get_available_packages()
                pkg = next(
                    (
                        p
                        for p in avail
                        if p.from_code == self.from_code
                        and p.to_code == self.to_code
                    ),
                    None,
                )
                if pkg is None:
                    raise RuntimeError(
                        f"找不到 {self.from_code}->{self.to_code} 的离线翻译模型"
                    )
                package.install_from_path(pkg.download())
                installed = translate.get_installed_languages()
                src_lang = next(
                    (l for l in installed if l.code == self.from_code), None
                )
            self._translation = src_lang.get_translation(self.to_code)
        except Exception as e:  # noqa: BLE001
            self._err = f"翻译模型加载失败：{e}"
            raise RuntimeError(self._err) from e

    def translate(self, texts: list[str]) -> list[str]:
        """批量翻译；与输入等长（空行原样返回空）。"""
        if self.from_code == self.to_code:
            return list(texts)
        self._load()
        out: list[str] = []
        for t in texts:
            if t and t.strip():
                try:
                    out.append(self._translation.translate(t))
                except Exception:
                    out.append(t)  # 单条失败就保留原文
            else:
                out.append("")
        return out
