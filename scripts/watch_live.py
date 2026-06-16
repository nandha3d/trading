"""Watch Alice Blue realtime market feed (WebSocket) — live LTP table in terminal.

Prereq: a valid session saved by scripts/alice_oauth.py (data/.alice_session.json).
The WebSocket feed is live ONLY during market hours (09:15-15:30 IST, Mon-Fri).
Outside hours the socket still authenticates ("cf":"OK") but no ticks arrive.

Flow (Alice Blue open-api WS docs):
  1) POST /open-api/od/v1/profile/createWsSess   (Bearer userSession)
  2) connect wss://ws1.aliceblueonline.com/NorenWS
  3) auth: {"susertoken": sha256(sha256(userSession)), "t":"c",
            "actid": clientId+"_API", "uid": clientId+"_API", "source":"API"}
     -> {"t":"cf","k":"OK"}
  4) subscribe: {"k":"NSE|26000#NSE|26009", "t":"t"}
  5) feed: t=tk (full snapshot) / t=tf (partial update). lp=LTP, v=vol, oi, o/h/l/c.
  6) heartbeat {"k":"","t":"h"} every ~45s.

Usage:
  python scripts/watch_live.py                       # NIFTY + BANKNIFTY spot
  python scripts/watch_live.py NSE|26000 NFO|54957   # custom Exchange|token list
  python scripts/watch_live.py --secs 8              # connect, run 8s, exit (test)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import websocket  # websocket-client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402

SESS_FILE = Path("data/.alice_session.json")
WS_URL = "wss://ws1.aliceblueonline.com/NorenWS/"  # trailing slash: /NorenWS 301-redirects
CREATEWS = "https://a3.aliceblueonline.com/open-api/od/v1/profile/createWsSess"
DEFAULT_TOKENS = ["NSE|26000", "NSE|26009"]
KNOWN = {"26000": "NIFTY 50", "26009": "NIFTY BANK"}


def load_session() -> dict:
    if not SESS_FILE.exists():
        print("No session. Run:  python scripts/alice_oauth.py")
        sys.exit(1)
    d = json.loads(SESS_FILE.read_text(encoding="utf-8"))
    if not d.get("userSession") or not d.get("clientId"):
        print("Session file incomplete — re-run alice_oauth.py")
        sys.exit(1)
    return d


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def render(latest: dict, names: dict) -> None:
    hdr = "{:<18}{:>11}{:>9}{:>15}{:>13}{:>10}".format(
        "SYMBOL", "LTP", "%CHG", "VOLUME", "OI", "TIME")
    lines = [hdr, "-" * len(hdr)]
    for tk, row in latest.items():
        ft = row.get("ft")
        tstr = datetime.fromtimestamp(int(ft)).strftime("%H:%M:%S") if ft else "-"
        lines.append("{:<18}{:>11}{:>9}{:>15}{:>13}{:>10}".format(
            names.get(tk, tk)[:18], row.get("lp", "-"), row.get("pc", "-"),
            row.get("v", "-"), row.get("oi", "-"), tstr))
    sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def main() -> int:
    argv = sys.argv[1:]
    run_secs = 0
    if "--secs" in argv:
        i = argv.index("--secs")
        run_secs = int(argv[i + 1])
        del argv[i:i + 2]
    tokens = argv or DEFAULT_TOKENS

    sess = load_session()
    us = sess["userSession"]
    cid = str(sess["clientId"])

    try:
        r = requests.post(CREATEWS, json={"source": "API", "userId": cid},
                          headers={"Authorization": f"Bearer {us}"}, timeout=15)
        try:
            print("createWsSess:", r.status_code, r.json().get("status"))
        except ValueError:
            print("createWsSess:", r.status_code, r.text[:120])
    except requests.RequestException as e:
        print("createWsSess error (continuing):", e)

    ws = websocket.create_connection(WS_URL, timeout=10)
    ws.send(json.dumps({"susertoken": sha(sha(us)), "t": "c",
                        "actid": cid + "_API", "uid": cid + "_API", "source": "API"}))
    ack = json.loads(ws.recv())
    # connect-ack: docs show {"t":"cf","k":"OK"} but live server sends {"t":"ck","s":"OK"}
    if not (ack.get("s") == "OK" or ack.get("k") == "OK"):
        print("WS auth failed:", ack)
        ws.close()
        return 1
    print("WS connected. subscribing:", ", ".join(tokens))
    ws.send(json.dumps({"k": "#".join(tokens), "t": "t"}))

    latest: dict = {}
    names = dict(KNOWN)
    last_hb = time.time()
    start = time.time()
    ws.settimeout(1)
    try:
        while True:
            try:
                msg = ws.recv()
                if msg:
                    o = json.loads(msg)
                    if o.get("t") in ("tk", "tf"):
                        tk = o.get("tk")
                        if tk:
                            latest.setdefault(tk, {}).update(
                                {k: v for k, v in o.items() if v not in (None, "")})
                            if o.get("ts"):
                                names[tk] = o["ts"]
                        render(latest, names)
            except websocket.WebSocketTimeoutException:
                pass
            now = time.time()
            if now - last_hb > 45:
                ws.send(json.dumps({"k": "", "t": "h"}))
                last_hb = now
            if run_secs and now - start > run_secs:
                print("\n(--secs elapsed, exiting)")
                break
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
