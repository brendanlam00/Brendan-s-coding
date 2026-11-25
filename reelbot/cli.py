"""reelbot command line.

  reelbot edit VIDEO               make the variations of one video (no posting)
  reelbot trial                    make variations of everything in inbox/, post each as a Trial Reel
  reelbot stats                    refresh and show views for everything posted
  reelbot promote                  post the most-viewed finished trial to your main feed
  reelbot run                      trial + promote in one go (put this on a schedule)
  reelbot check                    verify your Instagram credentials
  reelbot setup                    connect your Instagram (writes .env for you)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .editor import EditOptions
from .instagram import InstagramClient
from .pipeline import post_trials, promote, refresh_stats
from .store import Store
from .variants import VARIANTS, make_plan, parse_variants, render_variants


def _edit_opts(a: argparse.Namespace) -> EditOptions:
    return EditOptions(
        cut_silence=not a.no_cut, captions=not a.no_captions, reframe=a.reframe,
        hook=a.hook, max_seconds=a.max_seconds, whisper_model=a.whisper_model,
        silence_db=a.silence_db, min_silence=a.min_silence,
    )


def _add_edit_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("editing")
    g.add_argument("--no-cut", action="store_true", help="don't cut out pauses")
    g.add_argument("--no-captions", action="store_true", help="don't burn in captions")
    g.add_argument("--variants", help=f"comma list from: {', '.join(VARIANTS)} "
                   "(default: REELBOT_VARIANTS or letterbox,mirror,hook)")
    g.add_argument("--no-ai", action="store_true", help="don't ask Claude for hooks / cold open")
    g.add_argument("--reframe", choices=["auto", "crop", "blur"], default="auto",
                   help="framing for the full-screen variations")
    g.add_argument("--hook", help="text shown at the top for the first 3s")
    g.add_argument("--max-seconds", type=float, help="cap the edited length")
    g.add_argument("--whisper-model", default="small", help="tiny/base/small/medium")
    g.add_argument("--silence-db", type=float, default=-35.0)
    g.add_argument("--min-silence", type=float, default=0.5)


def _client(cfg: Config) -> InstagramClient:
    cfg.require_credentials()
    return InstagramClient(cfg.access_token, cfg.ig_user_id, cfg.api_version)


def _variants(a, cfg) -> list[str]:
    return parse_variants(a.variants or cfg.variants)


def _use_ai(a, cfg) -> bool:
    return cfg.ai_hooks and not a.no_ai


def cmd_edit(a, cfg):
    src = Path(a.video)
    variants = _variants(a, cfg)
    opts = _edit_opts(a)
    plan = make_plan(src, variants, _use_ai(a, cfg), opts.whisper_model)
    for n in plan.notes:
        print(n)
    out_dir = Path(a.output) if a.output else cfg.edited
    render_variants(src, out_dir, variants, opts, plan)


def cmd_trial(a, cfg):
    client = None if a.dry_run else _client(cfg)
    post_trials(cfg, Store(cfg.db_path), client, _edit_opts(a), limit=a.limit, dry_run=a.dry_run,
                variants=_variants(a, cfg), use_ai=_use_ai(a, cfg))


def cmd_stats(a, cfg):
    store = Store(cfg.db_path)
    if not a.offline:
        refresh_stats(store, _client(cfg))
    posts = store.posts()
    if not posts:
        print("Nothing posted yet.")
        return
    print(f"{'#':>3}  {'type':5}  {'status':7}  {'age':>5}  {'views':>8}  {'likes':>6}  "
          f"{'shares':>6}  {'saves':>5}  video")
    for p in posts:
        when = datetime.fromtimestamp(p.posted_at).strftime("%m-%d")
        print(f"{p.id:>3}  {p.kind:5}  {p.status:7}  {p.age_hours:>4.0f}h  {p.views:>8}  "
              f"{p.likes:>6}  {p.shares:>6}  {p.saved:>5}  {p.source_name}"
              + (f" [{p.variant}]" if p.variant else "") + f" ({when})")


def cmd_promote(a, cfg):
    promote(cfg, Store(cfg.db_path), _client(cfg), dry_run=a.dry_run, force=a.force)


def cmd_run(a, cfg):
    client = _client(cfg)
    store = Store(cfg.db_path)
    post_trials(cfg, store, client, _edit_opts(a), limit=a.limit,
                variants=_variants(a, cfg), use_ai=_use_ai(a, cfg))
    promote(cfg, store, client, force=a.force)


def cmd_check(a, cfg):
    client = _client(cfg)
    me = client._get(cfg.ig_user_id, fields="username,account_type,media_count")
    print(f"Connected to @{me.get('username')} ({me.get('account_type', 'professional')}, "
          f"{me.get('media_count', '?')} posts)")
    try:
        q = client.publishing_quota()
        print(f"Posts published via API in the last 24h: {q.get('quota_usage', '?')}"
              f" / {q.get('config', {}).get('quota_total', '?')}")
    except Exception as exc:  # quota endpoint is informational only
        print(f"(couldn't read publishing quota: {exc})")


def cmd_setup(a, cfg):
    from .setup import run_setup
    if run_setup(Path(a.env), cfg.api_version):
        cmd_check(a, Config.from_env(a.env))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelbot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default=".env", help="path to .env file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("edit", help="make the variations of one video without posting")
    p.add_argument("video")
    p.add_argument("-o", "--output", help="folder for the edited files (default: edited/)")
    _add_edit_flags(p)
    p.set_defaults(fn=cmd_edit)

    p = sub.add_parser("trial", help="edit inbox videos and post them as Trial Reels")
    p.add_argument("--limit", type=int, help="max videos to post this run")
    p.add_argument("--dry-run", action="store_true", help="edit only, don't post")
    _add_edit_flags(p)
    p.set_defaults(fn=cmd_trial)

    p = sub.add_parser("stats", help="refresh and show performance")
    p.add_argument("--offline", action="store_true", help="show saved numbers without calling Instagram")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("promote", help="post the most-viewed finished trial to your main feed")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_promote)

    p = sub.add_parser("run", help="trial + promote (for a schedule)")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")
    _add_edit_flags(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("setup", help="connect your Instagram account (writes .env)")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("check", help="verify Instagram credentials")
    p.set_defaults(fn=cmd_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.from_env(args.env)
    args.fn(args, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
