# reelbot

Drop your raw videos in a folder. reelbot then:

1. **Makes 3 variations of each video** and edits all of them:
   - **letterbox**: horizontal, with black bars above and below
   - **mirror**: flipped left to right
   - **hook**: a new first few seconds, with the strongest moment moved to the front

   Each variation gets its own hook line. Every version also gets pauses cut out, levelled sound, captions, and Instagram-ready export.
2. **Posts every variation as a Trial Reel.** Trial Reels are shown to non-followers first, so testing never hurts your main page.
3. **Tracks the views** of every trial.
4. **After 24–48 hours, posts the best performer to your main feed as a brand-new post.** It's a fresh upload, not a "share" or a repost, so it reaches a new audience again.

```
inbox/clip.mp4 ─┬─ letterbox ─┐
                ├─ mirror ────┼─ Trial Reels ─ wait 24-48h ─ most views ─▶ NEW post on main feed
                └─ hook ──────┘
```

---

## 1. Install

**Mac (easiest):** download this folder, open Terminal in it, and run:

```bash
bash install.sh
source .venv/bin/activate
```

The installer works with the Mac's built-in Python. It sets up an environment in `.venv` and installs reelbot, and it tells you if ffmpeg is missing. Video editing needs ffmpeg: `brew install ffmpeg`.

**Manual install (any OS):** you need Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html):

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[captions]"
```

The `[captions]` part installs faster-whisper for auto-captions. It downloads a speech model the first time it runs. If you leave it out, everything else still works and videos just won't get captions.

## 2. Connect your Instagram (one-time, ~15 min)

Instagram only allows posting through its official API. You need these:

1. **A Professional account.** In the Instagram app, go to Settings → Account type → switch to **Creator** or **Business**. Then **link it to a Facebook Page** (Settings → Accounts Center, or from the Page's settings).
2. **A Meta app.** Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) → *Create app* → choose **Business** → add the **Instagram** product → pick **API setup with Facebook login**. You can leave the app in Development mode. Because you're the app's admin, it can post to your own account without going through App Review.
3. **Generate a token.** Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer/). Choose your app under **Meta App**, then **Get User Access Token**. Add these permissions:
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`, `business_management`.
   Click **Generate Access Token**, tick your Page and Instagram account in the popup, and copy the token.
4. **Get your App ID and App Secret.** In your app, go to **App settings → Basic** (click **Show** next to App Secret).
5. **Run setup:**

```bash
reelbot setup
```

Paste the token, App ID and App Secret when it asks. Your typing is hidden. Setup then:
- checks that the token has all the permissions,
- extends it to about 60 days,
- finds your Instagram account ID,
- writes everything to `.env`,
- runs `reelbot check`.

When the token expires (about 60 days), redo steps 3 and 5.

`.env` is in `.gitignore`. Never commit it or share your token.

## 3. Use it

### Daily workflow

Put raw clips in `inbox/`. For each video you can add optional text files with the same name:

| File | What it's for |
|---|---|
| `inbox/gym-tip.mp4` | the raw video |
| `inbox/gym-tip.txt` | the post caption and hashtags (if missing, `REELBOT_DEFAULT_CAPTION` is used) |
| `inbox/gym-tip.hook.txt` | hook lines, **one per line**: line 1 goes on the letterbox version, line 2 on the mirror version, line 3 on the hook version |

If there's no `.hook.txt`, Claude writes the hooks for you (see *Claude-written hooks* below). If that isn't set up either, the videos go out without hook text.

Then:

```bash
reelbot trial --dry-run   # edit only, so you can check edited/ before anything posts
reelbot trial             # edit + post everything in inbox/ as Trial Reels
reelbot stats             # see views, likes, shares and saves for everything posted
reelbot promote           # post the top-viewed finished trial to your main feed
```

`reelbot run` does `trial` and then `promote`. That's the command to put on a schedule.

Posted raw files move to `processed/`. Edited files stay in `edited/` because the winner gets re-uploaded from there.

### Edit one video without posting

```bash
reelbot edit my-clip.mov                               # makes edited/my-clip__letterbox.mp4, __mirror, __hook
reelbot edit my-clip.mov --variants main,mirror
reelbot edit my-clip.mov --hook "3 things I wish I knew" --no-captions
```

### Variations

| Name | What it does |
|---|---|
| `letterbox` | keeps the whole frame, horizontal, with black bars above and below; the hook sits in the top bar |
| `mirror` | flips the video left to right (text and captions are *not* flipped) |
| `hook` | new opening: the most gripping 1.5–4s moment plays first, then the full video |
| `main` | the standard full-screen vertical edit |

The default is `letterbox,mirror,hook`. Change it with `REELBOT_VARIANTS` in `.env`, or `--variants` on a single run.

### Claude-written hooks (optional)

If you set this up, Claude reads each video's transcript and writes a different hook line for every variation. It also picks the moment to use as the cold open for the `hook` variation and writes a caption if you didn't give one. Setup:

1. Install the extras (needs Python 3.10+; on a Mac: `brew install python`, then rerun `bash install.sh`):
   `pip install -e ".[captions,ai]"`
2. Add your Anthropic API key to `.env`: `ANTHROPIC_API_KEY=...` (get one at console.anthropic.com).

Without this, reelbot uses your `.hook.txt` lines and picks the loudest moment as the cold open.

Editing options (these also work on `trial` and `run`):

| Flag | Default | Meaning |
|---|---|---|
| `--no-cut` | off | keep pauses |
| `--min-silence` | `0.5` | only cut pauses at least this many seconds long |
| `--silence-db` | `-35` | how quiet counts as silence (raise to `-30` in noisy rooms) |
| `--reframe` | `auto` | `crop` fills the frame, `blur` fits the video over a blurred copy, `auto` picks one |
| `--no-captions` | off | skip auto-captions |
| `--whisper-model` | `small` | `tiny`/`base` run faster, `medium` is more accurate |
| `--hook` | none | hook text (overrides `.hook.txt`) |
| `--max-seconds` | none | cap the length |

### How the winner is picked

Each `promote` run looks at every trial (every variation of every video) that has been live for at least `REELBOT_TRIAL_HOURS` (default 48; set it to 24 if you prefer). It takes the one with the **most views**; ties go to the one with more shares and saves. That exact version is uploaded to your main feed as a **new post** with the same caption. The other trials in that round are marked `passed` and never promoted. Trials that are still young keep running for the next round.

Set `REELBOT_MIN_VIEWS` (e.g. `1000`) if you only want to promote trials that clear a minimum.

### Run it automatically

Your videos live on your computer, so the schedule runs there too.

**Mac/Linux.** Run `crontab -e` and add this line to run every day at 6 pm:

```
0 18 * * * cd /path/to/Brendan-s-coding && /usr/bin/env reelbot run >> reelbot.log 2>&1
```

**Windows.** In Task Scheduler, create a daily task that runs `reelbot run` with "Start in" set to the project folder.

## Things to know

- **Why a new post instead of "Share to followers":** a fresh upload counts as a new post, so it gets pushed to a new audience again ("more eyes"). Instagram's API can't press "Share to followers" anyway. If you'd rather let Instagram share winners itself, set `REELBOT_GRADUATION=SS_PERFORMANCE`; reelbot then won't post anything to the main feed.
- **Daily limits:** each video uses 3 trial posts. Instagram limits how many posts an app can publish per day, and third-party guides report a lower cap for Trial Reels (around 20 a day). Post about 5 videos a day or fewer.
- **Trial Reels have to be enabled on your account.** If Instagram rejects the trial post, check that your Professional account has Trial Reels in the app (it isn't available to every account yet).
- **Format:** `reelbot check` shows how many API posts you have left today. Reels must be 3 seconds to 15 minutes long and under 300 MB; reelbot's output meets the format requirements.
- The upload uses Instagram's resumable upload, so videos go straight from your computer to Instagram with no file hosting needed. This upload method requires the Facebook-login setup described above.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the editor on real ffmpeg-generated clips, the Instagram API calls (mocked), and the winner-selection logic.
