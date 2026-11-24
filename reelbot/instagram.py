"""Instagram Graph API client: publish Reels / Trial Reels and read their insights.

Uses the resumable upload flow, so videos go straight from your computer to
Instagram — no need to host them at a public URL first.
Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"

INSIGHT_METRICS = ["views", "reach", "likes", "comments", "shares", "saved"]
LEGACY_INSIGHT_METRICS = ["plays", "reach", "likes", "comments", "shares", "saved"]


class InstagramError(RuntimeError):
    pass


@dataclass
class Published:
    media_id: str
    permalink: str | None = None


class InstagramClient:
    def __init__(self, access_token: str, ig_user_id: str, api_version: str = "v23.0",
                 session: requests.Session | None = None, poll_interval: float = 5.0,
                 poll_timeout: float = 600.0):
        self.token = access_token
        self.user_id = ig_user_id
        self.version = api_version
        self.http = session or requests.Session()
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    # -- low level ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.version}/{path.lstrip('/')}"

    def _check(self, resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            msg = err.get("error_user_msg") or err.get("message") or resp.text[:300]
            raise InstagramError(f"Instagram API error {resp.status_code}: {msg}")
        return data

    def _get(self, path: str, **params) -> dict:
        params["access_token"] = self.token
        return self._check(self.http.get(self._url(path), params=params, timeout=60))

    def _post(self, path: str, **params) -> dict:
        params["access_token"] = self.token
        return self._check(self.http.post(self._url(path), data=params, timeout=60))

    # -- publishing ----------------------------------------------------------
    def create_reel_container(self, caption: str = "", trial_graduation: str | None = None,
                              cover_offset_ms: int | None = None) -> str:
        """Create an empty Reels container for resumable upload. Returns container id.

        trial_graduation: None for a normal Reel, or "MANUAL" / "SS_PERFORMANCE" to
        publish as a Trial Reel (shown to non-followers first).
        """
        params: dict = {"media_type": "REELS", "upload_type": "resumable", "caption": caption}
        if trial_graduation:
            params["trial_params"] = json.dumps({"graduation_strategy": trial_graduation})
        if cover_offset_ms is not None:
            params["thumb_offset"] = str(cover_offset_ms)
        data = self._post(f"{self.user_id}/media", **params)
        return data["id"]

    def upload_video(self, container_id: str, video: Path) -> None:
        size = video.stat().st_size
        with open(video, "rb") as fh:
            resp = self.http.post(
                f"{RUPLOAD}/{self.version}/{container_id}",
                headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                         "file_size": str(size)},
                data=fh, timeout=600,
            )
        data = self._check(resp)
        if data.get("success") is False:
            raise InstagramError(f"Upload failed: {data}")

    def wait_until_ready(self, container_id: str) -> None:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            data = self._get(container_id, fields="status_code,status")
            code = data.get("status_code")
            if code == "FINISHED":
                return
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"Instagram could not process the video: {data.get('status')}")
            if time.monotonic() > deadline:
                raise InstagramError("Timed out waiting for Instagram to process the video")
            time.sleep(self.poll_interval)

    def publish_container(self, container_id: str) -> str:
        return self._post(f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def publish_reel(self, video: Path, caption: str = "",
                     trial_graduation: str | None = None) -> Published:
        container = self.create_reel_container(caption, trial_graduation)
        self.upload_video(container, Path(video))
        self.wait_until_ready(container)
        media_id = self.publish_container(container)
        permalink = None
        try:
            permalink = self._get(media_id, fields="permalink").get("permalink")
        except InstagramError:
            pass
        return Published(media_id, permalink)

    # -- insights --------------------------------------------------------------
    def media_insights(self, media_id: str) -> dict[str, int]:
        last_err: InstagramError | None = None
        for metrics in (INSIGHT_METRICS, LEGACY_INSIGHT_METRICS):
            try:
                data = self._get(f"{media_id}/insights", metric=",".join(metrics))
            except InstagramError as exc:
                last_err = exc
                continue
            out: dict[str, int] = {}
            for item in data.get("data", []):
                values = item.get("values") or [{}]
                val = item.get("total_value", {}).get("value", values[0].get("value", 0))
                name = "views" if item["name"] == "plays" else item["name"]
                out[name] = int(val or 0)
            return out
        raise last_err or InstagramError("no insights returned")

    def publishing_quota(self) -> dict:
        data = self._get(f"{self.user_id}/content_publishing_limit", fields="config,quota_usage")
        return (data.get("data") or [{}])[0]
