"""
SQLite storage for options chain snapshots, so each fetch builds history
instead of overwriting a CSV.

Schema: one row per (snapshot_time, symbol, expiration, strike, type) —
i.e. every time you snapshot a chain, every contract gets a timestamped row.
This lets you later ask things like "how did volume at this strike change
over the past week" or "when did open interest start building here."

Usage:
    from qt_db import init_db, save_snapshot, get_history, get_latest

    init_db()  # creates options_history.db if it doesn't exist, run once
    save_snapshot(df, symbol="AAPL")  # df from qt_chain.get_full_chain()

    # later, for analysis:
    hist = get_history("AAPL", expiration="2026-06-29", strike=285.0, option_type="call")
    latest = get_latest("AAPL")
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "options_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    type TEXT NOT NULL,
    volume INTEGER,
    openInterest INTEGER,
    bid REAL,
    ask REAL,
    lastTradePrice REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    impliedVolatility REAL
);

CREATE INDEX IF NOT EXISTS idx_symbol_time ON snapshots(symbol, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_symbol_expiry_strike ON snapshots(symbol, expiration, strike, type);
"""


def init_db():
    """Create the database and table if they don't already exist. Safe to
    call every time the script runs — it's a no-op if already set up."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def save_snapshot(df: pd.DataFrame, symbol: str, snapshot_time: str | None = None):
    """Appends every row of df as a new timestamped snapshot. Does NOT
    overwrite or deduplicate — every call adds a fresh batch of rows tagged
    with the current time (or a time you pass in)."""
    if snapshot_time is None:
        snapshot_time = datetime.now(timezone.utc).isoformat()

    df_to_save = df.copy()
    df_to_save["snapshot_time"] = snapshot_time
    df_to_save["symbol"] = symbol  # ensure consistent symbol even if df has it

    cols = [
        "snapshot_time", "symbol", "expiration", "strike", "type",
        "volume", "openInterest", "bid", "ask", "lastTradePrice",
        "delta", "gamma", "theta", "vega", "impliedVolatility",
    ]
    df_to_save = df_to_save[cols]

    conn = sqlite3.connect(DB_PATH)
    df_to_save.to_sql("snapshots", conn, if_exists="append", index=False)
    conn.close()

    print(f"Saved {len(df_to_save)} rows to {DB_PATH.name} at {snapshot_time}")


def get_history(
    symbol: str,
    expiration: str | None = None,
    strike: float | None = None,
    option_type: str | None = None,
) -> pd.DataFrame:
    """Pull historical snapshots for a symbol, optionally filtered down to
    a specific expiration/strike/type to see how that one contract's
    volume/OI has changed over time."""
    conn = sqlite3.connect(DB_PATH)

    query = "SELECT * FROM snapshots WHERE symbol = ?"
    params = [symbol]

    if expiration:
        query += " AND expiration = ?"
        params.append(expiration)
    if strike is not None:
        query += " AND strike = ?"
        params.append(strike)
    if option_type:
        query += " AND type = ?"
        params.append(option_type)

    query += " ORDER BY snapshot_time"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_latest(symbol: str) -> pd.DataFrame:
    """Returns just the most recent snapshot for a symbol (the latest
    snapshot_time's worth of rows) — equivalent to what qt_chain gives you
    fresh, but read from storage instead of hitting the API again."""
    conn = sqlite3.connect(DB_PATH)
    latest_time = pd.read_sql_query(
        "SELECT MAX(snapshot_time) as t FROM snapshots WHERE symbol = ?",
        conn, params=[symbol],
    )["t"].iloc[0]

    if latest_time is None:
        conn.close()
        return pd.DataFrame()

    df = pd.read_sql_query(
        "SELECT * FROM snapshots WHERE symbol = ? AND snapshot_time = ?",
        conn, params=[symbol, latest_time],
    )
    conn.close()
    return df


def list_snapshot_times(symbol: str) -> list[str]:
    """Returns all distinct snapshot timestamps stored for a symbol —
    useful to see how much history you've built up so far."""
    conn = sqlite3.connect(DB_PATH)
    times = pd.read_sql_query(
        "SELECT DISTINCT snapshot_time FROM snapshots WHERE symbol = ? ORDER BY snapshot_time",
        conn, params=[symbol],
    )["snapshot_time"].tolist()
    conn.close()
    return times


if __name__ == "__main__":
    # Quick manual check: shows row counts and snapshot history per symbol
    init_db()
    conn = sqlite3.connect(DB_PATH)
    summary = pd.read_sql_query(
        "SELECT symbol, COUNT(DISTINCT snapshot_time) as num_snapshots, "
        "COUNT(*) as total_rows FROM snapshots GROUP BY symbol",
        conn,
    )
    conn.close()
    print(f"Database: {DB_PATH}")
    if summary.empty:
        print("No snapshots saved yet.")
    else:
        print(summary)
