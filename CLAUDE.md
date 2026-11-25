# reelbot: instructions for Claude

This repo is the user's Instagram Reels pipeline. When the user talks to you in plain words, map
their request to these commands, run them from the repo root with the `.venv` active
(`source .venv/bin/activate`), and report the results in plain language.

| User says | Run |
|---|---|
| "edit my videos" / "make the versions" / "show me the variations first" | `reelbot trial --dry-run` (edits only; files land in `edited/`) |
| "post my reels" / "post the trial reels" | `reelbot trial` |
| "make N versions" / "add a normal vertical one too" | `reelbot trial --variants letterbox,mirror,hook,main` (pick names: letterbox, mirror, hook, main) |
| "how are they doing" / "look at the best performing ones" / "analytics" | `reelbot stats` |
| "post the best one to my main feed" | `reelbot promote --dry-run` first, tell the user which one won, then `reelbot promote` |
| "do everything" | `reelbot run` |
| "is it connected?" | `reelbot check` |

Workflow the user wants:
1. Each raw video in `inbox/` becomes 3 variations (letterbox with black bars, mirrored, new first
   3 seconds). Each is posted as its own **Trial Reel**.
2. After 24-48 h (`REELBOT_TRIAL_HOURS`), the single best performer by views is posted to the main feed
   as a **new post**. It is a fresh upload, never a share or repost, so it reaches a new audience.

Rules:
- Posting is public and can't be undone from here. Before `reelbot trial`, `run` or `promote`
  (without `--dry-run`), say what will be posted and get the user's OK, unless they just told you to post.
- Never print, log, or commit `.env`, tokens, or the App Secret. `reelbot setup` asks for them with
  hidden input, and the user must type them in themselves.
- Hook lines per video go in `inbox/<name>.hook.txt`, one per line, in variation order. Captions go in `inbox/<name>.txt`.
- If a command fails, read the error, fix the cause (missing ffmpeg: `brew install ffmpeg`; expired
  token: user reruns `reelbot setup`), and retry.
