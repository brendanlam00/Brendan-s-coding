"""`reelbot setup`: turn a Graph API Explorer token into a working .env.

You paste: the token from Graph API Explorer, your App ID, and your App Secret.
It then: swaps the short (1-hour) token for a 60-day one, finds your Instagram
account ID, writes both into .env, and confirms the connection.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import requests

from .instagram import GRAPH, InstagramError

REQUIRED_PERMS = {
    "instagram_basic", "instagram_content_publish", "instagram_manage_insights",
    "pages_show_list", "pages_read_engagement",
}


def _get(http: requests.Session, url: str, **params) -> dict:
    resp = http.get(url, params=params, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or "error" in data:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise InstagramError(err.get("message") or resp.text[:300])
    return data


def exchange_token(http, version: str, app_id: str, app_secret: str, short_token: str) -> str:
    data = _get(http, f"{GRAPH}/{version}/oauth/access_token", grant_type="fb_exchange_token",
                client_id=app_id, client_secret=app_secret, fb_exchange_token=short_token)
    return data["access_token"]


def missing_permissions(http, version: str, token: str) -> set[str]:
    data = _get(http, f"{GRAPH}/{version}/me/permissions", access_token=token)
    granted = {p["permission"] for p in data.get("data", []) if p.get("status") == "granted"}
    return REQUIRED_PERMS - granted


def find_instagram_accounts(http, version: str, token: str) -> tuple[list[dict], int]:
    data = _get(http, f"{GRAPH}/{version}/me/accounts", access_token=token,
                fields="name,instagram_business_account{id,username}")
    out = []
    for page in data.get("data", []):
        ig = page.get("instagram_business_account")
        if ig:
            out.append({"page": page.get("name", "?"), "id": ig["id"],
                        "username": ig.get("username", "?")})
    return out, len(data.get("data", []))


def write_env(path: Path, values: dict[str, str]) -> None:
    """Set keys in .env, keeping every other line as it was."""
    if path.exists():
        lines = path.read_text().splitlines()
    elif Path(".env.example").exists():
        lines = Path(".env.example").read_text().splitlines()
    else:
        lines = []
    remaining = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def run_setup(env_path: Path, version: str = "v23.0", http: requests.Session | None = None,
              ask=input, ask_secret=getpass.getpass, log=print) -> bool:
    http = http or requests.Session()
    log("reelbot setup. Your inputs are hidden and only saved to .env on this computer.\n")
    short = ask_secret("1) Paste the token from Graph API Explorer: ").strip()
    app_id = ask("2) App ID (App settings > Basic): ").strip()
    secret = ask_secret("3) App Secret (App settings > Basic > Show): ").strip()

    try:
        missing = missing_permissions(http, version, short)
    except InstagramError as exc:
        log(f"\nThat token didn't work: {exc}\nGenerate a fresh one in Graph API Explorer and try again.")
        return False
    if missing:
        log(f"\nThe token is missing: {', '.join(sorted(missing))}\n"
            "Add them in Graph API Explorer, click Generate Access Token again, then rerun setup.")
        return False

    try:
        token = exchange_token(http, version, app_id, secret, short)
    except InstagramError as exc:
        log(f"\nCouldn't extend the token: {exc}\nDouble-check the App ID and App Secret "
            "(they must be from the same app you picked in Graph API Explorer).")
        return False
    log("OK  extended token to ~60 days")

    accounts, n_pages = find_instagram_accounts(http, version, token)
    if not accounts:
        if n_pages == 0:
            log("\nNo Facebook Pages came back. In Graph API Explorer, click Generate Access Token "
                "again and make sure you tick your Page in the popup.")
        else:
            log("\nYour Page has no Instagram account linked. In Instagram: Edit profile > Page > "
                "connect it, then rerun setup.")
        return False
    if len(accounts) == 1:
        acct = accounts[0]
    else:
        for i, a in enumerate(accounts, 1):
            log(f"  {i}. @{a['username']} (Page: {a['page']})")
        acct = accounts[int(ask("Which Instagram account? ").strip()) - 1]
    log(f"OK  found @{acct['username']} (ID {acct['id']})")

    write_env(env_path, {"IG_ACCESS_TOKEN": token, "IG_USER_ID": acct["id"],
                         "IG_API_VERSION": version})
    log(f"OK  saved to {env_path}\n\nAll set. Run:  reelbot check")
    return True
