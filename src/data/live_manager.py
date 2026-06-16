import asyncio
import random
import json
import logging
from datetime import datetime, date, time
from typing import Optional, Dict, List
import polars as pl

from src.data import storage
from src.data.options_math import calculate_iv, calculate_greeks, bs_price

logger = logging.getLogger("LiveManager")
logger.setLevel(logging.INFO)

RISK_FREE = 0.065

def fetch_yahoo_spot(underlying: str) -> Optional[float]:
    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    ticker = "^NSEI" if underlying.upper() == "NIFTY" else "^NSEBANK"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            meta = data['chart']['result'][0]['meta']
            return float(meta['regularMarketPrice'])
    except Exception as e:
        logger.error(f"Error fetching Yahoo spot price for {underlying}: {e}")
    return None

class LiveSession:
    def __init__(self, underlying: str, expiry: str):
        self.underlying = underlying.upper()
        self.expiry = expiry
        self.spot_price: float = 0.0
        self.base_spot_price: float = 0.0
        self.chain: Dict[int, Dict] = {}
        self.pcr_trend: List[Dict] = []
        self.block_trades: List[Dict] = []
        self.last_update: str = ""
        self.lot_size = 65 if self.underlying == "NIFTY" else 30  # current NSE sizes (Jan 2026 revision)
        self.is_active = False
        self._seed_data()

    def _seed_data(self):
        """Seed the live simulation using the first minute of options data from database."""
        storage.init_db()
        con = storage.db().cursor()
        try:
            exp_date = date.fromisoformat(self.expiry)
            today_date = date.today()
            
            # If the contract expiry is today or in the future, seed from real-time Yahoo spot price
            if exp_date >= today_date:
                yahoo_spot = fetch_yahoo_spot(self.underlying)
                if yahoo_spot:
                    self.spot_price = yahoo_spot
                    logger.info(f"Seeded live session spot from Yahoo Finance for {self.underlying}: {self.spot_price}")
                else:
                    self.spot_price = 18000.0 if self.underlying == "NIFTY" else 42000.0
                    logger.warning(f"Yahoo Finance fetch failed, using fallback spot for {self.underlying}: {self.spot_price}")
                self.base_spot_price = self.spot_price
                self._generate_dummy_chain()
                return

            # Find the first timestamp of data for this underlying/expiry in options_1m
            ts_row = con.execute(
                "SELECT MIN(ts) FROM options_1m WHERE underlying = ? AND expiry = ?",
                [self.underlying, exp_date]
            ).fetchone()
            
            if not ts_row or not ts_row[0]:
                # Fallback to Yahoo live spot price first, then to hardcoded defaults
                yahoo_spot = fetch_yahoo_spot(self.underlying)
                if yahoo_spot:
                    self.spot_price = yahoo_spot
                    logger.info(f"Seeded live session spot from Yahoo Finance for {self.underlying}: {self.spot_price}")
                else:
                    self.spot_price = 18000.0 if self.underlying == "NIFTY" else 42000.0
                self.base_spot_price = self.spot_price
                self._generate_dummy_chain()
                return

            ts_val = ts_row[0]
            
            # Read spot price at that time
            spot_row = con.execute(
                "SELECT close FROM spot_1m WHERE underlying = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                [self.underlying, ts_val]
            ).fetchone()
            self.spot_price = spot_row[0] if spot_row else (18000.0 if self.underlying == "NIFTY" else 42000.0)
            self.base_spot_price = self.spot_price


            # Read all option rows for this timestamp
            options_rows = con.execute(
                """
                SELECT strike, option_type, close, volume, oi
                FROM options_1m
                WHERE underlying = ? AND expiry = ? AND ts = ?
                """,
                [self.underlying, exp_date, ts_val]
            ).fetchall()
        except Exception as e:
            logger.error(f"Error querying db for live seed: {e}")
            self._generate_dummy_chain()
            return
        finally:
            con.close()

        try:
            exp_dt = datetime.combine(exp_date, time(15, 30))
            secs = max((exp_dt - ts_val).total_seconds(), 60.0)
            t_years = secs / (365.0 * 86400)

            for strike, opt_type, close, volume, oi in options_rows:
                if strike not in self.chain:
                    self.chain[strike] = {
                        "strike": strike,
                        "ce": None,
                        "pe": None,
                        "ce_iv": 0.15,  # fallback baseline IV
                        "pe_iv": 0.15,
                        "ce_oi_base": oi or 1000,
                        "pe_oi_base": oi or 1000,
                        "ce_vol": volume or 10,
                        "pe_vol": volume or 10,
                    }
                
                # Back-calculate baseline IV
                if close and close > 0 and t_years > 0:
                    calculated_iv = calculate_iv(close, self.spot_price, strike, t_years, RISK_FREE, opt_type)
                    if calculated_iv and calculated_iv > 0:
                        if opt_type == "CE":
                            self.chain[strike]["ce_iv"] = calculated_iv
                        else:
                            self.chain[strike]["pe_iv"] = calculated_iv

            # Fill up options rows
            for strike in self.chain:
                self._update_strike_theoreticals(strike, t_years)

            self.last_update = ts_val.isoformat()
            self._compute_pcr_and_pain()
            
            logger.info(f"Seeded live session for {self.underlying} - {self.expiry} at spot {self.spot_price}")
        except Exception as e:
            logger.error(f"Error seeding live session: {e}")
            self._generate_dummy_chain()

    def _generate_dummy_chain(self):
        """Generate a synthetic options chain if no historical database match is found."""
        step = 100 if self.underlying == "NIFTY" else 100
        atm = int(round(self.spot_price / step) * step)
        t_years = 4.0 / 365.0 # 4 days to expiry
        
        for offset in range(-15, 16):
            strike = atm + offset * step
            self.chain[strike] = {
                "strike": strike,
                "ce": None,
                "pe": None,
                "ce_iv": 0.14 + abs(offset) * 0.005,
                "pe_iv": 0.15 + abs(offset) * 0.005,
                "ce_oi_base": 10000 - abs(offset) * 500,
                "pe_oi_base": 10000 - abs(offset) * 500,
                "ce_vol": 500,
                "pe_vol": 500,
            }
            self._update_strike_theoreticals(strike, t_years)
        self._compute_pcr_and_pain()

    def _update_strike_theoreticals(self, strike: int, t_years: float):
        """Re-calculate option close and greeks using BSM based on current spot and cached IV."""
        data = self.chain[strike]
        
        # CE
        ce_price = bs_price(self.spot_price, strike, t_years, RISK_FREE, data["ce_iv"], "CE")
        ce_greeks = calculate_greeks(self.spot_price, strike, t_years, RISK_FREE, data["ce_iv"], "CE")
        data["ce"] = {
            "close": round(ce_price, 2),
            "volume": data["ce_vol"],
            "oi": data["ce_oi_base"],
            "iv": round(data["ce_iv"] * 100, 2),
            "delta": ce_greeks["delta"],
            "theta": ce_greeks["theta"],
            "oi_change": int(data["ce_oi_base"] * 0.05) # dummy 5% change from open
        }

        # PE
        pe_price = bs_price(self.spot_price, strike, t_years, RISK_FREE, data["pe_iv"], "PE")
        pe_greeks = calculate_greeks(self.spot_price, strike, t_years, RISK_FREE, data["pe_iv"], "PE")
        data["pe"] = {
            "close": round(pe_price, 2),
            "volume": data["pe_vol"],
            "oi": data["pe_oi_base"],
            "iv": round(data["pe_iv"] * 100, 2),
            "delta": pe_greeks["delta"],
            "theta": pe_greeks["theta"],
            "oi_change": int(data["pe_oi_base"] * 0.03)
        }

    def _compute_pcr_and_pain(self):
        """Calculate live PCR and Max Pain metrics."""
        total_ce_oi = 0
        total_pe_oi = 0
        min_pain = float("inf")
        best_strike = 0
        
        strikes = sorted(self.chain.keys())
        
        for target in strikes:
            pain = 0
            for strike in strikes:
                ce_oi = self.chain[strike]["ce_oi_base"]
                pe_oi = self.chain[strike]["pe_oi_base"]
                if target > strike:
                    pain += (target - strike) * ce_oi
                elif target < strike:
                    pain += (strike - target) * pe_oi
            
            if pain < min_pain:
                min_pain = pain
                best_strike = target
                
        for data in self.chain.values():
            total_ce_oi += data["ce_oi_base"]
            total_pe_oi += data["pe_oi_base"]

        pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 1.0
        
        self.pcr = pcr
        self.max_pain = best_strike
        self.total_ce_oi = total_ce_oi
        self.total_pe_oi = total_pe_oi

    def tick(self):
        """Simulate real-time price changes, volume increases, OI additions, and Greeks decay."""
        # 1. Random walk spot price (limit drift to 5% of baseline)
        drift_limit = self.base_spot_price * 0.05
        change = random.uniform(-10, 10)
        new_spot = self.spot_price + change
        if abs(new_spot - self.base_spot_price) > drift_limit:
            # Revert drift
            new_spot = self.spot_price - change * 0.5
        self.spot_price = round(new_spot, 2)
        
        # 2. Incrementally decay time to expiry (approximate 2 seconds)
        t_years = 4.0 / 365.0
        
        # 3. Modify IV slightly, increase volume and OI
        for strike, data in self.chain.items():
            # drift IV randomly
            data["ce_iv"] = max(0.05, min(0.60, data["ce_iv"] + random.uniform(-0.002, 0.002)))
            data["pe_iv"] = max(0.05, min(0.60, data["pe_iv"] + random.uniform(-0.002, 0.002)))
            
            # accumulate trading volumes
            data["ce_vol"] += random.randint(10, 100)
            data["pe_vol"] += random.randint(10, 100)
            
            # accumulate Open Interest
            # Call OI grows if spot rises, Put OI grows if spot falls (typical institutional behavior)
            if self.spot_price > strike:
                data["pe_oi_base"] += random.randint(50, 500)
            else:
                data["ce_oi_base"] += random.randint(50, 500)

            self._update_strike_theoreticals(strike, t_years)

        # 4. Recompute PCR & Max Pain
        self._compute_pcr_and_pain()
        
        # 5. Append to PCR trend
        now_str = datetime.now().strftime("%H:%M:%S")
        self.pcr_trend.append({
            "time": now_str,
            "pcr": self.pcr,
            "max_pain": self.max_pain
        })
        if len(self.pcr_trend) > 50:
            self.pcr_trend.pop(0)

        # 6. Randomly generate Block Trade alerts
        if random.random() > 0.8:
            strike_choice = random.choice(list(self.chain.keys()))
            opt_type = random.choice(["CE", "PE"])
            action = random.choice(["BUY", "SELL"])
            qty = random.randint(50, 500) * self.lot_size
            price = self.chain[strike_choice][opt_type.lower()]["close"]
            value = round(qty * price, 2)
            
            if price > 0:
                alert = {
                    "timestamp": now_str,
                    "strike": strike_choice,
                    "option_type": opt_type,
                    "action": action,
                    "qty": qty,
                    "price": price,
                    "value": value
                }
                self.block_trades.insert(0, alert)
                if len(self.block_trades) > 30:
                    self.block_trades.pop()

        self.last_update = datetime.now().isoformat()

    def get_payload(self) -> Dict:
        """Serialize current state into a JSON-compatible dictionary."""
        chain_list = []
        for strike in sorted(self.chain.keys()):
            d = self.chain[strike]
            chain_list.append({
                "strike": strike,
                "ce": d["ce"],
                "pe": d["pe"]
            })
            
        return {
            "underlying": self.underlying,
            "expiry": self.expiry,
            "timestamp": self.last_update,
            "spot_price": self.spot_price,
            "pcr": self.pcr,
            "max_pain": self.max_pain,
            "total_ce_oi": self.total_ce_oi,
            "total_pe_oi": self.total_pe_oi,
            "chain": chain_list,
            "pcr_trend": self.pcr_trend,
            "block_trades": self.block_trades
        }


# Active live session caching
_sessions: Dict[str, LiveSession] = {}

def get_live_session(underlying: str, expiry: str) -> LiveSession:
    key = f"{underlying.upper()}_{expiry}"
    if key not in _sessions:
        _sessions[key] = LiveSession(underlying, expiry)
    return _sessions[key]
