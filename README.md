# reelbot

Drop your raw videos in a folder. reelbot then:

1. **Edits them.** It cuts dead air and pauses, reframes the video to vertical 9:16 (1080×1920), sets loudness to Instagram's level, burns in big word-by-word captions, and can show a hook line at the top for the first 3 seconds.
2. **Posts each one as a Trial Reel.** Trial Reels are shown to non-followers first, so a flop doesn't hurt your main page.
3. **Tracks views** on every trial through the official Instagram API.
4. **Posts the most-viewed trial to your main feed** once the trials have had time to run (48 hours by default).

```
inbox/  ──edit──▶  edited/  ──post as Trial Reels──▶  wait 48h  ──▶  top views ──▶ main feed
```

---

## 1. Install

You need Python 3.10+ and [ffmpeg](https://ffmpeg.org/download.html):

- **Mac:** `brew install ffmpeg`
- **Windows:** `winget install ffmpeg`

Then:

```bash
git clone https://github.com/brendanlam00/Brendan-s-coding.git
cd Brendan-s-coding
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
| `inbox/gym-tip.hook.txt` | hook text shown at the top for the first 3s, e.g. `Stop doing this at the gym` |

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
reelbot edit my-clip.mov --hook "3 things I wish I knew"
reelbot edit my-clip.mov --no-captions --reframe crop --max-seconds 60
```

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

Each `promote` run looks at every trial that has been live for at least `REELBOT_TRIAL_HOURS` (default 48). It takes the one with the **most views**; ties go to the one with more shares and saves. That one is reposted to your main feed as a regular Reel with the same caption. The other trials in that round are marked `passed` and never promoted. Trials that are still young keep running for the next round.

Set `REELBOT_MIN_VIEWS` (e.g. `1000`) if you only want to promote trials that clear a minimum.

### Run it automatically

Your videos live on your computer, so the schedule runs there too.

**Mac/Linux.** Run `crontab -e` and add this line to run every day at 6 pm:

```
0 18 * * * cd /path/to/Brendan-s-coding && /usr/bin/env reelbot run >> reelbot.log 2>&1
```

**Windows.** In Task Scheduler, create a daily task that runs `reelbot run` with "Start in" set to the project folder.

## Things to know

- **About "share to followers":** Instagram's API can publish Trial Reels, but it **can't** press the in-app "Share to followers" button. So reelbot puts the winner on your main feed by **posting it again as a regular Reel**. The original trial stays up for non-followers. If you'd rather use Instagram's built-in sharing, you have two options:
  - set `REELBOT_GRADUATION=SS_PERFORMANCE`, and Instagram automatically shares trials that perform well to your followers (reelbot then won't repost), or
  - run `reelbot promote --dry-run` to see the winner, then tap *Share to followers* on it yourself in the app.
- **Trial Reels have to be enabled on your account.** If Instagram rejects the trial post, check that your Professional account has Trial Reels in the app (it isn't available to every account yet).
- **Limits:** Instagram caps how many posts an app can publish per 24 hours. `reelbot check` shows how much you've used. Reels must be 3 seconds to 15 minutes long and under 300 MB; reelbot's output meets the format requirements.
- The upload uses Instagram's resumable upload, so videos go straight from your computer to Instagram with no file hosting needed. This upload method requires the Facebook-login setup described above.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the editor on real ffmpeg-generated clips, the Instagram API calls (mocked), and the winner-selection logic.
