"""
Trident — SPY, QQQ and IWM strike matrices side by side on the nearest
expiration, each with its own spot line, GEX / VEX toggle and snap-to-spot,
so you can read index positioning at a single glance.

This is a page of the multipage app: run

    streamlit run dashboard.py

and pick "Trident" in the sidebar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make sure the project root (where qt_chain.py etc. live) is importable
# even though this file sits in pages/.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="Trident", page_icon="🔱", layout="wide")

SYMBOLS = ["SPY", "QQQ", "IWM"]


def check_password() -> bool:
    """Same simple gate as the main dashboard — skipped entirely when no
    DASHBOARD_PASSWORD secret is configured (i.e. running locally)."""
    try:
        required_password = st.secrets.get("DASHBOARD_PASSWORD")
    except Exception:
        required_password = None

    if not required_password:
        return True

    if st.session_state.get("password_correct", False):
        return True

    pw = st.text_input("Password", type="password")
    if pw:
        if pw == required_password:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


if not check_password():
    st.stop()


# --- Data fetchers (cached, shared across viewers) -------------------------
# Trident is a live glance page: it caches pulls but deliberately does NOT
# write snapshots to the history DB, so it never pollutes the snapshot list
# on the main dashboard.

@st.cache_data(ttl=90)
def fetch_nearest_chain(sym: str) -> pd.DataFrame:
    from qt_chain import get_full_chain
    return get_full_chain(sym, num_expirations=1)


@st.cache_data(ttl=90)
def fetch_spot(sym: str):
    from qt_chain import get_spot_price
    return get_spot_price(sym)


# --- Formatting helpers (matches the Exposure tab styling) ------------------

def format_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{sign}${v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{sign}${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{sign}${v/1_000:.1f}K"
    return f"{sign}${v:.0f}"


def signed_value_to_color(val: float, max_abs: float) -> str:
    """Negative -> red gradient. Positive -> dark purple -> gold gradient.
    Same Obsidian-style scheme as the main dashboard's exposure heatmap."""
    if max_abs == 0:
        norm = 0.0
    else:
        norm = abs(val) / max_abs
    norm = max(0.0, min(1.0, norm)) ** 0.6  # spread out lower values

    if val < 0:
        dark = (40, 14, 14)
        bright = (220, 38, 38)
        r = int(dark[0] + (bright[0] - dark[0]) * norm)
        g = int(dark[1] + (bright[1] - dark[1]) * norm)
        b = int(dark[2] + (bright[2] - dark[2]) * norm)
    else:
        dark = (24, 16, 36)
        mid = (91, 58, 160)
        gold = (245, 180, 66)
        if norm < 0.5:
            t = norm / 0.5
            c1, c2 = dark, mid
        else:
            t = (norm - 0.5) / 0.5
            c1, c2 = mid, gold
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
    return f"rgb({r},{g},{b})"


# --- Header -----------------------------------------------------------------

st.markdown(
    """
    <div style="display:flex; align-items:center; gap:14px; margin-bottom:2px;">
      <div style="font-size:34px; font-weight:800;">🔱 Trident™</div>
      <div style="background:#2a1f4d; color:#b9a0f5; border:1px solid #5b3aa0;
                  border-radius:999px; padding:3px 14px; font-family:monospace;
                  font-size:12px; letter-spacing:2px;">CIPHER&nbsp;X</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    "SPY, QQQ and IWM strike matrices side by side on the nearest expiration, "
    "each with its own spot line, GEX / VEX toggle and snap-to-spot, so you "
    "can read index positioning at a single glance."
)

ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 1])
with ctrl1:
    n_per_side = st.slider(
        "Strikes each side of spot (snap-to-spot window)",
        min_value=5, max_value=30, value=12,
        help="How many strikes above and below spot to show when "
             "snap-to-spot is on for a matrix.",
    )
with ctrl2:
    weight_choice = st.radio(
        "Weight by", ["Open Interest", "Today's Volume"], horizontal=True,
        help="Open interest = held positioning. Volume = today's live flow.",
    )
with ctrl3:
    st.write("")  # spacer to align button with the other controls
    if st.button("↻ Refresh all", use_container_width=True):
        fetch_nearest_chain.clear()
        fetch_spot.clear()
        st.rerun()

weight_by = "openInterest" if weight_choice == "Open Interest" else "volume"

# Shared styles for the three matrices
st.markdown(
    """
    <style>
    .tri-wrap {
        background:#0d0d0d;
        border:1px solid #262032;
        border-radius:10px;
        padding:10px;
        max-height:640px;
        overflow-y:auto;
    }
    .tri-table {
        border-collapse:separate;
        border-spacing:0 3px;
        width:100%;
        font-family:monospace;
    }
    .tri-strike {
        color:#999;
        font-size:12px;
        text-align:right;
        padding-right:10px;
        white-space:nowrap;
        width:52px;
    }
    .tri-cell { padding:0; }
    .tri-pill {
        border-radius:4px;
        padding:7px 12px;
        color:white;
        font-weight:700;
        font-size:12px;
        text-align:right;
        white-space:nowrap;
    }
    .tri-highlight { border:2px solid white; }
    .tri-spot-row td { padding:3px 0; }
    .tri-spot-label {
        color:#1a1a1a;
        background:#fff;
        font-size:10px;
        font-weight:700;
        text-align:right;
        padding:2px 6px;
        border-radius:4px;
        white-space:nowrap;
    }
    .tri-spot-line { border-top:2px dashed #f0d060; }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_matrix(sym: str) -> None:
    mode = st.radio(
        "Exposure", ["GEX", "VEX"], horizontal=True,
        key=f"tri_mode_{sym}", label_visibility="collapsed",
    )
    snap = st.toggle("🎯 Snap to spot", value=True, key=f"tri_snap_{sym}")

    try:
        df = fetch_nearest_chain(sym)
        spot = fetch_spot(sym)
    except Exception as e:
        st.error(f"Couldn't fetch {sym}: {e}")
        return

    if df.empty:
        st.info(f"No chain data for {sym}.")
        return

    expiration = df["expiration"].min()

    from qt_exposure import compute_gex, compute_vex

    if mode == "GEX":
        if not spot:
            st.warning(f"{sym}: spot price unavailable — GEX needs it.")
            return
        exp_df = compute_gex(df, spot, weight_by=weight_by)
        value_col = "net_gex"
    else:
        exp_df = compute_vex(df, weight_by=weight_by)
        value_col = "net_vex"

    if exp_df.empty:
        st.info(f"No exposure data for {sym}.")
        return

    spot_str = f"${spot:,.2f}" if spot else "n/a"
    st.markdown(
        f"<div style='display:flex; justify-content:space-between; "
        f"align-items:baseline; padding:2px 2px 6px;'>"
        f"<span style='font-size:20px; font-weight:800;'>{sym}</span>"
        f"<span style='color:#f0d060; font-family:monospace; "
        f"font-size:15px;'>{spot_str}</span>"
        f"<span style='color:#888; font-size:12px;'>exp {expiration}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    strikes_asc = sorted(exp_df.index)
    if snap and spot:
        below = [s for s in strikes_asc if s <= spot][-n_per_side:]
        above = [s for s in strikes_asc if s > spot][:n_per_side]
        exp_df = exp_df.loc[below + above]

    strikes_desc = sorted(exp_df.index, reverse=True)
    max_abs = exp_df[value_col].abs().max()
    max_abs = max_abs if max_abs and max_abs > 0 else 1
    most_extreme = exp_df[value_col].abs().idxmax()

    rows_html = []
    spot_marker_inserted = spot is None
    for strike in strikes_desc:
        if not spot_marker_inserted and strike < spot:
            spot_marker_inserted = True
            rows_html.append(
                f'<tr class="tri-spot-row">'
                f'<td class="tri-spot-label">SPOT {spot:,.2f}</td>'
                f'<td class="tri-spot-line"></td></tr>'
            )
        val = exp_df.loc[strike, value_col]
        color = signed_value_to_color(val, max_abs)
        hl = " tri-highlight" if strike == most_extreme else ""
        rows_html.append(
            f'<tr><td class="tri-strike">{strike:g}</td>'
            f'<td class="tri-cell"><div class="tri-pill{hl}" '
            f'style="background:{color}">{format_money(val)}</div></td></tr>'
        )

    st.markdown(
        f'<div class="tri-wrap"><table class="tri-table">'
        f'{"".join(rows_html)}</table></div>',
        unsafe_allow_html=True,
    )

    net_total = exp_df[value_col].sum()
    st.metric(
        f"Total net {mode}",
        format_money(net_total),
        help="net positive" if net_total >= 0 else "net negative",
    )


col_spy, col_qqq, col_iwm = st.columns(3)
for sym, col in zip(SYMBOLS, (col_spy, col_qqq, col_iwm)):
    with col:
        render_matrix(sym)

st.caption(
    "Purple → gold = increasingly positive net exposure (price magnet / "
    "stabilizing). Red = negative net exposure (volatile zone). White box "
    "marks the most extreme strike. Data cached ~90s; nothing on this page "
    "is written to the snapshot history."
)
