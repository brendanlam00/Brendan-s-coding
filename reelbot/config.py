"""Settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines; real env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    access_token: str = ""
    ig_user_id: str = ""
    api_version: str = "v23.0"
    inbox: Path = Path("inbox")
    edited: Path = Path("edited")
    processed: Path = Path("processed")
    db_path: Path = Path("reelbot.db")
    graduation: str = "MANUAL"
    trial_hours: float = 48.0
    min_views: int = 0
    default_caption: str = ""

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        load_dotenv(env_file)
        e = os.environ.get
        graduation = e("REELBOT_GRADUATION", "MANUAL").strip().upper()
        if graduation not in {"MANUAL", "SS_PERFORMANCE"}:
            raise ValueError("REELBOT_GRADUATION must be MANUAL or SS_PERFORMANCE")
        return cls(
            access_token=e("IG_ACCESS_TOKEN", ""),
            ig_user_id=e("IG_USER_ID", ""),
            api_version=e("IG_API_VERSION", "v23.0"),
            inbox=Path(e("REELBOT_INBOX", "inbox")),
            edited=Path(e("REELBOT_EDITED", "edited")),
            processed=Path(e("REELBOT_PROCESSED", "processed")),
            db_path=Path(e("REELBOT_DB", "reelbot.db")),
            graduation=graduation,
            trial_hours=float(e("REELBOT_TRIAL_HOURS", "48")),
            min_views=int(e("REELBOT_MIN_VIEWS", "0")),
            default_caption=e("REELBOT_DEFAULT_CAPTION", ""),
        )

    def require_credentials(self) -> None:
        missing = [n for n, v in (("IG_ACCESS_TOKEN", self.access_token),
                                  ("IG_USER_ID", self.ig_user_id)) if not v]
        if missing:
            raise SystemExit(
                f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in "
                "(see README: 'Connect your Instagram')."
            )
