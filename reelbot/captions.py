"""Caption styling: turns word timings into an .ass subtitle file that ffmpeg burns in.

Style: big, bold, centered, 1-3 words at a time (the standard "Reels caption" look),
plus an optional hook line pinned near the top for the first few seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Word:
    text: str
    start: float
    end: float


def _ts(seconds: float) -> str:
    """ASS timestamp: H:MM:SS.cc"""
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk_words(words: list[Word], max_words: int = 3, max_gap: float = 0.6) -> list[Word]:
    """Group words into short caption chunks; break on pauses and sentence ends."""
    chunks: list[Word] = []
    cur: list[Word] = []
    for w in words:
        if cur and (len(cur) >= max_words or w.start - cur[-1].end > max_gap
                    or cur[-1].text.rstrip().endswith((".", "!", "?"))):
            chunks.append(Word(" ".join(x.text.strip() for x in cur), cur[0].start, cur[-1].end))
            cur = []
        cur.append(w)
    if cur:
        chunks.append(Word(" ".join(x.text.strip() for x in cur), cur[0].start, cur[-1].end))
    return chunks


def build_ass(
    words: list[Word] | None = None,
    hook: str | None = None,
    hook_seconds: float = 3.0,
    width: int = 1080,
    height: int = 1920,
    font: str = "Inter",
    uppercase: bool = True,
) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,560,1
Style: Hook,{font},72,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook:
        # Pop-in: scale from 80% to 100% over 150ms
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(hook_seconds)},Hook,,0,0,0,,"
            f"{{\\fscx80\\fscy80\\t(0,150,\\fscx100\\fscy100)}}{_escape(hook)}"
        )
    chunks = chunk_words(words or [])
    for i, c in enumerate(chunks):
        end = c.end
        if i + 1 < len(chunks):  # hold until next chunk if the gap is tiny
            nxt = chunks[i + 1].start
            if nxt - end < 0.3:
                end = nxt
        text = c.text.upper() if uppercase else c.text
        lines.append(
            f"Dialogue: 0,{_ts(c.start)},{_ts(max(end, c.start + 0.2))},Caption,,0,0,0,,"
            f"{{\\fscx90\\fscy90\\t(0,80,\\fscx100\\fscy100)}}{_escape(text)}"
        )
    return header + "\n".join(lines) + "\n"


def transcribe(video: Path, model_size: str = "small") -> list[Word]:
    """Word-level transcription with faster-whisper (optional dependency)."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Auto-captions need faster-whisper: pip install 'reelbot[captions]' "
            "(or run with --no-captions)"
        ) from exc
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            if w.word.strip():
                words.append(Word(w.word.strip(), float(w.start), float(w.end)))
    return words
