"""Automatic Reels editor built on ffmpeg.

What it does to each raw clip:
  1. Cuts dead air / long pauses (jump-cut style).
  2. Reframes to vertical 1080x1920 (center-crop if already vertical-ish,
     otherwise fits the video over a blurred copy of itself).
  3. Normalizes loudness to -14 LUFS (what Instagram/TikTok target).
  4. Burns in big word-by-word captions (needs faster-whisper) and an optional
     hook line at the top for the first 3 seconds.
  5. Exports an Instagram-spec MP4 (H.264 / AAC 48 kHz / 30 fps / faststart).
"""

from __future__ import annotations

import json
from array import array
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .captions import Word, build_ass, transcribe

W, H = 1080, 1920


@dataclass
class EditOptions:
    cut_silence: bool = True
    silence_db: float = -35.0      # quieter than this counts as silence
    min_silence: float = 0.5       # only cut pauses at least this long (s)
    padding: float = 0.12          # keep this much air around speech (s)
    reframe: str = "auto"          # auto | crop | blur | letterbox
    mirror: bool = False           # flip left-right
    cold_open: tuple[float, float] | None = None  # (start, end) in the source, shown first
    captions: bool = True
    hook: str | None = None
    hook_seconds: float = 3.0
    max_seconds: float | None = None
    whisper_model: str = "small"
    loudness: float = -14.0
    crf: int = 20


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


@dataclass
class EditResult:
    output: Path
    source_duration: float
    output_duration: float
    cuts: int = 0
    captioned: bool = False
    notes: list[str] = field(default_factory=list)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd[:3])} ...):\n{tail}")
    return proc


def probe(path: Path) -> MediaInfo:
    out = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(path)]).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"{path} has no video stream")
    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    if "rotate" in (video.get("tags") or {}):
        rotation = int(video["tags"]["rotate"])
    if abs(rotation) % 180 == 90:  # ffmpeg auto-rotates, so report displayed size
        w, h = h, w
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    return MediaInfo(duration, w, h, has_audio)


def detect_silences(path: Path, noise_db: float, min_silence: float) -> list[tuple[float, float]]:
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                 "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
                 "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None  # trailing silence has no end marker
        silences.append((max(0.0, s), e if e is not None else float("inf")))
    return silences


def keep_segments(duration: float, silences: list[tuple[float, float]],
                  padding: float = 0.12, min_keep: float = 0.25) -> list[tuple[float, float]]:
    """Invert silences into the segments to keep, with a little padding."""
    segs: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in sorted(silences):
        seg_end = min(duration, s + padding)
        if seg_end - cursor >= min_keep:
            segs.append((cursor, seg_end))
        cursor = max(cursor, min(duration, e - padding))
    if duration - cursor >= min_keep:
        segs.append((cursor, duration))
    # merge overlaps created by padding
    merged: list[tuple[float, float]] = []
    for s, e in segs:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged or [(0.0, duration)]


def loudest_moment(path: Path, length: float = 3.0, skip_start: float = 0.2,
                   sample_rate: int = 8000) -> tuple[float, float] | None:
    """Find the most energetic `length`-second stretch (after the first 20%).

    Used to pick a cold open when no transcript/AI pick is available: loud
    usually means the punchline, the reaction, or the payoff.
    """
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                           "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"],
                          capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    hop = sample_rate // 10  # 100 ms blocks
    energy = [sum(x * x for x in samples[i:i + hop]) / hop for i in range(0, len(samples) - hop + 1, hop)]
    win = max(1, int(length * 10))
    if len(energy) <= win:
        return None
    first = min(int(len(energy) * skip_start), len(energy) - win)
    run = sum(energy[first:first + win])
    best, best_i = run, first
    for i in range(first + 1, len(energy) - win + 1):
        run += energy[i + win - 1] - energy[i - 1]
        if run > best:
            best, best_i = run, i
    if best <= 0:
        return None
    return best_i / 10, (best_i + win) / 10


def _reframe_filter(info: MediaInfo, mode: str, src: str, dst: str) -> str:
    if mode == "auto":
        aspect = info.width / info.height
        mode = "crop" if 0.5 <= aspect <= 0.7 else "blur"
    if mode == "crop":
        return (f"[{src}]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1[{dst}]")
    if mode == "letterbox":  # whole frame visible, black bars filling the rest
        return (f"[{src}]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{dst}]")
    if mode == "blur":
        return (f"[{src}]split[rf_a][rf_b];"
                f"[rf_a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"boxblur=40:4,eq=brightness=-0.08[rf_bg];"
                f"[rf_b]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[rf_fg];"
                f"[rf_bg][rf_fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{dst}]")
    raise ValueError(f"unknown reframe mode {mode!r} (use auto, crop, blur or letterbox)")


def _encode_args(crf: int, copy_audio: bool = False) -> list[str]:
    audio = ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30",
            *audio, "-movflags", "+faststart"]


def _ass_path_escape(p: Path) -> str:
    s = str(p.resolve())
    return s.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def edit_video(
    src: Path,
    dst: Path,
    opts: EditOptions | None = None,
    transcriber: Callable[[Path, str], list[Word]] = transcribe,
) -> EditResult:
    opts = opts or EditOptions()
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    result = EditResult(dst, info.duration, info.duration)

    # 1. figure out which parts to keep
    segments = [(0.0, info.duration)]
    if opts.cut_silence and info.has_audio:
        silences = detect_silences(src, opts.silence_db, opts.min_silence)
        segments = keep_segments(info.duration, silences, opts.padding)
        result.cuts = max(0, len(segments) - 1)
    if opts.max_seconds:
        trimmed, total = [], 0.0
        for s, e in segments:
            if total >= opts.max_seconds:
                break
            e = min(e, s + (opts.max_seconds - total))
            trimmed.append((s, e))
            total += e - s
        segments = trimmed

    # 2. pass 1: (cold open) + cut + reframe + mirror + loudness
    parts = []
    concat_in = ""
    a_flag = 1 if info.has_audio else 0
    n_cold = 0
    if opts.cold_open:
        cs, ce = opts.cold_open
        cs, ce = max(0.0, cs), min(info.duration, ce)
        if ce - cs >= 0.5:
            n_cold = 1
            parts.append("[1:v]fps=30,setpts=PTS-STARTPTS[vcold];")
            concat_in += "[vcold]"
            if a_flag:
                parts.append("[1:a]asetpts=PTS-STARTPTS[acold];")
                concat_in += "[acold]"
    n = len(segments)
    vsplit = f"[0:v]fps=30,split={n}" + "".join(f"[vs{i}]" for i in range(n)) + ";" if n > 1 else ""
    asplit = ("[0:a]" + f"asplit={n}" + "".join(f"[as{i}]" for i in range(n)) + ";") if (n > 1 and a_flag) else ""
    parts.append(vsplit + asplit)
    for i, (s, e) in enumerate(segments):
        vin = f"vs{i}" if n > 1 else "0:v"
        pre = "" if n > 1 else "fps=30,"
        parts.append(f"[{vin}]{pre}trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];")
        concat_in += f"[v{i}]"
        if a_flag:
            ain = f"as{i}" if n > 1 else "0:a"
            parts.append(f"[{ain}]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}];")
            concat_in += f"[a{i}]"
    parts.append(f"{concat_in}concat=n={n + n_cold}:v=1:a={a_flag}[vcat]" + ("[acat];" if a_flag else ";"))
    parts.append(_reframe_filter(info, opts.reframe, "vcat", "vfr" if opts.mirror else "vout"))
    if opts.mirror:
        parts.append(";[vfr]hflip[vout]")
    if a_flag:
        parts.append(f";[acat]loudnorm=I={opts.loudness}:TP=-1.5:LRA=11,aresample=48000[aout]")
    graph = "".join(parts)
    inputs = ["-i", str(src)]
    if n_cold:
        inputs += ["-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src)]

    needs_burn = bool(opts.hook) or opts.captions
    with tempfile.TemporaryDirectory(prefix="reelbot_") as tmp:
        tmpdir = Path(tmp)
        pass1 = tmpdir / "pass1.mp4" if needs_burn else dst
        cmd = ["ffmpeg", "-hide_banner", "-y", *inputs, "-filter_complex", graph,
               "-map", "[vout]"]
        if a_flag:
            cmd += ["-map", "[aout]"]
        cmd += _encode_args(max(opts.crf - 2, 16) if needs_burn else opts.crf) + [str(pass1)]
        _run(cmd)

        # 3. captions + hook
        if needs_burn:
            words: list[Word] = []
            if opts.captions and a_flag:
                try:
                    words = transcriber(pass1, opts.whisper_model)
                    result.captioned = bool(words)
                except RuntimeError as exc:
                    result.notes.append(str(exc))
            if words or opts.hook:
                ass = tmpdir / "captions.ass"
                ass.write_text(build_ass(words, opts.hook, opts.hook_seconds), encoding="utf-8")
                cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(pass1),
                       "-vf", f"ass='{_ass_path_escape(ass)}'", "-map", "0:v"]
                if a_flag:
                    cmd += ["-map", "0:a"]
                cmd += _encode_args(opts.crf, copy_audio=bool(a_flag))
                _run(cmd + [str(dst)])
            else:
                shutil.move(str(pass1), dst)

    result.output_duration = probe(dst).duration
    if result.output_duration < 3:
        result.notes.append("Output is under 3s; Instagram rejects Reels shorter than 3 seconds.")
    return result
