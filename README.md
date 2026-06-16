# Options Backtest Platform (AlgoTest-style)

1-minute options backtesting for NIFTY / BANKNIFTY / F&O stocks.
Data: **Alice Blue (pya3)** live + recent history, **Kaggle** free historical
backfill, **NSE bhavcopy** EOD validation. Stored as Parquet, queried with DuckDB.

## Status
- App "Trading" on Alice Blue: **Approval Pending** -> fill `.env` once approved.
- Kaggle backfill works **today** (no broker API needed).

## Layout
```
config/settings.py        env-driven config
src/data/
  schema.py               canonical Parquet schemas (options + spot)
  storage.py              Parquet lake write + DuckDB read
  aliceblue_client.py     pya3 wrapper (auth, contracts, 1-min history)
  kaggle_loader.py        free historical backfill
  recorder.py             live WS ticks -> 1-min candles -> lake
src/backtest/
  strategy.py             legs, strike selection, contract specs
  engine.py               minute-by-minute multi-leg simulation
  costs.py                NSE F&O cost model (STT/GST/brokerage/slippage)
  metrics.py              win%, expectancy, drawdown, Sharpe
src/cli.py                typer CLI
```

## Setup
```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env                            # fill keys
```

## Use now (free data)
```bash
python -m src.cli kaggle-spot debashis74017/nifty-50-minute-data --underlying NIFTY
python -m src.cli info
```

## Backtest (after lake has spot + options)
```bash
python -m src.cli backtest --underlying NIFTY --start 2024-01-01 --end 2024-03-31 --expiry 2024-01-25
```

## Data lake
Hive-partitioned Parquet under `data/lake/`:
```
options/underlying=NIFTY/expiry=2026-06-26/part-*.parquet
spot/underlying=NIFTY/part-*.parquet
```

## TODO (pending API approval)
- pya3 WS wiring in `recorder.py` (aggregation logic already done)
- options 1-min backfill via pya3 `get_historical` for recent expiries
- PREMIUM/DELTA strike selection (needs chain + greeks via py_vollib)
- FastAPI + React strategy-builder UI (later phase)
