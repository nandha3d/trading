"""Angel One scrip-master loader + token resolution.

Angel One publishes the full instrument list (token <-> contract) as a single
JSON. We cache it to disk (daily refresh) and resolve:
  - spot index token for an underlying
  - option tokens for an underlying + expiry (optionally a strike window)

Scrip entry shape (relevant fields):
  {"token":"57920","symbol":"NIFTY28MAR2422000CE","name":"NIFTY",
   "expiry":"28MAR2024","strike":"2200000","lotsize":"50",
   "instrumenttype":"OPTIDX","exch_seg":"NFO"}
Note: `strike` is x100 (2200000 -> 22000.0). `expiry` is DDMMMYYYY uppercase.
"""
from __future__ import annotations

import json
import logging
import time as _time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

from config import settings

logger = logging.getLogger("AngelScrip")

SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# SmartWebSocketV2 exchangeType codes
EXCH_NSE_CM = 1   # NSE cash / index
EXCH_NFO = 2      # NSE F&O

# Well-known NSE index spot tokens (exch_seg NSE). Used for spot subscription.
INDEX_SPOT_TOKENS = {
    "NIFTY": "26000",
    "BANKNIFTY": "26009",
    "FINNIFTY": "26037",
    "MIDCPNIFTY": "26074",
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _cache_path() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / "angelone_scrip.json"


def to_angel_expiry(iso: str) -> str:
    """'2024-03-28' -> '28MAR2024' (Angel One scrip-master format)."""
    d = date.fromisoformat(iso)
    return f"{d.day:02d}{_MONTHS[d.month - 1]}{d.year}"


def fetch_scrip_master(force: bool = False, max_age_hours: int = 24) -> list[dict]:
    """Download + cache the scrip master. Refresh if older than max_age_hours."""
    p = _cache_path()
    if p.exists() and not force:
        age_h = (_time.time() - p.stat().st_mtime) / 3600
        if age_h < max_age_hours:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Cached scrip master unreadable ({e}); refetching.")
    logger.info("Downloading Angel One scrip master...")
    resp = requests.get(SCRIP_URL, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not cache scrip master: {e}")
    logger.info(f"Scrip master loaded: {len(data):,} instruments")
    return data


def spot_token(underlying: str) -> tuple[str, int]:
    """Return (token, exchangeType) for the index spot of `underlying`."""
    tok = INDEX_SPOT_TOKENS.get(underlying.upper())
    if not tok:
        raise ValueError(f"No known spot token for {underlying}")
    return tok, EXCH_NSE_CM


def future_token(underlying: str, scrip: Optional[list[dict]] = None) -> tuple[str, str]:
    """Return (token, expiry_iso) for the nearest-expiry index future of `underlying`.

    Picks the soonest FUTIDX expiry that is today or later (the front-month
    contract). Raises ValueError if none found.
    """
    scrip = scrip if scrip is not None else fetch_scrip_master()
    want = underlying.upper()
    today = date.today()
    best: Optional[tuple[date, str]] = None
    for row in scrip:
        if row.get("exch_seg") != "NFO":
            continue
        if row.get("name") != want:
            continue
        if row.get("instrumenttype") != "FUTIDX":
            continue
        exp_raw = row.get("expiry", "")
        try:
            exp_d = datetime.strptime(exp_raw, "%d%b%Y").date()
        except ValueError:
            continue
        if exp_d < today:
            continue
        tok = row.get("token", "")
        if not tok:
            continue
        if best is None or exp_d < best[0]:
            best = (exp_d, tok)
    if best is None:
        raise ValueError(f"No FUTIDX contract found for {want}")
    return best[1], best[0].isoformat()


def resolve_option_tokens(
    underlying: str,
    expiry_iso: str,
    strikes: Optional[list[int]] = None,
    scrip: Optional[list[dict]] = None,
) -> dict[str, dict]:
    """Map token -> {strike, opt_type, lotsize, exch_type} for one underlying+expiry.

    If `strikes` given, restrict to those strikes (ATM window). Returns a dict
    keyed by token string so live ticks can be matched O(1).
    """
    scrip = scrip if scrip is not None else fetch_scrip_master()
    want_name = underlying.upper()
    want_exp = to_angel_expiry(expiry_iso)
    strike_set = set(strikes) if strikes else None

    out: dict[str, dict] = {}
    for row in scrip:
        if row.get("exch_seg") != "NFO":
            continue
        if row.get("name") != want_name:
            continue
        if row.get("instrumenttype") != "OPTIDX":
            continue
        if row.get("expiry") != want_exp:
            continue
        sym = row.get("symbol", "")
        opt_type = "CE" if sym.endswith("CE") else "PE" if sym.endswith("PE") else None
        if opt_type is None:
            continue
        try:
            strike = int(round(float(row["strike"]) / 100.0))
        except (KeyError, ValueError):
            continue
        if strike_set is not None and strike not in strike_set:
            continue
        out[row["token"]] = {
            "strike": strike,
            "opt_type": opt_type,
            "lotsize": int(row.get("lotsize", 0) or 0),
            "exch_type": EXCH_NFO,
        }
    if not out:
        logger.warning(f"No option tokens resolved for {want_name} {want_exp}")
    return out


def list_expiries(underlying: str, scrip: Optional[list[dict]] = None) -> list[str]:
    """Distinct expiries (ISO) available for an underlying, sorted ascending."""
    scrip = scrip if scrip is not None else fetch_scrip_master()
    want = underlying.upper()
    seen: set[str] = set()
    for row in scrip:
        if row.get("name") == want and row.get("instrumenttype") == "OPTIDX":
            exp = row.get("expiry", "")
            if exp:
                seen.add(exp)
    out = []
    for exp in seen:
        try:
            out.append(datetime.strptime(exp, "%d%b%Y").date().isoformat())
        except ValueError:
            continue
    return sorted(out)
