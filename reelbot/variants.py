"""Turn one raw video into several trial-reel variations.

  letterbox  horizontal framing with black bars above and below
  mirror     flipped left-right
  hook       new first seconds: the strongest moment is moved to the front (cold open)
  main       the standard full-screen vertical edit
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .captions import Word, transcribe
from .editor import EditOptions, EditResult, edit_video, loudest_moment

VARIANTS: dict[str, dict] = {
    "main": {},
    "letterbox": {"reframe": "letterbox"},
    "mirror": {"mirror": True},
    "hook": {"cold_open": True},
}
DEFAULT_VARIANTS = ["letterbox", "mirror", "hook"]

Log = Callable[[str], None]


def parse_variants(text: str | None) -> list[str]:
    names = [v.strip().lower() for v in (text or "").split(",") if v.strip()] or DEFAULT_VARIANTS
    bad = [v for v in names if v not in VARIANTS]
    if bad:
        raise SystemExit(f"Unknown variant(s): {', '.join(bad)}. Choose from: {', '.join(VARIANTS)}")
    return names


@dataclass
class VideoPlan:
    hooks: list[str] = field(default_factory=list)
    cold_open: tuple[float, float] | None = None
    caption: str | None = None
    notes: list[str] = field(default_factory=list)


def make_plan(video: Path, variants: list[str], use_ai: bool = True, whisper_model: str = "small",
              transcriber: Callable[[Path, str], list[Word]] = transcribe,
              planner=None) -> VideoPlan:
    """Decide hook lines (one per variant) and the cold-open moment for one video."""
    plan = VideoPlan()
    hook_file = video.with_name(video.stem + ".hook.txt")
    if hook_file.is_file():
        plan.hooks = [ln.strip() for ln in hook_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    need_hooks = len(plan.hooks) < len(variants)
    need_cold = "hook" in variants
    if use_ai and (need_hooks or need_cold):
        try:
            words = transcriber(video, whisper_model)
            if planner is None:
                from .ai import plan_with_claude as planner
            ai = planner(words, len(variants))
            plan.hooks = plan.hooks + ai.hooks[: max(0, len(variants) - len(plan.hooks))]
            plan.cold_open = ai.cold_open
            plan.caption = ai.caption or None
            plan.notes.append("Claude wrote hooks and picked the cold open")
        except Exception as exc:
            plan.notes.append(f"AI hooks skipped ({exc})")

    if need_cold and plan.cold_open is None:
        plan.cold_open = loudest_moment(video)
        if plan.cold_open:
            plan.notes.append(f"cold open = loudest moment {plan.cold_open[0]:.1f}-{plan.cold_open[1]:.1f}s")
    return plan


def render_variants(video: Path, out_dir: Path, variants: list[str], base: EditOptions,
                    plan: VideoPlan, log: Log = print,
                    transcriber: Callable[[Path, str], list[Word]] = transcribe
                    ) -> list[tuple[str, Path, EditResult]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, name in enumerate(variants):
        spec = dict(VARIANTS[name])
        if spec.pop("cold_open", False):
            spec["cold_open"] = plan.cold_open
        hook = base.hook or (plan.hooks[i % len(plan.hooks)] if plan.hooks else None)
        opts = replace(base, hook=hook, **spec)
        out = out_dir / f"{video.stem}__{name}.mp4"
        log(f"  [{name}] editing ...")
        res = edit_video(video, out, opts, transcriber=transcriber)
        log(f"  [{name}] {out}  ({res.output_duration:.1f}s"
            + (f', hook: "{hook}"' if hook else "") + ")")
        for note in res.notes:
            log(f"  [{name}] note: {note}")
        results.append((name, out, res))
    return results
