import json

from reelbot.setup import run_setup, write_env


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._d


class FakeHTTP:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for suffix, resp in self.routes.items():
            if url.endswith(suffix):
                return resp(params) if callable(resp) else resp
        raise AssertionError(url)


ALL_PERMS = {"data": [{"permission": p, "status": "granted"} for p in (
    "instagram_basic", "instagram_content_publish", "instagram_manage_insights",
    "pages_show_list", "pages_read_engagement", "business_management")]}


def answers(*vals):
    it = iter(vals)
    return lambda prompt="": next(it)


def test_setup_writes_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nIG_ACCESS_TOKEN=\nIG_USER_ID=\nREELBOT_TRIAL_HOURS=24\n")
    http = FakeHTTP({
        "/me/permissions": Resp(ALL_PERMS),
        "/oauth/access_token": lambda p: Resp({"access_token": "LONG"}) if p["fb_exchange_token"] == "SHORT" else Resp({"error": {"message": "bad"}}, 400),
        "/me/accounts": Resp({"data": [{"name": "My Page", "instagram_business_account": {"id": "17841", "username": "me"}}]}),
    })
    secrets = answers("SHORT", "SECRET")
    ok = run_setup(env, http=http, ask=answers("APPID"), ask_secret=secrets, log=lambda *a: None)
    assert ok
    text = env.read_text()
    assert "IG_ACCESS_TOKEN=LONG" in text and "IG_USER_ID=17841" in text
    assert "# keep me" in text and "REELBOT_TRIAL_HOURS=24" in text
    exch = next(p for u, p in http.calls if u.endswith("/oauth/access_token"))
    assert exch["client_id"] == "APPID" and exch["client_secret"] == "SECRET"


def test_setup_reports_missing_permissions(tmp_path):
    logs = []
    http = FakeHTTP({"/me/permissions": Resp({"data": [{"permission": "instagram_basic", "status": "granted"}]})})
    ok = run_setup(tmp_path / ".env", http=http, ask=answers("APPID"),
                   ask_secret=answers("SHORT", "SECRET"), log=logs.append)
    assert not ok and "instagram_content_publish" in " ".join(logs)
    assert not (tmp_path / ".env").exists()


def test_setup_explains_unlinked_page(tmp_path):
    logs = []
    http = FakeHTTP({
        "/me/permissions": Resp(ALL_PERMS),
        "/oauth/access_token": Resp({"access_token": "LONG"}),
        "/me/accounts": Resp({"data": [{"name": "My Page"}]}),
    })
    ok = run_setup(tmp_path / ".env", http=http, ask=answers("APPID"),
                   ask_secret=answers("SHORT", "SECRET"), log=logs.append)
    assert not ok and "no Instagram account linked" in " ".join(logs)


def test_write_env_appends_new_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    write_env(env, {"A": "2", "B": "3"})
    assert env.read_text() == "A=2\nB=3\n"
