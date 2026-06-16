"""
Upstox OAuth callback — allows daily token refresh via browser (phone or desktop).

Setup:
  1. In Upstox developer portal → set Redirect URI to:
       https://trade.animazon.in/api/oauth/upstox/callback
  2. In .env set:
       UPSTOX_REDIRECT_URL=https://trade.animazon.in/api/oauth/upstox/callback

Daily flow (30 seconds):
  1. Open https://trade.animazon.in/api/oauth/upstox  (shows the login link)
  2. Tap the link → Upstox login page
  3. Log in → browser redirects back to the callback
  4. Token auto-saved to data/.upstox_session.json  (valid until ~03:30 IST next day)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import settings

router = APIRouter()

TOKEN_URL     = "https://api.upstox.com/v2/login/authorization/token"
DIALOG        = "https://api.upstox.com/v2/login/authorization/dialog"
SESSION_FILE  = Path("data/.upstox_session.json")

# ------------------------------------------------------------------ helpers --

def _login_url() -> str:
    from urllib.parse import quote
    return (f"{DIALOG}?response_type=code"
            f"&client_id={settings.upstox_api_key}"
            f"&redirect_uri={quote(settings.upstox_redirect_url, safe='')}")


def _exchange(code: str) -> dict:
    r = requests.post(
        TOKEN_URL,
        data={
            "code":          code,
            "client_id":     settings.upstox_api_key,
            "client_secret": settings.upstox_api_secret,
            "redirect_uri":  settings.upstox_redirect_url,
            "grant_type":    "authorization_code",
        },
        headers={"accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    return r.json()


def _save_token(body: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "access_token": body["access_token"],
        "user_id":      body.get("user_id"),
        "email":        body.get("email"),
        "saved_at":     datetime.now(timezone.utc).isoformat(),
    }
    SESSION_FILE.write_text(json.dumps(rec, indent=2), encoding="utf-8")

# ------------------------------------------------------------------ routes ---

@router.get("/oauth/upstox", response_class=HTMLResponse)
async def upstox_login():
    """Show the Upstox login link. Open from phone / browser once a day."""
    if not settings.upstox_api_key:
        return HTMLResponse("<h2>UPSTOX_API_KEY not set in .env</h2>", status_code=500)
    url = _login_url()
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upstox Login</title>
<style>
  body{{font-family:sans-serif;background:#111;color:#eee;display:flex;align-items:center;
       justify-content:center;height:100vh;margin:0;flex-direction:column;gap:1rem}}
  a{{background:#2563eb;color:#fff;padding:.75rem 2rem;border-radius:.5rem;
     text-decoration:none;font-size:1.1rem;font-weight:700}}
  p{{color:#9ca3af;font-size:.85rem}}
</style></head><body>
<h2>Upstox Daily Token Refresh</h2>
<a href="{url}">Log in with Upstox</a>
<p>Token valid until ~03:30 IST next day</p>
</body></html>""")


@router.get("/oauth/upstox/callback", response_class=HTMLResponse)
async def upstox_callback(code: str = "", error: str = ""):
    """Upstox redirects here with ?code=. Exchanges code for token and saves."""
    if error:
        return HTMLResponse(f"<h2>Login error: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No code in callback</h2>", status_code=400)

    try:
        body = _exchange(code)
    except Exception as e:
        return HTMLResponse(f"<h2>Token exchange failed: {e}</h2>", status_code=500)

    token = body.get("access_token")
    if not token:
        return HTMLResponse(f"<h2>No token: {body}</h2>", status_code=500)

    _save_token(body)
    user = body.get("user_id", "unknown")
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Token Saved</title>
<style>
  body{{font-family:sans-serif;background:#111;color:#eee;display:flex;align-items:center;
       justify-content:center;height:100vh;margin:0;flex-direction:column;gap:.75rem}}
  .ok{{color:#10b981;font-size:2rem}}
</style></head><body>
<div class="ok">✓</div>
<h2>Token saved</h2>
<p>User: {user}</p>
<p style="color:#6b7280;font-size:.8rem">Valid until ~03:30 IST tomorrow. Close this tab.</p>
</body></html>""")
