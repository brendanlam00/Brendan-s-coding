import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from reelbot.ai import AIPlan, AIUnavailable, plan_with_claude
from reelbot.captions import Word
from reelbot.config import Config
from reelbot.editor import EditOptions, loudest_moment, probe
from reelbot.instagram import Published
from reelbot.pipeline import post_trials
from reelbot.store import Store
from reelbot.variants import VideoPlan, make_plan, parse_variants, render_variants

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def make_clip(path: Path, seconds=8, loud=(5, 7)):
    # quiet tone everywhere, much louder between `loud`
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds},"
                    f"volume='if(between(t,{loud[0]},{loud[1]}),1,0.1)':eval=frame",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
                   check=True)


def no_words(p, m):
    raise RuntimeError("no whisper")


def test_parse_variants():
    assert parse_variants(None) == ["letterbox", "mirror", "hook"]
    assert parse_variants("main, Mirror") == ["main", "mirror"]
    with pytest.raises(SystemExit):
        parse_variants("sideways")


@needs_ffmpeg
def test_loudest_moment_finds_loud_part(tmp_path):
    clip = tmp_path / "c.mp4"
    make_clip(clip)
    s, e = loudest_moment(clip, length=2.0)
    assert 4.5 <= s <= 5.5 and e - s == pytest.approx(2.0)


@needs_ffmpeg
def test_render_three_variants(tmp_path):
    clip = tmp_path / "c.mp4"
    make_clip(clip)
    plan = VideoPlan(hooks=["one", "two", "three"], cold_open=(5.0, 7.0))
    base = EditOptions(cut_silence=False, captions=False)
    out = render_variants(clip, tmp_path / "out", ["letterbox", "mirror", "hook"], base, plan,
                          log=lambda *_: None, transcriber=no_words)
    names = [n for n, _, _ in out]
    assert names == ["letterbox", "mirror", "hook"]
    for _, path, _ in out:
        info = probe(path)
        assert (info.width, info.height) == (1080, 1920)
    dur = {n: probe(p).duration for n, p, _ in out}
    assert dur["hook"] == pytest.approx(dur["mirror"] + 2.0, abs=0.3)  # cold open prepended
    # letterbox: top rows are black bars
    top = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "4", "-i", str(out[0][1]),
                          "-frames:v", "1", "-vf", "crop=1080:100:0:0,scale=1:1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    assert top and top[0] < 20


def test_make_plan_uses_hook_file_then_ai(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    (tmp_path / "v.hook.txt").write_text("My own hook\n")
    words = [Word("hi", 0, 0.5)]
    plan = make_plan(video, ["letterbox", "mirror", "hook"], use_ai=True,
                     transcriber=lambda p, m: words,
                     planner=lambda w, n: AIPlan(["ai 1", "ai 2", "ai 3"], (3.0, 6.0), "cap #x"))
    assert plan.hooks == ["My own hook", "ai 1", "ai 2"]
    assert plan.cold_open == (3.0, 6.0) and plan.caption == "cap #x"


@needs_ffmpeg
def test_make_plan_falls_back_to_loudness(tmp_path):
    clip = tmp_path / "c.mp4"
    make_clip(clip)

    def broken_planner(w, n):
        raise AIUnavailable("no key")

    plan = make_plan(clip, ["hook"], use_ai=True, transcriber=lambda p, m: [Word("a", 0, 1)],
                     planner=broken_planner)
    assert plan.cold_open and 4.0 <= plan.cold_open[0] <= 5.5
    assert any("no key" in n for n in plan.notes)


class FakeClient:
    def __init__(self, fail_variant=None):
        self.posted, self.fail_variant, self.n = [], fail_variant, 0

    def publish_reel(self, video, caption="", trial_graduation=None):
        from reelbot.instagram import InstagramError
        name = Path(video).stem.split("__")[-1]
        if name == self.fail_variant:
            raise InstagramError("boom")
        self.n += 1
        self.posted.append((name, caption, trial_graduation))
        return Published(f"M{self.n}", None)


@needs_ffmpeg
def test_post_trials_posts_each_variant_and_retries_failures(tmp_path):
    cfg = Config(inbox=tmp_path / "inbox", edited=tmp_path / "edited", processed=tmp_path / "done",
                 db_path=tmp_path / "db", ai_hooks=False)
    cfg.inbox.mkdir()
    make_clip(cfg.inbox / "day1.mp4")
    (cfg.inbox / "day1.txt").write_text("caption!")
    store = Store(cfg.db_path)
    opts = EditOptions(cut_silence=False, captions=False)

    client = FakeClient(fail_variant="mirror")
    post_trials(cfg, store, client, opts, log=lambda *_: None, transcriber=no_words)
    assert [p[0] for p in client.posted] == ["letterbox", "hook"]
    assert all(p[1] == "caption!" and p[2] == "MANUAL" for p in client.posted)
    assert (cfg.inbox / "day1.mp4").exists()  # kept for retry

    client2 = FakeClient()
    post_trials(cfg, store, client2, opts, log=lambda *_: None, transcriber=no_words)
    assert [p[0] for p in client2.posted] == ["mirror"]  # only the failed one
    assert not (cfg.inbox / "day1.mp4").exists()
    assert sorted(p.variant for p in store.posts(kind="trial")) == ["hook", "letterbox", "mirror"]


def test_plan_with_claude_maps_word_indexes():
    words = [Word(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(20)]
    payload = {"hooks": ["a", "b", "c", "d"], "cold_open_start_index": 10,
               "cold_open_end_index": 13, "caption": "nice #tag"}
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    plan = plan_with_claude(words, 3, client=client)
    assert plan.hooks == ["a", "b", "c"]
    assert plan.cold_open == pytest.approx((4.9, 7.05))  # word 10 start - 0.1 .. word 13 end + 0.15
    assert seen["model"] == "claude-opus-5-5" and seen["fallbacks"] == "default"
    assert seen["output_config"]["format"]["type"] == "json_schema"


def test_plan_with_claude_refusal():
    resp = SimpleNamespace(stop_reason="refusal", content=[])
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resp)))
    with pytest.raises(AIUnavailable):
        plan_with_claude([Word("x", 0, 1)], 3, client=client)


def test_store_upgrades_old_database(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT NOT NULL,"
                " edited_path TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,"
                " status TEXT NOT NULL, media_id TEXT, permalink TEXT, posted_at REAL NOT NULL,"
                " views INTEGER NOT NULL DEFAULT 0, reach INTEGER NOT NULL DEFAULT 0,"
                " likes INTEGER NOT NULL DEFAULT 0, comments INTEGER NOT NULL DEFAULT 0,"
                " shares INTEGER NOT NULL DEFAULT 0, saved INTEGER NOT NULL DEFAULT 0,"
                " stats_at REAL, promoted_media_id TEXT)")
    con.execute("INSERT INTO posts (source_name, edited_path, kind, status, posted_at)"
                " VALUES ('a','a','trial','testing',0)")
    con.commit()
    con.close()
    posts = Store(db).posts()
    assert posts[0].variant == ""
