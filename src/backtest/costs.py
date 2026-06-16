"""Transaction cost model for NSE F&O (options).

Defaults reflect typical Indian discount-broker + statutory charges (2024-25).
Verify rates against current SEBI/exchange/broker schedule before trusting PnL.
All charges computed per leg per round trip (entry + exit).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostModel:
    brokerage_per_order: float = 20.0     # flat per executed order (Alice Blue-style)
    stt_sell_pct: float = 0.001           # STT on SELL side premium (options)
    exch_txn_pct: float = 0.00035         # NSE options txn charge on premium
    sebi_pct: float = 0.000001            # SEBI turnover fee
    stamp_buy_pct: float = 0.00003        # stamp duty on BUY side
    gst_pct: float = 0.18                 # GST on (brokerage + txn charges)
    slippage_pct: float = 0.0             # optional % slippage on fill price

    def leg_cost(self, entry_premium: float, exit_premium: float, qty: int) -> float:
        """Total round-trip cost for one leg. qty = lots * lot_size."""
        buy_val = entry_premium * qty
        sell_val = exit_premium * qty
        brokerage = self.brokerage_per_order * 2
        stt = sell_val * self.stt_sell_pct
        txn = (buy_val + sell_val) * self.exch_txn_pct
        sebi = (buy_val + sell_val) * self.sebi_pct
        stamp = buy_val * self.stamp_buy_pct
        gst = (brokerage + txn) * self.gst_pct
        return brokerage + stt + txn + sebi + stamp + gst

    def apply_slippage(self, price: float, is_buy: bool) -> float:
        if not self.slippage_pct:
            return price
        adj = price * self.slippage_pct
        return price + adj if is_buy else price - adj
