"""
Options exposure calculations: Gamma Exposure (GEX), Vega Exposure (VEX),
and unusual volume detection.

These are the standard retail-facing formulas used by most options flow
dashboards (Obsidian, SqueezeMetrics-style tools, etc). They're approximations
based on open interest and the greeks Questrade gives us — not a perfect
model of actual dealer positioning (we don't know if dealers are actually
net long or short each contract), but they're the conventional way these
numbers are presented and are useful as a directional/positioning gauge.

Convention used here (the most common one):
  - Call GEX is treated as POSITIVE (dealers assumed net short calls, so
    they must buy stock as price rises -> stabilizing/positive gamma)
  - Put GEX is treated as NEGATIVE (dealers assumed net short puts, so
    they must sell stock as price falls -> destabilizing/negative gamma)
  - This is a simplification. Real dealer positioning can differ, but this
    is the standard way GEX is shown on every retail platform.

GEX formula per contract:
    GEX = gamma * open_interest * 100 (contract multiplier) * spot_price^2 * 0.01
    (the 0.01 converts to "dollars of exposure per 1% move in the underlying")

VEX formula per contract:
    VEX = vega * open_interest * 100
    (dollars of exposure per 1 point move in implied volatility)
    Vega exposure isn't typically sign-flipped between calls/puts the way
    gamma is, since vega is symmetric — both calls and puts gain value as
    IV rises. We report it as total exposure dealers are short, which is
    why we negate it (selling options = dealers are short vega).
"""

from __future__ import annotations

import pandas as pd


def compute_gex(df: pd.DataFrame, spot_price: float) -> pd.DataFrame:
    """Given a chain DataFrame (with strike, type, gamma, openInterest
    columns) and the current spot price, returns a DataFrame with one row
    per strike showing call GEX, put GEX, and net GEX in dollars.
    """
    work = df.copy()
    work["gamma"] = work["gamma"].fillna(0)
    work["openInterest"] = work["openInterest"].fillna(0)

    work["gex_raw"] = (
        work["gamma"] * work["openInterest"] * 100 * (spot_price ** 2) * 0.01
    )
    # Calls are positive exposure, puts are negative (standard convention)
    work["gex_signed"] = work.apply(
        lambda r: r["gex_raw"] if r["type"] == "call" else -r["gex_raw"], axis=1
    )

    pivot = work.pivot_table(
        index="strike", columns="type", values="gex_signed", aggfunc="sum"
    ).fillna(0)

    if "call" not in pivot.columns:
        pivot["call"] = 0.0
    if "put" not in pivot.columns:
        pivot["put"] = 0.0

    pivot["net_gex"] = pivot["call"] + pivot["put"]
    pivot = pivot.rename(columns={"call": "call_gex", "put": "put_gex"})
    return pivot.sort_index()


def compute_vex(df: pd.DataFrame) -> pd.DataFrame:
    """Given a chain DataFrame (with strike, type, vega, openInterest
    columns), returns a DataFrame with one row per strike showing call VEX,
    put VEX, and net VEX. Dealers assumed net short options overall, so we
    negate to represent dealer vega exposure (positive = dealers gain as
    IV falls, i.e. they're short vega here)."""
    work = df.copy()
    work["vega"] = work["vega"].fillna(0)
    work["openInterest"] = work["openInterest"].fillna(0)

    work["vex_raw"] = -(work["vega"] * work["openInterest"] * 100)

    pivot = work.pivot_table(
        index="strike", columns="type", values="vex_raw", aggfunc="sum"
    ).fillna(0)

    if "call" not in pivot.columns:
        pivot["call"] = 0.0
    if "put" not in pivot.columns:
        pivot["put"] = 0.0

    pivot["net_vex"] = pivot["call"] + pivot["put"]
    pivot = pivot.rename(columns={"call": "call_vex", "put": "put_vex"})
    return pivot.sort_index()


def detect_unusual_volume(df: pd.DataFrame, min_volume: int = 100) -> pd.DataFrame:
    """Flags contracts with unusually high volume relative to their open
    interest — the classic signature of a fresh, same-day position being
    opened rather than ongoing/stale activity. Returns contracts sorted by
    how unusual they are (highest volume/OI ratio first).

    min_volume: ignore very low-volume contracts entirely (avoids flagging
    a contract with 5 volume / 1 OI as "500% unusual" when it's just noise).
    """
    work = df.copy()
    work["volume"] = work["volume"].fillna(0)
    work["openInterest"] = work["openInterest"].fillna(0)

    work = work[work["volume"] >= min_volume].copy()
    if work.empty:
        return work

    # Avoid divide-by-zero: treat 0 OI as 1 for ratio purposes (means the
    # ratio is just "volume", which is still meaningfully high)
    work["oi_safe"] = work["openInterest"].replace(0, 1)
    work["volume_oi_ratio"] = work["volume"] / work["oi_safe"]

    flagged = work[work["volume_oi_ratio"] >= 2.0].copy()
    flagged = flagged.sort_values("volume_oi_ratio", ascending=False)

    return flagged[
        ["expiration", "strike", "type", "volume", "openInterest", "volume_oi_ratio"]
    ]
