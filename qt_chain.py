"""
Fetch options chain data (strikes, expirations, volume, open interest, greeks)
for a given underlying symbol from Questrade.

Questrade's flow for options data is two steps:
  1. Look up the symbol -> get its numeric symbolId
  2. Get the option chain skeleton (expirations -> strikes -> contract IDs)
  3. Get live quotes/greeks for the option contract IDs you care about
     (volume + OI live here, not in the chain skeleton)

Usage:
    from qt_chain import get_full_chain
    df = get_full_chain("AAPL")
    df.to_csv("aapl_chain_snapshot.csv", index=False)
"""

from __future__ import annotations

import pandas as pd

from qt_auth import QuestradeAuth

MAX_IDS_PER_QUOTE_CALL = 100  # Questrade caps batch size on the quotes endpoint


def get_symbol_id(session, api_server: str, symbol: str) -> int:
    resp = session.get(f"{api_server}/v1/symbols", params={"names": symbol})
    resp.raise_for_status()
    symbols = resp.json()["symbols"]
    if not symbols:
        raise ValueError(f"No Questrade symbol found for '{symbol}'")
    return symbols[0]["symbolId"]


def get_option_chain_skeleton(session, api_server: str, symbol_id: int) -> dict:
    """Returns the raw chain structure: list of expiration dates, each with
    strikes, each strike having callSymbolId / putSymbolId."""
    resp = session.get(f"{api_server}/v1/symbols/{symbol_id}/options")
    resp.raise_for_status()
    return resp.json()


def get_option_quotes(session, api_server: str, option_ids: list[int]) -> list[dict]:
    """Fetch live quotes (volume, OI, greeks, bid/ask) for a batch of option
    contract IDs. Batches automatically since Questrade limits request size."""
    all_quotes = []
    for i in range(0, len(option_ids), MAX_IDS_PER_QUOTE_CALL):
        batch = option_ids[i : i + MAX_IDS_PER_QUOTE_CALL]
        resp = session.post(
            f"{api_server}/v1/markets/quotes/options",
            json={"optionIds": batch},
        )
        if resp.status_code != 200:
            print(f"\n--- Questrade error response ({resp.status_code}) ---")
            print(resp.text)
            print(f"--- Batch size: {len(batch)}, first few IDs: {batch[:5]} ---\n")
        resp.raise_for_status()
        all_quotes.extend(resp.json()["optionQuotes"])
    return all_quotes


def get_underlying_quote(session, api_server: str, symbol_id: int) -> dict:
    """Fetch the current Level 1 quote for the underlying stock itself
    (not an option) — used to show spot price alongside the chain."""
    resp = session.get(f"{api_server}/v1/markets/quotes/{symbol_id}")
    resp.raise_for_status()
    quotes = resp.json().get("quotes", [])
    return quotes[0] if quotes else {}


def get_spot_price(symbol: str) -> float | None:
    """Standalone helper: looks up a symbol and returns its last trade price.
    Used by the dashboard to display current spot price next to the chain."""
    auth = QuestradeAuth()
    session = auth.get_session()
    api_server = auth.api_server
    symbol_id = get_symbol_id(session, api_server, symbol)
    quote = get_underlying_quote(session, api_server, symbol_id)
    return quote.get("lastTradePrice")


def get_candles(symbol: str, days: int = 90, interval: str = "OneDay") -> pd.DataFrame:
    """Fetch historical OHLC candles for the underlying stock (not options).
    Used to draw a price chart with key strikes overlaid.

    days: how far back to pull (calendar days, not trading days)
    interval: Questrade interval enum, e.g. 'OneDay', 'OneHour', 'FifteenMinutes'
    """
    import datetime

    auth = QuestradeAuth()
    session = auth.get_session()
    api_server = auth.api_server

    symbol_id = get_symbol_id(session, api_server, symbol)

    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=days)

    resp = session.get(
        f"{api_server}/v1/markets/candles/{symbol_id}",
        params={
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
            "interval": interval,
        },
    )
    resp.raise_for_status()
    candles = resp.json().get("candles", [])

    df = pd.DataFrame(candles)
    if df.empty:
        return df

    df["start"] = pd.to_datetime(df["start"])
    df = df.rename(columns={
        "start": "date", "open": "open", "high": "high",
        "low": "low", "close": "close", "volume": "volume",
    })
    return df[["date", "open", "high", "low", "close", "volume"]]


def get_full_chain(
    symbol: str,
    expiration_dates: list[str] | None = None,
    num_expirations: int = 4,
) -> pd.DataFrame:
    """
    Returns a flat DataFrame with one row per contract:
    symbol, expiration, strike, type (call/put), volume, openInterest,
    bid, ask, lastTradePrice, delta, gamma, theta, vega, impliedVolatility

    expiration_dates: optional list of 'YYYY-MM-DD' strings to limit which
    expirations to pull. If given, num_expirations is ignored.

    num_expirations: if expiration_dates isn't given, pulls this many of the
    NEAREST upcoming expirations (default 4, i.e. roughly the next month of
    weeklies). Set higher for a longer-dated view, but note this multiplies
    the number of quote requests made.
    """
    auth = QuestradeAuth()
    session = auth.get_session()
    api_server = auth.api_server

    symbol_id = get_symbol_id(session, api_server, symbol)
    chain = get_option_chain_skeleton(session, api_server, symbol_id)

    # Build a lookup of optionId -> (expiration, strike, type)
    contract_meta = {}
    option_ids = []

    expiry_blocks = chain["optionChain"]
    if not expiration_dates:
        sorted_blocks = sorted(expiry_blocks, key=lambda b: b["expiryDate"])
        expiry_blocks = sorted_blocks[:num_expirations]
        dates_preview = [b["expiryDate"][:10] for b in expiry_blocks]
        print(f"No expiration filter given — pulling nearest {len(expiry_blocks)} "
              f"expirations: {dates_preview}")

    for expiry_block in expiry_blocks:
        expiry_date = expiry_block["expiryDate"][:10]  # trim to YYYY-MM-DD
        if expiration_dates and expiry_date not in expiration_dates:
            continue
        for strike_row in expiry_block["chainPerRoot"][0]["chainPerStrikePrice"]:
            strike = strike_row["strikePrice"]
            for opt_type, id_key in (("call", "callSymbolId"), ("put", "putSymbolId")):
                opt_id = strike_row.get(id_key)
                if opt_id:
                    contract_meta[opt_id] = {
                        "symbol": symbol,
                        "expiration": expiry_date,
                        "strike": strike,
                        "type": opt_type,
                    }
                    option_ids.append(opt_id)

    if not option_ids:
        raise ValueError(
            f"No contracts found for {symbol} with the given expiration filter."
        )

    quotes = get_option_quotes(session, api_server, option_ids)

    rows = []
    for q in quotes:
        meta = contract_meta.get(q["symbolId"])
        if not meta:
            continue
        rows.append(
            {
                **meta,
                "volume": q.get("volume"),
                "openInterest": q.get("openInterest"),
                "bid": q.get("bidPrice"),
                "ask": q.get("askPrice"),
                "lastTradePrice": q.get("lastTradePrice"),
                "delta": q.get("delta"),
                "gamma": q.get("gamma"),
                "theta": q.get("theta"),
                "vega": q.get("vega"),
                "impliedVolatility": q.get("volatility"),
            }
        )

    return pd.DataFrame(rows)


def max_volume_per_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """Given a chain DataFrame, returns one row per (expiration, type) showing
    the strike with the highest volume — i.e. answers 'which strike on which
    date has the most volume', split out by calls vs puts."""
    idx = df.groupby(["expiration", "type"])["volume"].idxmax()
    return (
        df.loc[idx, ["expiration", "type", "strike", "volume", "openInterest"]]
        .sort_values(["expiration", "type"])
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    import sys

    from qt_db import init_db, save_snapshot

    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    n_exp = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    print(f"Fetching chain for {sym} (next {n_exp} expirations)...")
    df = get_full_chain(sym, num_expirations=n_exp)

    print("\n=== Top 15 contracts by volume (all expirations) ===")
    print(df.sort_values("volume", ascending=False).head(15)[
        ["expiration", "strike", "type", "volume", "openInterest"]
    ])

    print("\n=== Max-volume strike per expiration (call/put) ===")
    print(max_volume_per_expiry(df))

    out_path = f"{sym}_chain_snapshot.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}")

    init_db()
    save_snapshot(df, symbol=sym)
