"""Upstox OAuth — exchange an auth code for an access token.

Flow (Upstox API v2):
  1) Open: https://api.upstox.com/v2/login/authorization/dialog
           ?response_type=code&client_id=<API_KEY>&redirect_uri=<REDIRECT>
  2) Log in; the browser redirects to <REDIRECT>?code=...
  3) POST https://api.upstox.com/v2/login/authorization/token  (form-encoded)
        code, client_id, client_secret, redirect_uri,
        grant_type=authorization_code
     -> access_token (valid until ~03:30 IST next day)

The token is saved to data/.upstox_session.json (data/ is gitignored).
Never commit the token or the API Secret. The Secret was exposed in chat ->
rotate it in the Upstox developer portal after this works.

Usage:
  python scripts/upstox_oauth.py                        # print the login URL
  python scripts/upstox_oauth.py "<full redirect URL>"  # finish (parses ?code=)
  python scripts/upstox_oauth.py <code>                 # finish with raw code
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402

DIALOG = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
SESSION_FILE = Path("data/.upstox_session.json")


def login_url() -> str:
    return (f"{DIALOG}?response_type=code&client_id={settings.upstox_api_key}"
            f"&redirect_uri={quote(settings.upstox_redirect_url, safe='')}")


def parse_code(argv):
    if not argv:
        return None
    a0 = argv[0]
    if a0.startswith("http"):
        return parse_qs(urlparse(a0).query).get("code", [None])[0]
    return a0


def main() -> int:
    if not settings.upstox_api_key or not settings.upstox_api_secret:
        print("Missing UPSTOX_API_KEY / UPSTOX_API_SECRET in .env")
        return 1

    code = parse_code(sys.argv[1:])
    if not code:
        print("STEP 1 — open this URL and log in:")
        print("   ", login_url())
        print("\nSTEP 2 — after login you land on", settings.upstox_redirect_url,
              "with ?code=...")
        print("STEP 3 — run:")
        print('    python scripts/upstox_oauth.py "<paste the full redirect URL>"')
        return 0

    data = {"code": code, "client_id": settings.upstox_api_key,
            "client_secret": settings.upstox_api_secret,
            "redirect_uri": settings.upstox_redirect_url,
            "grant_type": "authorization_code"}
    try:
        r = requests.post(TOKEN_URL, data=data, timeout=20, headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"})
    except requests.RequestException as e:
        print("request failed:", e)
        return 2
    try:
        body = r.json()
    except ValueError:
        print("non-JSON response", r.status_code, r.text[:200])
        return 2

    token = body.get("access_token")
    if not token:
        print("token exchange failed:", body)
        return 2

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"access_token": token,
           "user_id": body.get("user_id"),
           "email": body.get("email"),
           "saved_at": datetime.now(timezone.utc).isoformat()}
    SESSION_FILE.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print("token OK. user_id:", rec.get("user_id"))
    print("access_token:", f"received ({len(token)} chars)")
    print("saved ->", SESSION_FILE, "(gitignored)")
    print("Reminder: rotate the API Secret you shared in chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
