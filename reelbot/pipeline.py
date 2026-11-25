"""The workflow: edit -> post as Trial Reels -> track views -> promote the winner."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .config import Config
from .captions import transcribe
from .editor import EditOptions
from .instagram import InstagramClient, InstagramError
from .store import Post, Store
from .variants import make_plan, parse_variants, render_variants

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}

Log = Callable[[str], None]


def find_new_videos(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def sidecar_text(video: Path, suffix: str) -> str | None:
    p = video.with_name(video.stem + suffix)
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def caption_for(video: Path, cfg: Config) -> str:
    return sidecar_text(video, ".txt") or cfg.default_caption


def _archive(video: Path, processed: Path) -> None:
    processed.mkdir(parents=True, exist_ok=True)
    for p in video.parent.glob(video.stem + "*"):
        if p.stem == video.stem or p.name.startswith(video.stem + "."):
            shutil.move(str(p), processed / p.name)


def post_trials(cfg: Config, store: Store, client: InstagramClient | None, opts: EditOptions,
                limit: int | None = None, dry_run: bool = False, log: Log = print,
                variants: list[str] | None = None, use_ai: bool | None = None,
                transcriber=transcribe, planner=None) -> list[int]:
    """Make several variations of every inbox video and post each as its own Trial Reel."""
    variants = variants or parse_variants(cfg.variants)
    use_ai = cfg.ai_hooks if use_ai is None else use_ai
    videos = find_new_videos(cfg.inbox)[: limit or None]
    if not videos:
        log(f"No new videos in {cfg.inbox}/")
        return []
    ids = []
    for video in videos:
        log(f"{video.name}: making {len(variants)} variations ({', '.join(variants)})")
        plan = make_plan(video, variants, use_ai, opts.whisper_model, transcriber, planner)
        for note in plan.notes:
            log(f"  {note}")
        caption = sidecar_text(video, ".txt") or plan.caption or cfg.default_caption
        already = {p.variant for p in store.posts(kind="trial") if p.source_name == video.name}
        todo = [v for v in variants if v not in already]
        if already & set(variants):
            log(f"  already posted: {', '.join(sorted(already & set(variants)))}")
        rendered = render_variants(video, cfg.edited, todo, opts, plan, log, transcriber)
        if dry_run:
            log(f"  [dry run] would post {len(rendered)} Trial Reels with caption: {caption[:80]!r}")
            continue
        assert client is not None
        failed = False
        for name, path, _ in rendered:
            log(f"  [{name}] uploading as a Trial Reel ...")
            try:
                pub = client.publish_reel(path, caption, trial_graduation=cfg.graduation)
            except InstagramError as exc:
                log(f"  [{name}] FAILED: {exc}")
                failed = True
                continue
            pid = store.add(source_name=video.name, edited_path=str(path), caption=caption,
                            kind="trial", status="testing", media_id=pub.media_id,
                            permalink=pub.permalink, variant=name)
            ids.append(pid)
            log(f"  [{name}] posted trial #{pid}: {pub.permalink or pub.media_id}")
        if failed:
            log(f"  Left {video.name} in the inbox; the next run retries only the failed variations.")
        else:
            _archive(video, cfg.processed)
    return ids


def refresh_stats(store: Store, client: InstagramClient, posts: list[Post] | None = None,
                  log: Log = print) -> None:
    posts = posts if posts is not None else store.posts(status="testing") + store.posts(status="live")
    for p in posts:
        if not p.media_id:
            continue
        try:
            store.update_stats(p.id, client.media_insights(p.media_id))
        except InstagramError as exc:
            log(f"  could not read stats for #{p.id} ({p.source_name}): {exc}")


def _score(p: Post) -> tuple:
    return (p.views, p.shares + p.saved, p.likes + p.comments, p.reach)


def pick_winner(trials: list[Post], trial_hours: float, min_views: int
                ) -> tuple[Post | None, list[Post]]:
    """Among trials that have run at least `trial_hours`, return (winner, everyone judged)."""
    ready = [t for t in trials if t.status == "testing" and t.age_hours >= trial_hours]
    if not ready:
        return None, []
    best = max(ready, key=_score)
    return (best if best.views >= min_views else None), ready


def promote(cfg: Config, store: Store, client: InstagramClient, dry_run: bool = False,
            force: bool = False, log: Log = print) -> Post | None:
    """Repost the most-viewed finished trial to the main feed as a regular Reel."""
    if cfg.graduation == "SS_PERFORMANCE" and not force:
        log("REELBOT_GRADUATION is SS_PERFORMANCE: Instagram shares winning trials to your "
            "followers automatically, so reelbot won't repost (use --force to override).")
        return None
    testing = store.posts(kind="trial", status="testing")
    refresh_stats(store, client, testing, log)
    testing = store.posts(kind="trial", status="testing")
    winner, judged = pick_winner(testing, cfg.trial_hours, cfg.min_views)
    if not judged:
        waiting = [f"{t.source_name} ({t.age_hours:.0f}h/{cfg.trial_hours:.0f}h)" for t in testing]
        log("No trials have finished testing yet." + (f" Running: {', '.join(waiting)}" if waiting else ""))
        return None

    log("Trial results:")
    for t in sorted(judged, key=_score, reverse=True):
        mark = "  <- WINNER" if winner and t.id == winner.id else ""
        label = f"{t.source_name} [{t.variant}]" if t.variant else t.source_name
        log(f"  {t.views:>8} views  {t.likes:>6} likes  {t.shares:>5} shares  {label}{mark}")

    if winner is None:
        log(f"No trial reached {cfg.min_views} views; nothing promoted this round.")
        if not dry_run:
            for t in judged:
                store.set_status(t.id, "passed")
        return None

    if dry_run:
        log(f"[dry run] would post {winner.source_name} [{winner.variant}] to the main feed as a new post.")
        return winner

    if not Path(winner.edited_path).is_file():
        raise SystemExit(f"Edited file for the winner is missing: {winner.edited_path}")
    log(f"Posting {winner.source_name} [{winner.variant}] to your main feed as a new post ...")
    pub = client.publish_reel(Path(winner.edited_path), winner.caption, trial_graduation=None)
    store.add(source_name=winner.source_name, edited_path=winner.edited_path,
              caption=winner.caption, kind="main", status="live", media_id=pub.media_id,
              permalink=pub.permalink, variant=winner.variant)
    store.set_status(winner.id, "winner", promoted_media_id=pub.media_id)
    for t in judged:
        if t.id != winner.id:
            store.set_status(t.id, "passed")
    log(f"Live on your feed: {pub.permalink or pub.media_id}")
    return winner
