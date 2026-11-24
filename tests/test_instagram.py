import json

import pytest

from reelbot.instagram import InstagramClient, InstagramError


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._d


class FakeSession:
    def __init__(self, handler):
        self.calls, self.handler = [], handler

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params or {}))
        return self.handler("GET", url, params or {})

    def post(self, url, data=None, headers=None, timeout=None, params=None):
        body = data if isinstance(data, dict) else {"_stream": True}
        self.calls.append(("POST", url, body, headers or {}))
        return self.handler("POST", url, body)


def make(handler):
    s = FakeSession(handler)
    return InstagramClient("TOKEN", "123", "v23.0", session=s, poll_interval=0), s


def test_publish_trial_reel_flow(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 10)
    statuses = iter(["IN_PROGRESS", "FINISHED"])

    def handler(method, url, p):
        if method == "POST" and url.endswith("/123/media"):
            return Resp({"id": "C1"})
        if "rupload" in url:
            return Resp({"success": True})
        if method == "GET" and url.endswith("/C1"):
            return Resp({"status_code": next(statuses)})
        if url.endswith("/media_publish"):
            return Resp({"id": "M1"})
        if url.endswith("/M1"):
            return Resp({"permalink": "https://instagram.com/reel/abc"})
        raise AssertionError(url)

    client, s = make(handler)
    pub = client.publish_reel(video, "cap", trial_graduation="MANUAL")
    assert pub.media_id == "M1" and pub.permalink.endswith("/abc")
    create = s.calls[0][2]
    assert create["media_type"] == "REELS" and create["upload_type"] == "resumable"
    assert json.loads(create["trial_params"]) == {"graduation_strategy": "MANUAL"}
    upload = s.calls[1]
    assert upload[1] == "https://rupload.facebook.com/ig-api-upload/v23.0/C1"
    assert upload[3]["file_size"] == "10" and upload[3]["Authorization"] == "OAuth TOKEN"


def test_regular_reel_has_no_trial_params(tmp_path):
    client, s = make(lambda m, u, p: Resp({"id": "C"}))
    client.create_reel_container("hi")
    assert "trial_params" not in s.calls[0][2]


def test_processing_error_raises():
    client, _ = make(lambda m, u, p: Resp({"status_code": "ERROR", "status": "bad codec"}))
    with pytest.raises(InstagramError, match="bad codec"):
        client.wait_until_ready("C1")


def test_api_error_message_surfaces():
    client, _ = make(lambda m, u, p: Resp({"error": {"message": "Invalid token"}}, 400))
    with pytest.raises(InstagramError, match="Invalid token"):
        client.create_reel_container()


def test_insights_falls_back_to_plays():
    def handler(m, url, p):
        if "views" in p.get("metric", ""):
            return Resp({"error": {"message": "metric views not supported"}}, 400)
        return Resp({"data": [{"name": "plays", "values": [{"value": 900}]},
                              {"name": "likes", "values": [{"value": 40}]}]})
    client, _ = make(handler)
    assert client.media_insights("M1") == {"views": 900, "likes": 40}


def test_insights_total_value_shape():
    client, _ = make(lambda m, u, p: Resp({"data": [{"name": "views", "total_value": {"value": 1234}}]}))
    assert client.media_insights("M1")["views"] == 1234
