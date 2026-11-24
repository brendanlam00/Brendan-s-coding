import time
from pathlib import Path

from reelbot.config import Config
from reelbot.instagram import Published
from reelbot.pipeline import _archive, find_new_videos, pick_winner, promote
from reelbot.store import Store


class FakeClient:
    def __init__(self, views):
        self.views, self.published = views, []

    def media_insights(self, media_id):
        return {"views": self.views[media_id], "likes": 1}

    def publish_reel(self, video, caption="", trial_graduation=None):
        self.published.append((Path(video).name, caption, trial_graduation))
        return Published("MAIN1", "https://instagram.com/reel/main")


def cfg(tmp_path, **kw):
    return Config(access_token="t", ig_user_id="1", db_path=tmp_path / "db.sqlite",
                  inbox=tmp_path / "inbox", edited=tmp_path / "edited",
                  processed=tmp_path / "processed", trial_hours=48, **kw)


def add_trial(store, tmp_path, name, media_id, hours_ago):
    f = tmp_path / f"{name}.mp4"
    f.write_bytes(b"v")
    return store.add(source_name=name, edited_path=str(f), caption=f"cap {name}", kind="trial",
                     status="testing", media_id=media_id, permalink=None,
                     posted_at=time.time() - hours_ago * 3600)


def test_promote_posts_most_viewed_finished_trial(tmp_path):
    c = cfg(tmp_path)
    store = Store(c.db_path)
    a = add_trial(store, tmp_path, "a", "M_a", 50)
    b = add_trial(store, tmp_path, "b", "M_b", 60)
    young = add_trial(store, tmp_path, "young", "M_y", 2)  # still testing, ignored
    client = FakeClient({"M_a": 500, "M_b": 4000, "M_y": 99999})

    winner = promote(c, store, client, log=lambda *_: None)

    assert winner.id == b
    assert client.published == [("b.mp4", "cap b", None)]  # regular Reel, not a trial
    status = {p.id: p.status for p in store.posts()}
    assert status[a] == "passed" and status[b] == "winner" and status[young] == "testing"
    assert [p.source_name for p in store.posts(kind="main")] == ["b"]


def test_promote_waits_when_nothing_finished(tmp_path):
    c = cfg(tmp_path)
    store = Store(c.db_path)
    add_trial(store, tmp_path, "a", "M_a", 5)
    client = FakeClient({"M_a": 10})
    assert promote(c, store, client, log=lambda *_: None) is None
    assert client.published == []


def test_min_views_blocks_weak_round(tmp_path):
    c = cfg(tmp_path, min_views=1000)
    store = Store(c.db_path)
    add_trial(store, tmp_path, "a", "M_a", 50)
    client = FakeClient({"M_a": 10})
    assert promote(c, store, client, log=lambda *_: None) is None
    assert client.published == [] and store.posts()[0].status == "passed"


def test_ss_performance_does_not_repost(tmp_path):
    c = cfg(tmp_path, graduation="SS_PERFORMANCE")
    store = Store(c.db_path)
    add_trial(store, tmp_path, "a", "M_a", 50)
    client = FakeClient({"M_a": 10})
    assert promote(c, store, client, log=lambda *_: None) is None
    assert client.published == []


def test_pick_winner_tiebreaks_on_shares_and_saves(tmp_path):
    store = Store(tmp_path / "db")
    for name in ("a", "b"):
        add_trial(store, tmp_path, name, name, 50)
    store.update_stats(1, {"views": 100, "shares": 1})
    store.update_stats(2, {"views": 100, "shares": 9})
    winner, judged = pick_winner(store.posts(), 48, 0)
    assert winner.source_name == "b" and len(judged) == 2


def test_inbox_and_archive(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for n in ("clip.mp4", "clip.txt", "clip.hook.txt", "clip2.mov", "notes.md"):
        (inbox / n).write_text("x")
    assert [p.name for p in find_new_videos(inbox)] == ["clip.mp4", "clip2.mov"]
    _archive(inbox / "clip.mp4", tmp_path / "done")
    assert sorted(p.name for p in inbox.iterdir()) == ["clip2.mov", "notes.md"]
    assert sorted(p.name for p in (tmp_path / "done").iterdir()) == ["clip.hook.txt", "clip.mp4", "clip.txt"]
