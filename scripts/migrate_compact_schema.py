#!/usr/bin/env python3
"""
One-time migration: downcasts DOUBLE→FLOAT, BIGINT→INTEGER in existing DuckDB.
Run on VPS ONCE after pulling this commit. Safe to re-run (checks types first).

Usage:
    cd /opt/trading
    .venv/bin/python scripts/migrate_compact_schema.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from config import settings

def _col_types(con, table: str) -> dict[str, str]:
    rows = con.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table}'").fetchall()
    return {r[0]: r[1].upper() for r in rows}


def migrate(db_path: str) -> None:
    con = duckdb.connect(db_path)
    print(f"DB: {db_path}")

    for table, cols in [
        ("options_1m", ["open", "high", "low", "close", "volume", "oi"]),
        ("spot_1m",    ["open", "high", "low", "close", "volume"]),
    ]:
        try:
            cur_types = _col_types(con, table)
        except Exception as e:
            print(f"  {table}: skip ({e})")
            continue

        needs = []
        for col in cols:
            ct = cur_types.get(col, "")
            want = "FLOAT" if col not in ("volume", "oi") else "INTEGER"
            if want not in ct:
                needs.append((col, want))

        if not needs:
            print(f"  {table}: already compact, nothing to do")
            continue

        print(f"  {table}: migrating {[c for c, _ in needs]} ...")
        rows_before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

        # Export → drop → recreate → reimport
        tmp = f"/tmp/{table}_migration.parquet"
        con.execute(f"COPY {table} TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"DROP TABLE {table}")

        # Recreate with compact types
        if table == "options_1m":
            con.execute("""
                CREATE TABLE options_1m (
                    underlying   VARCHAR   NOT NULL,
                    expiry       DATE      NOT NULL,
                    strike       INTEGER   NOT NULL,
                    option_type  VARCHAR   NOT NULL,
                    ts           TIMESTAMP NOT NULL,
                    open         FLOAT,
                    high         FLOAT,
                    low          FLOAT,
                    close        FLOAT,
                    volume       INTEGER,
                    oi           INTEGER
                )
            """)
        else:
            con.execute("""
                CREATE TABLE spot_1m (
                    underlying VARCHAR   NOT NULL,
                    ts         TIMESTAMP NOT NULL,
                    open       FLOAT,
                    high       FLOAT,
                    low        FLOAT,
                    close      FLOAT,
                    volume     INTEGER
                )
            """)

        con.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{tmp}')")
        rows_after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

        if rows_before != rows_after:
            print(f"  ERROR: row count mismatch {rows_before} → {rows_after}. Restore from {tmp}")
            sys.exit(1)

        Path(tmp).unlink(missing_ok=True)
        print(f"  {table}: done ({rows_after:,} rows)")

    # Rebuild indexes after table recreate
    print("Rebuilding indexes...")
    con.execute("CREATE INDEX IF NOT EXISTS idx_opt_main ON options_1m(underlying, expiry, strike, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_spot_main ON spot_1m(underlying, ts)")

    print("VACUUM...")
    con.execute("VACUUM")
    con.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate(str(settings.db_path))
