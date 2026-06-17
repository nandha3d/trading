"""Persistent DuckDB database — single file, typed, integrity-enforced.

DB file: data/market.duckdb (settings.db_path).

Two tables, both with NOT NULL on every key field so a row missing
date/time/strike/expiry/type is REJECTED at insert, never stored wrong:

  options_1m(underlying, expiry, strike, option_type, ts, ohlc, volume, oi)
  spot_1m(underlying, ts, ohlc, volume)

Writers validate first: drop rows with null keys or bad option_type, count
them as rejected, insert only clean rows. clear_* enables idempotent reload
(no duplicates). verify() reports row counts, ts coverage, null/dup checks.
"""
from __future__ import annotations

import threading
from datetime import date, datetime

import duckdb
import polars as pl

from config import settings
from .schema import OPTIONS_COLS, SPOT_COLS

_OPT_KEYS = ["underlying", "expiry", "strike", "option_type", "ts"]
_SPOT_KEYS = ["underlying", "ts"]

_DB: duckdb.DuckDBPyConnection | None = None
_LOCK = threading.Lock()


def db() -> duckdb.DuckDBPyConnection:
    """Cached persistent connection with thread-safety lock."""
    global _DB
    with _LOCK:
        if _DB is None:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            _DB = duckdb.connect(str(settings.db_path))
            init_db(_DB)
        return _DB


def init_db(con: duckdb.DuckDBPyConnection | None = None) -> None:
    con = con or db()
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS options_1m (
            underlying   VARCHAR    NOT NULL,
            expiry       DATE       NOT NULL,
            strike       INTEGER    NOT NULL,
            option_type  VARCHAR    NOT NULL,
            ts           TIMESTAMP  NOT NULL,
            open         FLOAT,
            high         FLOAT,
            low          FLOAT,
            close        FLOAT,
            volume       INTEGER,
            oi           INTEGER
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS spot_1m (
            underlying VARCHAR   NOT NULL,
            ts         TIMESTAMP NOT NULL,
            open       FLOAT,
            high       FLOAT,
            low        FLOAT,
            close      FLOAT,
            volume     INTEGER
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_strategies (
            id           VARCHAR    NOT NULL,
            name         VARCHAR    NOT NULL,
            underlying   VARCHAR    NOT NULL,
            expiry       DATE       NOT NULL,
            created_at   TIMESTAMP  NOT NULL,
            legs         VARCHAR    NOT NULL
        );
        """
    )


_INDEXED = False


def ensure_indexes() -> None:
    """Build covering ART indexes once (IF NOT EXISTS). Speeds the per-day
    WHERE underlying/expiry/strike/ts lookups the backtest engine issues.
    First build on a large table costs time once; later calls are no-ops."""
    global _INDEXED
    if _INDEXED:
        return
    con = db()
    con.execute("CREATE INDEX IF NOT EXISTS idx_opt_main ON options_1m(underlying, expiry, strike, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_spot_main ON spot_1m(underlying, ts)")
    _INDEXED = True


def _insert(table: str, df: pl.DataFrame, cols: list[str]) -> int:
    con = db()
    con.register("src", df.select(cols).to_arrow())
    collist = ", ".join(cols)
    con.execute(f"INSERT INTO {table} ({collist}) SELECT {collist} FROM src")
    con.unregister("src")
    return df.height


def write_options(df: pl.DataFrame) -> int:
    """Validate + insert option candles. Returns rows written (after rejecting
    rows with null keys or option_type not in CE/PE)."""
    if df.is_empty():
        return 0
    df = df.select(OPTIONS_COLS)
    clean = df.drop_nulls(subset=_OPT_KEYS).filter(pl.col("option_type").is_in(["CE", "PE"]))
    rejected = df.height - clean.height
    if rejected:
        _log_reject("options_1m", rejected)
    if clean.is_empty():
        return 0
    return _insert("options_1m", clean, OPTIONS_COLS)


def write_spot(df: pl.DataFrame) -> int:
    if df.is_empty():
        return 0
    df = df.select(SPOT_COLS)
    clean = df.drop_nulls(subset=_SPOT_KEYS)
    rejected = df.height - clean.height
    if rejected:
        _log_reject("spot_1m", rejected)
    if clean.is_empty():
        return 0
    return _insert("spot_1m", clean, SPOT_COLS)


def _log_reject(table: str, n: int) -> None:
    print(f"  [reject] {table}: dropped {n:,} rows with null key / bad type")


def clear_options(underlying: str) -> int:
    con = db()
    n = con.execute("SELECT count(*) FROM options_1m WHERE underlying=?", [underlying]).fetchone()[0]
    con.execute("DELETE FROM options_1m WHERE underlying=?", [underlying])
    return n


def dedupe_options(underlying: str | None = None) -> int:
    """Remove duplicate (underlying,expiry,strike,option_type,ts) rows, keeping
    the highest-volume/oi row per key. Returns rows deleted. Constraints survive
    (in-place DELETE, not table recreate)."""
    con = db()
    where = "WHERE underlying = ?" if underlying else ""
    params = [underlying] if underlying else []
    sql = f"""
        DELETE FROM options_1m WHERE rowid IN (
            SELECT rowid FROM (
                SELECT rowid, row_number() OVER (
                    PARTITION BY underlying, expiry, strike, option_type, ts
                    ORDER BY volume DESC, oi DESC
                ) rn
                FROM options_1m {where}
            ) WHERE rn > 1
        )
    """
    before = con.execute("SELECT count(*) FROM options_1m").fetchone()[0]
    con.execute(sql, params)
    after = con.execute("SELECT count(*) FROM options_1m").fetchone()[0]
    return before - after


def clear_spot(underlying: str) -> int:
    con = db()
    n = con.execute("SELECT count(*) FROM spot_1m WHERE underlying=?", [underlying]).fetchone()[0]
    con.execute("DELETE FROM spot_1m WHERE underlying=?", [underlying])
    return n


# ---- reads (same signatures the engine already uses) ----

def read_options(
    underlying: str,
    start: datetime,
    end: datetime,
    expiry: date | None = None,
    strikes: list[int] | None = None,
    option_type: str | None = None,
) -> pl.DataFrame:
    where = ["underlying = ?", "ts >= ?", "ts <= ?"]
    params: list = [underlying, start, end]
    if expiry:
        where.append("expiry = ?")
        params.append(expiry)
    if strikes:
        where.append(f"strike IN ({','.join('?' for _ in strikes)})")
        params += strikes
    if option_type:
        where.append("option_type = ?")
        params.append(option_type)
    sql = f"SELECT * FROM options_1m WHERE {' AND '.join(where)} ORDER BY ts"
    cur = db().cursor()
    try:
        return cur.execute(sql, params).pl()
    finally:
        cur.close()


def read_spot(underlying: str, start: datetime, end: datetime) -> pl.DataFrame:
    sql = "SELECT * FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts"
    cur = db().cursor()
    try:
        return cur.execute(sql, [underlying, start, end]).pl()
    finally:
        cur.close()


def list_expiries(underlying: str) -> list[date]:
    sql = "SELECT DISTINCT expiry FROM options_1m WHERE underlying=? ORDER BY expiry"
    cur = db().cursor()
    try:
        rows = cur.execute(sql, [underlying]).fetchall()
        return [r[0] for r in rows]
    finally:
        cur.close()


def verify(fast: bool = False) -> dict:
    """Integrity + coverage report."""
    cur = db().cursor()
    try:
        out: dict = {}
        for tbl, keys in (("options_1m", _OPT_KEYS), ("spot_1m", _SPOT_KEYS)):
            n = cur.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            rng = cur.execute(f"SELECT min(ts), max(ts) FROM {tbl}").fetchone()
            
            if fast:
                nulls = 0
                dups = 0
            else:
                nulls = cur.execute(
                    f"SELECT count(*) FROM {tbl} WHERE "
                    + " OR ".join(f"{k} IS NULL" for k in keys)
                ).fetchone()[0]
                dups = cur.execute(
                    f"SELECT count(*) FROM (SELECT {', '.join(keys)}, count(*) c "
                    f"FROM {tbl} GROUP BY {', '.join(keys)} HAVING c > 1)"
                ).fetchone()[0]
                
            per_und = cur.execute(
                f"SELECT underlying, count(*) FROM {tbl} GROUP BY underlying ORDER BY underlying"
            ).fetchall()
            out[tbl] = {
                "rows": n, "ts_min": rng[0], "ts_max": rng[1],
                "null_keys": nulls, "dup_keys": dups,
                "by_underlying": dict(per_und),
            }
        return out
    finally:
        cur.close()
