"""冒烟测试：用假 ASR/翻译器验证管线逻辑（无需装重型依赖）。"""
import sys
import types
from pathlib import Path

# ---- 轻量 PySide6 存根（仅够 PipelineController 的 Signal/QObject 用）----
_pyside6 = types.ModuleType("PySide6")
_qtcore = types.ModuleType("PySide6.QtCore")


class _Signal:
    def __init__(self, *a):
        self._subs = []

    def connect(self, fn):
        self._subs.append(fn)

    def emit(self, *a):
        for fn in list(self._subs):
            fn(*a)


class _QObject:
    def __init__(self, parent=None):
        pass


_qtcore.Signal = _Signal
_qtcore.QObject = _QObject
_pyside6.QtCore = _qtcore
sys.modules["PySide6"] = _pyside6
sys.modules["PySide6.QtCore"] = _qtcore
# ---- 存根结束 ----

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from smartplayer.subs.pipeline import (
    PipelineController,
    SubSegment,
    SubtitleStore,
    parse_srt,
)


class FakeASR:
    def transcribe(self, pcm, language=None):
        from smartplayer.subs.asr import TranscribedSegment

        return [TranscribedSegment(0.0, 2.0, "hello world")]


class FakeTranslator:
    def translate(self, texts):
        return ["你好世界" for _ in texts]


def test_parse_srt():
    srt = """1
00:00:01,000 --> 00:00:03,500
Hello world

2
00:00:04,000 --> 00:00:06,000
Second line
"""
    segs = parse_srt(srt)
    assert len(segs) == 2, segs
    assert abs(segs[0].start - 1.0) < 1e-6
    assert abs(segs[0].end - 3.5) < 1e-6
    assert segs[0].src == "Hello world"
    print("parse_srt OK")


def test_store_active():
    st = SubtitleStore()
    st.add([SubSegment(1.0, 3.0, "a", "甲"), SubSegment(5.0, 7.0, "b", "乙")])
    assert [s.src for s in st.active(2.0)] == ["a"]
    assert st.active(4.0) == []
    assert [s.src for s in st.active(6.0)] == ["b"]
    assert abs(st.coverage() - 7.0) < 1e-6
    print("SubtitleStore OK")


def test_cache_roundtrip(tmp="/tmp/smartsubs_test.json"):
    st = SubtitleStore()
    st.add([SubSegment(1.0, 3.0, "a", "甲")])
    d = st.to_dict("en", "zh")
    st2 = SubtitleStore()
    assert st2.load_dict(d)
    assert [s.tgt for s in st2.active(2.0)] == ["甲"]
    print("cache roundtrip OK")


def test_controller_cache(tmp="/tmp/fake_media.mp4"):
    Path(tmp).write_bytes(b"fake")
    cache = Path(str(tmp) + ".smartsubs.json")
    st = SubtitleStore()
    st.add([SubSegment(0.0, 5.0, "hi", "嗨")])
    cache.write_text(
        __import__("json").dumps(st.to_dict("en", "zh"), ensure_ascii=False)
    )
    cfg = {
        "src_lang": "en",
        "tgt_lang": "zh",
        "live_translate": True,
        "use_embedded_subs": True,
    }
    c = PipelineController(cfg)
    c.start(tmp)
    assert [s.tgt for s in c.active(2.0)] == ["嗨"], "应命中缓存"
    c.stop()
    cache.unlink()
    Path(tmp).unlink()
    print("PipelineController cache OK")


if __name__ == "__main__":
    test_parse_srt()
    test_store_active()
    test_cache_roundtrip()
    test_controller_cache()
    print("ALL SMOKE TESTS PASSED")
