"""One-off audit: compare our stored options data vs authoritative NSE Bhavcopy.

For N random trading days within our option coverage:
  - download the NSE F&O bhavcopy (old format pre 2024-07-08, UDiFF after)
  - for NIFTY/BANKNIFTY nearest expiry, pick a few strikes we actually store
  - compare EOD close + OI: bhavcopy vs our /api/oi-analysis last bucket

Run with the API server up:  py scripts/validate_bhav.py
"""
from __future__ import annotations

import io
import random
import sys
import zipfile
from datetime import date, datetime

import requests

API = "http://localhost:8000/api"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
UDIFF_CUTOVER = date(2024, 7, 8)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def bhav_url(d: date) -> str:
    if d >= UDIFF_CUTOVER:
        return f"https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return (f"https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d.year}/{MONTHS[d.month-1]}/fo{d.day:02d}{MONTHS[d.month-1]}{d.year}bhav.csv.zip")


def parse_bhav(content: bytes, d: date) -> dict:
    """Return {(symbol, expiry_iso, strike, opt_type): (close, oi)}."""
    import csv
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    text = z.read(name).decode("utf-8", "ignore").splitlines()
    rd = csv.DictReader(text)
    out = {}
    udiff = d >= UDIFF_CUTOVER
    for row in rd:
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        if udiff:
            sym = row.get("TckrSymb", "")
            otp = row.get("OptnTp", "")
            if otp not in ("CE", "PE") or sym not in ("NIFTY", "BANKNIFTY"):
                continue
            xp = row.get("XpryDt", "")  # YYYY-MM-DD
            try:
                exp_iso = datetime.strptime(xp, "%Y-%m-%d").date().isoformat()
            except ValueError:
                continue
            strike = int(float(row.get("StrkPric", 0)))
            close = float(row.get("ClsPric", 0) or 0)
            oi = int(float(row.get("OpnIntrst", 0) or 0))
        else:
            if row.get("INSTRUMENT", "") not in ("OPTIDX",):
                continue
            sym = row.get("SYMBOL", "")
            if sym not in ("NIFTY", "BANKNIFTY"):
                continue
            otp = row.get("OPTION_TYP", "")
            if otp not in ("CE", "PE"):
                continue
            try:
                exp_iso = datetime.strptime(row.get("EXPIRY_DT", ""), "%d-%b-%Y").date().isoformat()
            except ValueError:
                continue
            strike = int(float(row.get("STRIKE_PR", 0)))
            close = float(row.get("CLOSE", 0) or 0)
            oi = int(float(row.get("OPEN_INT", 0) or 0))
        out[(sym, exp_iso, strike, otp)] = (close, oi)
    return out


def api_get(path: str, **params):
    r = requests.get(f"{API}/{path}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def our_eod(underlying, day, expiry, strike):
    """Last (EOD) bucket from our oi-analysis: (ce_close, ce_oi, pe_close, pe_oi)."""
    j = api_get("oi-analysis", underlying=underlying, date=day, expiry=expiry,
                strike=strike, interval=60, mode="historical")
    rows = j.get("rows") or []
    if not rows:
        return None
    r = rows[0]  # newest = EOD
    return r["call_ltp"], r["call_oi"], r["put_ltp"], r["put_oi"]


def pct_diff(a, b):
    if a is None or b is None:
        return None
    if a == 0 and b == 0:
        return 0.0
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base * 100


def main(n_days=20):
    dates = api_get("flow/dates", underlying="NIFTY").get("dates", [])
    cand = [d for d in dates if d <= "2026-04-13"]
    random.seed(42)
    random.shuffle(cand)

    checked = 0
    comparisons = 0
    close_ok = oi_ok = 0
    print(f"{'DATE':11} {'SYM':9} {'EXP':11} {'STRK':7} {'TYP':3} "
          f"{'OUR_CLOSE':>10} {'NSE_CLOSE':>10} {'OUR_OI':>12} {'NSE_OI':>12}  VERDICT")
    print("-" * 110)

    for d in cand:
        if checked >= n_days:
            break
        day = date.fromisoformat(d)
        try:
            content = requests.get(bhav_url(day), headers=H, timeout=30).content
            if not content[:2] == b"PK":  # not a zip (holiday/missing)
                continue
            bhav = parse_bhav(content, day)
        except Exception:
            continue
        if not bhav:
            continue

        any_row = False
        for sym in ("NIFTY", "BANKNIFTY"):
            exps = api_get("oi-analysis/expiries", underlying=sym, date=d).get("expiries", [])
            if not exps:
                continue
            expiry = exps[0]
            strikes = api_get("oi-analysis/strikes", underlying=sym, date=d, expiry=expiry).get("strikes", [])
            if not strikes:
                continue
            mid = len(strikes) // 2
            for strike in {strikes[mid], strikes[max(0, mid - 4)], strikes[min(len(strikes) - 1, mid + 4)]}:
                ours = our_eod(sym, d, expiry, strike)
                if not ours:
                    continue
                ce_c, ce_oi, pe_c, pe_oi = ours
                for otp, oc, ooi in (("CE", ce_c, ce_oi), ("PE", pe_c, pe_oi)):
                    nse = bhav.get((sym, expiry, strike, otp))
                    if not nse:
                        continue
                    nc, noi = nse
                    cd = pct_diff(oc, nc)
                    od = pct_diff(ooi, noi)
                    comparisons += 1
                    if oc is None and ooi is None:
                        continue  # our last bucket had no trade for this leg
                    cok = cd is not None and cd <= 5
                    ook = od is not None and od <= 5
                    close_ok += cok
                    oi_ok += ook
                    any_row = True
                    if cok and ook:
                        verdict = "OK"
                    elif not cok:
                        verdict = f"CLOSE {cd:.0f}%" if cd is not None else "CLOSE n/a"
                    else:
                        verdict = f"OI {od:.0f}%" if od is not None else "OI n/a"
                    print(f"{d:11} {sym:9} {expiry:11} {strike:<7} {otp:3} "
                          f"{str(oc):>10} {str(nc):>10} {str(ooi):>12} {str(noi):>12}  {verdict}")
        if any_row:
            checked += 1

    print("-" * 110)
    print(f"days checked: {checked}   comparisons: {comparisons}")
    if comparisons:
        print(f"close match (<=5%): {close_ok}/{comparisons} = {close_ok/comparisons*100:.0f}%")
        print(f"OI    match (<=5%): {oi_ok}/{comparisons} = {oi_ok/comparisons*100:.0f}%")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
