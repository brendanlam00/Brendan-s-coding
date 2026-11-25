"""Optional: let Claude write hooks and pick the cold-open moment.

Needs `pip install 'reelbot[ai]'` (Python 3.10+) and an Anthropic API key
(ANTHROPIC_API_KEY in .env). Without them reelbot still works: it uses your
.hook.txt lines and picks the cold open by loudness instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .captions import Word

MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "hooks": {"type": "array", "items": {"type": "string"}},
        "cold_open_start_index": {"type": "integer"},
        "cold_open_end_index": {"type": "integer"},
        "caption": {"type": "string"},
    },
    "required": ["hooks", "cold_open_start_index", "cold_open_end_index", "caption"],
    "additionalProperties": False,
}

PROMPT = """You are editing a short-form vertical video (Instagram Reel) for testing as Trial Reels.
Here is the transcript as numbered words:

{words}

Return:
- hooks: {n} different on-screen hook lines for the first 3 seconds. Each under 9 words, punchy,
  curiosity-driven, in the creator's voice, no emojis, no hashtags. Make them genuinely different angles
  (e.g. bold claim, question, "stop doing X", result-first).
- cold_open_start_index / cold_open_end_index: the word range (inclusive) of the single most
  gripping 2-4 second moment to show FIRST as a cold open (a payoff, surprising line, or strong
  statement). Prefer a moment from the middle or end, not the first sentence.
- caption: an Instagram caption (1-2 short lines + 3-5 relevant hashtags)."""


@dataclass
class AIPlan:
    hooks: list[str]
    cold_open: tuple[float, float] | None
    caption: str


class AIUnavailable(RuntimeError):
    pass


def plan_with_claude(words: list[Word], n_hooks: int, client=None) -> AIPlan:
    if not words:
        raise AIUnavailable("no speech found to write hooks from")
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            raise AIUnavailable("Claude hooks need: pip install 'reelbot[ai]' (Python 3.10+)") from exc
        client = anthropic.Anthropic()

    numbered = " ".join(f"[{i}]{w.text}" for i, w in enumerate(words))
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": PROMPT.format(words=numbered, n=n_hooks)}],
        )
    except Exception as exc:  # auth missing, network, rate limit: fall back gracefully
        raise AIUnavailable(f"Claude request failed: {exc}") from exc
    if response.stop_reason == "refusal":
        raise AIUnavailable("Claude declined this transcript")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AIUnavailable("Claude returned an unreadable answer") from exc

    hooks = [h.strip() for h in data.get("hooks", []) if h and h.strip()][:n_hooks]
    cold = None
    a, b = data.get("cold_open_start_index"), data.get("cold_open_end_index")
    if isinstance(a, int) and isinstance(b, int) and 0 <= a <= b < len(words):
        start, end = words[a].start, words[b].end
        end = min(max(end, start + 1.5), start + 4.0)  # keep it 1.5-4 s
        cold = (max(0.0, start - 0.1), end + 0.15)
    return AIPlan(hooks, cold, data.get("caption", "").strip())
