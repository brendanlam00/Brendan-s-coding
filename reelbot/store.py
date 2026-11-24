"""Local SQLite record of every Reel reelbot has posted and how it performed."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    edited_path TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                 -- trial | main
    status TEXT NOT NULL,               -- testing | winner | passed | live
    media_id TEXT,
    permalink TEXT,
    posted_at REAL NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    reach INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    shares INTEGER NOT NULL DEFAULT 0,
    saved INTEGER NOT NULL DEFAULT 0,
    stats_at REAL,
    promoted_media_id TEXT
);
"""

STAT_FIELDS = ("views", "reach", "likes", "comments", "shares", "saved")


@dataclass
class Post:
    id: int
    source_name: str
    edited_path: str
    caption: str
    kind: str
    status: str
    media_id: str | None
    permalink: str | None
    posted_at: float
    views: int
    reach: int
    likes: int
    comments: int
    shares: int
    saved: int
    stats_at: float | None
    promoted_media_id: str | None

    @property
    def age_hours(self) -> float:
        return (time.time() - self.posted_at) / 3600


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add(self, *, source_name: str, edited_path: str, caption: str, kind: str,
            status: str, media_id: str | None, permalink: str | None,
            posted_at: float | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO posts (source_name, edited_path, caption, kind, status, media_id,"
            " permalink, posted_at) VALUES (?,?,?,?,?,?,?,?)",
            (source_name, edited_path, caption, kind, status, media_id, permalink,
             posted_at if posted_at is not None else time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def posts(self, kind: str | None = None, status: str | None = None) -> list[Post]:
        q, args = "SELECT * FROM posts WHERE 1=1", []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if status:
            q += " AND status=?"
            args.append(status)
        return [Post(**dict(r)) for r in self.db.execute(q + " ORDER BY posted_at", args)]

    def update_stats(self, post_id: int, stats: dict[str, int]) -> None:
        vals = {k: int(stats.get(k, 0)) for k in STAT_FIELDS}
        self.db.execute(
            "UPDATE posts SET views=:views, reach=:reach, likes=:likes, comments=:comments,"
            " shares=:shares, saved=:saved, stats_at=:now WHERE id=:id",
            {**vals, "now": time.time(), "id": post_id},
        )
        self.db.commit()

    def set_status(self, post_id: int, status: str, promoted_media_id: str | None = None) -> None:
        self.db.execute("UPDATE posts SET status=?, promoted_media_id=COALESCE(?, promoted_media_id)"
                        " WHERE id=?", (status, promoted_media_id, post_id))
        self.db.commit()
