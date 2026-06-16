"""Alice Blue login via pya3 — create a session and run a read-only sanity check.

Credentials are read from .env (config.settings). The live App Secret stays in
.env (gitignored); this script never prints secrets or the full session id.

pya3's session login uses USER_ID + API_KEY:
  - ALICE_USER_ID  = your Alice Blue client / login id
  - ALICE_API_KEY  = the pya3 API key (ANT web -> Apps -> "API Key")
The App Key / App Secret / redirect URL are the OAuth/publisher creds and are
stored for that flow, but get_session_id() does not use them.

SSL verification is left ON (disable_ssl=False) — never disable it.

Usage:
  python scripts/alice_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402


def _mask(v: str) -> str:
    if not v:
        return "-"
    return f"set ({len(v)} chars)"


def main() -> int:
    print("Alice Blue credential status:")
    print("  ALICE_USER_ID    :", settings.alice_user_id or "(missing)")
    print("  ALICE_API_KEY    :", _mask(settings.alice_api_key))
    print("  ALICE_APP_KEY    :", _mask(settings.alice_app_key))
    print("  ALICE_APP_SECRET :", _mask(settings.alice_app_secret))
    print("  ALICE_REDIRECT   :", settings.alice_redirect_url or "(missing)")

    missing = []
    if not settings.alice_user_id:
        missing.append("ALICE_USER_ID (your Alice Blue client / login id)")
    if not settings.alice_api_key:
        missing.append("ALICE_API_KEY (pya3 API key from ANT web -> Apps -> API Key)")
    if missing:
        print("\nCannot log in yet — add these to .env:")
        for m in missing:
            print("  -", m)
        return 1

    from pya3 import Aliceblue

    alice = Aliceblue(user_id=settings.alice_user_id,
                      api_key=settings.alice_api_key,
                      disable_ssl=False)
    try:
        sid = alice.get_session_id()
    except Exception as e:  # network / auth failure
        print("\nget_session_id() failed:", e)
        return 2
    ok = bool(sid and (sid.get("sessionID") if isinstance(sid, dict) else sid))
    print("\nsession:", "OK" if ok else f"unexpected response: {sid}")
    if not ok:
        return 2

    # read-only sanity calls — confirm the session actually works
    try:
        prof = alice.get_profile()
        acct = prof.get("accountId") or prof.get("emailAddr") if isinstance(prof, dict) else None
        print("profile :", acct or "received")
        bal = alice.get_balance()
        print("balance :", "received" if bal is not None else "empty")
    except Exception as e:
        print("sanity call error:", e)
        return 3
    print("\nLogin OK. Reminder: rotate the App Secret you shared in chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
