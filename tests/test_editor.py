import shutil
import subprocess
from pathlib import Path

import pytest

from reelbot.captions import Word, build_ass, chunk_words
from reelbot.editor import EditOptions, edit_video, keep_segments, probe

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_keep_segments_cuts_middle_and_trailing_silence():
    segs = keep_segments(12.0, [(3.0, 6.0), (9.0, float("inf"))], padding=0.1)
    assert segs == [(0.0, 3.1), (5.9, 9.1)]


def test_keep_segments_no_silence_keeps_everything():
    assert keep_segments(5.0, []) == [(0.0, 5.0)]


def test_keep_segments_merges_overlaps():
    segs = keep_segments(4.0, [(1.0, 1.1)], padding=0.2)
    assert segs == [(0.0, 4.0)]


def test_chunk_words_breaks_on_count_and_sentence_end():
    words = [Word(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(
        ["one", "two", "three", "four", "end.", "next"])]
    assert [c.text for c in chunk_words(words, max_words=3)] == ["one two three", "four end.", "next"]


def test_build_ass_has_hook_and_captions():
    ass = build_ass([Word("hello", 0.0, 0.5)], hook="Watch {this}")
    assert "Style: Hook" in ass and "HELLO" in ass
    assert "Watch (this)" in ass  # braces escaped so libass doesn't treat them as tags


def _make_clip(path: Path, size="1280x720", silent_ranges=((3, 6), (9, 12))):
    vol = "+".join(f"between(t,{a},{b})" for a, b in silent_ranges) or "0"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration=12",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration=12,volume='if({vol},0,1)':eval=frame",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
                   check=True)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_edit_landscape_to_vertical_with_cuts(tmp_path):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _make_clip(src)
    res = edit_video(src, out, EditOptions(hook="hook!"),
                     transcriber=lambda p, m: [Word("hi", 0.1, 0.4)])
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio
    assert 5.5 < info.duration < 7.5  # 12s minus ~6s of silence
    assert res.cuts == 1 and res.captioned


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_edit_without_captions_or_cuts_keeps_length(tmp_path):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _make_clip(src, size="720x1280")
    edit_video(src, out, EditOptions(cut_silence=False, captions=False))
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert 11.5 < info.duration < 12.5


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_missing_whisper_is_a_note_not_a_crash(tmp_path):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _make_clip(src)

    def no_whisper(p, m):
        raise RuntimeError("Auto-captions need faster-whisper")

    res = edit_video(src, out, EditOptions(), transcriber=no_whisper)
    assert out.exists() and not res.captioned
    assert any("faster-whisper" in n for n in res.notes)
