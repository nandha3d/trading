"""Alice Blue OAuth (vendor) login — exchange an authCode for a userSession.

Flow (per Alice Blue developer docs):
  1) Open:  https://ant.aliceblueonline.com/?appcode=<APP_CODE>
  2) Log in; the broker redirects to your Redirect URL with
     ?authCode=...&userId=...
  3) checksum = SHA-256(userId + authCode + apiSecret)
  4) POST https://a3.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails
     body {"checkSum": checksum}  -> returns userSession (JWT) + clientId

The userSession is saved to data/.alice_session.json (data/ is gitignored).
Never commit the session JWT or the App Secret. The App Secret was exposed in
chat -> rotate it in the developer portal after this works.

Usage:
  python scripts/alice_oauth.py
      -> prints the login URL + instructions
  python scripts/alice_oauth.py "<full redirect URL with authCode>"
  python scripts/alice_oauth.py <authCode> <userId>
      -> completes the exchange and saves the session
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402

GETUSER_URL = "https://a3.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails"
LOGIN_BASE = "https://ant.aliceblueonline.com/?appcode="
SESSION_FILE = Path("data/.alice_session.json")


def login_url() -> str:
    return LOGIN_BASE + settings.alice_app_key


def parse_args(argv):
    if not argv:
        return None, None
    a0 = argv[0]
    if a0.startswith("http"):
        q = parse_qs(urlparse(a0).query)
        return q.get("authCode", [None])[0], q.get("userId", [None])[0]
    return a0, (argv[1] if len(argv) > 1 else (settings.alice_user_id or None))


def main() -> int:
    if not settings.alice_app_key or not settings.alice_app_secret:
        print("Missing ALICE_APP_KEY / ALICE_APP_SECRET in .env")
        return 1

    auth_code, user_id = parse_args(sys.argv[1:])
    if not auth_code:
        print("STEP 1 — open this URL and log in with your Alice Blue credentials:")
        print("   ", login_url())
        print("\nSTEP 2 — after login you are redirected to your Redirect URL")
        print("          (", settings.alice_redirect_url or "<set ALICE_REDIRECT_URL>",
              ") with ?authCode=...&userId=...")
        print("\nSTEP 3 — run ONE of these to finish:")
        print('    python scripts/alice_oauth.py "<paste the full redirect URL>"')
        print("    python scripts/alice_oauth.py <authCode> <userId>")
        return 0

    if not user_id:
        print("userId missing — pass it as the 2nd arg or set ALICE_USER_ID in .env")
        return 1

    checksum = hashlib.sha256(
        (user_id + auth_code + settings.alice_app_secret).encode()).hexdigest()
    try:
        r = requests.post(GETUSER_URL, json={"checkSum": checksum}, timeout=20)
    except requests.RequestException as e:
        print("request failed:", e)
        return 2
    try:
        body = r.json()
    except ValueError:
        print("non-JSON response", r.status_code, r.text[:200])
        return 2

    if body.get("stat") != "Ok":
        print("login failed:", body.get("emsg") or body)
        return 2

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"clientId": body.get("clientId"), "userId": user_id,
           "userSession": body.get("userSession"),
           "saved_at": datetime.now(timezone.utc).isoformat()}
    SESSION_FILE.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    sess = rec["userSession"] or ""
    print("session OK. clientId:", rec["clientId"])
    print("userSession:", f"received ({len(sess)} chars)")
    print("saved ->", SESSION_FILE, "(gitignored)")
    print("Reminder: rotate the App Secret you shared in chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
