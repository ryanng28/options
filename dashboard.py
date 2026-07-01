"""
Options chain dashboard — reads from the local SQLite history built up by
qt_chain.py / watchlist_snapshot.py and shows:
  - A strike x expiration volume heatmap (calls and puts)
  - A max-volume-per-expiration summary table
  side by side, for whichever symbol + snapshot you pick.

Run with:
    streamlit run dashboard.py

Opens automatically in your browser, usually at http://localhost:8501
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from qt_chain import max_volume_per_expiry

DB_PATH = Path(__file__).parent / "options_history.db"

st.set_page_config(page_title="Options Chain Tracker", layout="wide")


def check_password() -> bool:
    """Simple password gate for when this is deployed publicly. If no
    DASHBOARD_PASSWORD secret is configured (e.g. running locally), this
    is skipped entirely and the app behaves as before."""
    try:
        required_password = st.secrets.get("DASHBOARD_PASSWORD")
    except Exception:
        required_password = None

    if not required_password:
        return True  # no password configured (local use) — allow through

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


@st.cache_data(ttl=60)
def get_symbols() -> list[str]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    symbols = pd.read_sql_query(
        "SELECT DISTINCT symbol FROM snapshots ORDER BY symbol", conn
    )["symbol"].tolist()
    conn.close()
    return symbols


@st.cache_data(ttl=60)
def get_snapshot_times(symbol: str) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    times = pd.read_sql_query(
        "SELECT DISTINCT snapshot_time FROM snapshots WHERE symbol = ? "
        "ORDER BY snapshot_time DESC",
        conn, params=[symbol],
    )["snapshot_time"].tolist()
    conn.close()
    return times


@st.cache_data(ttl=60)
def load_snapshot(symbol: str, snapshot_time: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM snapshots WHERE symbol = ? AND snapshot_time = ?",
        conn, params=[symbol, snapshot_time],
    )
    conn.close()
    return df


st.title("📊 Options Chain Tracker")

symbols = get_symbols()

st.subheader("Ticker")
search_col1, search_col2 = st.columns([3, 1])
with search_col1:
    default_symbol = st.session_state.get("current_symbol", symbols[0] if symbols else "")
    search_ticker = st.text_input(
        "Type a ticker symbol (e.g. TSLA, MSFT, NVDA) — press Enter to view, "
        "or click Fetch to pull fresh live data",
        value=default_symbol,
        placeholder="Enter ticker...",
    ).strip().upper()
with search_col2:
    st.write("")  # vertical spacer to align button with text input
    fetch_clicked = st.button("Fetch live chain", use_container_width=True)

num_expirations_to_fetch = st.slider(
    "Number of upcoming expirations to fetch",
    min_value=2, max_value=20, value=12,
    help="More expirations = more data pulled per fetch, takes longer.",
)

auto_refresh = st.toggle(
    "🔄 Live auto-refresh (every 30s while market is open)",
    value=False,
    help="When on, automatically re-fetches the current ticker's chain every "
         "30 seconds and reloads the page. Leave off to only refresh "
         "manually with the Fetch button.",
)

if fetch_clicked and search_ticker:
    with st.spinner(f"Fetching chain for {search_ticker}..."):
        try:
            from qt_chain import get_full_chain
            from qt_db import init_db, save_snapshot

            new_df = get_full_chain(search_ticker, num_expirations=num_expirations_to_fetch)
            init_db()
            save_snapshot(new_df, symbol=search_ticker)
            st.success(f"Fetched and saved {len(new_df)} contracts for {search_ticker}.")
            st.cache_data.clear()  # refresh symbol/snapshot lists so it shows up below
            symbols = get_symbols()
        except Exception as e:
            st.error(f"Couldn't fetch {search_ticker}: {e}")

if not symbols:
    st.warning(
        "No data yet. Search a ticker above and click Fetch, or run "
        "`python3 watchlist_snapshot.py` to populate your watchlist."
    )
    st.stop()

if search_ticker and search_ticker in symbols:
    symbol = search_ticker
elif symbols:
    symbol = symbols[0]
else:
    st.warning(f"No saved data for '{search_ticker}' yet — click Fetch live chain to pull it.")
    st.stop()

st.session_state["current_symbol"] = symbol

if auto_refresh:
    # Re-fetch the current symbol automatically, throttled to once per 30s
    # via caching (so a page full of viewers doesn't hammer Questrade —
    # everyone shares the same cached pull within that window).
    @st.cache_data(ttl=30)
    def auto_fetch_chain(sym: str, n_exp: int):
        from qt_chain import get_full_chain
        from qt_db import init_db, save_snapshot

        fresh_df = get_full_chain(sym, num_expirations=n_exp)
        init_db()
        save_snapshot(fresh_df, symbol=sym)
        return len(fresh_df)

    try:
        rows_saved = auto_fetch_chain(symbol, num_expirations_to_fetch)
        st.caption(f"🔄 Live auto-refresh on — last pull: {rows_saved} contracts for {symbol}")
    except Exception as e:
        st.caption(f"⚠️ Auto-refresh failed: {e}")

    # Forces the browser to reload the whole page every 30s, which re-runs
    # this script and (via the cache above) checks for fresh data.
    st.markdown('<meta http-equiv="refresh" content="30">', unsafe_allow_html=True)

# Spot price for the underlying, shown next to the chain
@st.cache_data(ttl=60)
def get_cached_spot_price(sym: str):
    try:
        from qt_chain import get_spot_price
        return get_spot_price(sym)
    except Exception:
        return None

spot_price = get_cached_spot_price(symbol)
if spot_price:
    st.metric(f"{symbol} spot price", f"${spot_price:,.2f}")

times = get_snapshot_times(symbol)
snapshot_time = st.selectbox(
    "Snapshot (most recent first)", times,
    format_func=lambda t: t.replace("T", " ").split(".")[0] + " UTC",
)

df = load_snapshot(symbol, snapshot_time)

if df.empty:
    st.warning("No data for this selection.")
    st.stop()

_, label_col1, toggle_col, label_col2, _ = st.columns([4, 1, 1, 1, 4])
with label_col1:
    st.markdown(
        "<div style='text-align:right; padding-top:14px; font-weight:800; "
        "font-size:22px; color:#26a69a; white-space:nowrap;'>CALL</div>",
        unsafe_allow_html=True,
    )
with toggle_col:
    st.markdown(
        "<div style='transform:scale(1.6); transform-origin:center; "
        "display:flex; justify-content:center; padding-top:6px;'>",
        unsafe_allow_html=True,
    )
    is_put = st.toggle(" ", value=False, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
with label_col2:
    st.markdown(
        "<div style='text-align:left; padding-top:14px; font-weight:800; "
        "font-size:22px; color:#ef5350; white-space:nowrap;'>PUT</div>",
        unsafe_allow_html=True,
    )
option_side = "put" if is_put else "call"
df_side = df[df["type"] == option_side]

st.caption(
    f"{len(df)} total contracts in this snapshot · "
    f"{df['expiration'].nunique()} expirations · "
    f"taken {snapshot_time.replace('T', ' ').split('.')[0]} UTC"
)

st.caption("Filter strikes")
all_strikes = sorted(df_side["strike"].unique())

if spot_price:
    # Default to within 30% of the current spot price — keeps the heatmap
    # focused on strikes that are actually relevant to where the stock is
    # trading right now, instead of showing the full chain including far
    # OTM strikes nobody's looking at.
    target_lo = spot_price * 0.7
    target_hi = spot_price * 1.3
    default_lo = max(all_strikes[0], min(s for s in all_strikes if s >= target_lo) if any(s >= target_lo for s in all_strikes) else all_strikes[0])
    default_hi = min(all_strikes[-1], max(s for s in all_strikes if s <= target_hi) if any(s <= target_hi for s in all_strikes) else all_strikes[-1])
else:
    strikes_with_volume = sorted(df_side[df_side["volume"] > 0]["strike"].unique())
    if strikes_with_volume:
        default_lo, default_hi = strikes_with_volume[0], strikes_with_volume[-1]
    else:
        default_lo, default_hi = all_strikes[0], all_strikes[-1]

strike_range = st.slider(
    "Strike price range",
    min_value=float(all_strikes[0]),
    max_value=float(all_strikes[-1]),
    value=(float(default_lo), float(default_hi)),
    label_visibility="collapsed",
    help="Defaults to ±30% of current spot price.",
)

def format_compact(v) -> str:
    if pd.isna(v):
        return ""
    v = float(v)
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:.0f}"


def value_to_color(norm: float) -> str:
    """Dark purple (low) -> purple (mid) -> gold (high), matching the
    Obsidian-style gradient. norm is 0-1."""
    norm = max(0.0, min(1.0, norm))
    dark = (21, 16, 31)
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


tab_heatmap, tab_chart, tab_exposure, tab_data = st.tabs(
    ["📊 Heatmap", "📈 Chart", "⚡ Exposure", "🗂️ Data"]
)

with tab_heatmap:
    st.subheader(f"Volume heatmap — {symbol} {option_side}s")

    df_filtered = df_side[
        (df_side["strike"] >= strike_range[0]) & (df_side["strike"] <= strike_range[1])
    ]

    pivot = df_filtered.pivot_table(
        index="strike", columns="expiration", values="volume", aggfunc="sum"
    ).sort_index(ascending=False)

    max_val = pivot.max().max()
    max_val = max_val if max_val and max_val > 0 else 1
    # Square-root normalization spreads out the lower values more, similar to
    # how the reference heatmap visually distinguishes mid-volume cells instead
    # of everything below the single max looking equally dark.
    norm_pivot = (pivot / max_val).pow(0.5)

    strikes_sorted = list(pivot.index)  # already descending
    expiries = list(pivot.columns)

    rows_html = []
    spot_marker_inserted = (spot_price is None)

    for strike in strikes_sorted:
        if not spot_marker_inserted and strike < spot_price:
            spot_marker_inserted = True
            n_cols = len(expiries)
            rows_html.append(
                f'<tr class="spot-row"><td class="spot-label">SPOT {spot_price:,.2f}</td>'
                f'<td colspan="{n_cols}" class="spot-line"></td></tr>'
            )

        cells = [f'<td class="strike-label">{strike:g}</td>']
        for exp in expiries:
            val = pivot.loc[strike, exp]
            norm = norm_pivot.loc[strike, exp]
            if pd.isna(val):
                cells.append('<td class="cell empty"></td>')
            else:
                color = value_to_color(norm)
                text = format_compact(val)
                cells.append(
                    f'<td class="cell"><div class="pill" style="background:{color}">{text}</div></td>'
                )
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    header_cells = "".join(f'<th class="exp-header">{exp}</th>' for exp in expiries)

    heatmap_html = f"""
    <style>
    .heatmap-wrap {{
        background:#1a1a1a;
        border-radius:8px;
        padding:12px;
        overflow-x:auto;
    }}
    .heatmap-table {{
        border-collapse:separate;
        border-spacing:4px;
        width:100%;
        font-family:monospace;
    }}
    .exp-header {{
        color:#aaa;
        font-size:12px;
        font-weight:600;
        text-align:center;
        padding:4px 8px;
        white-space:nowrap;
    }}
    .strike-label {{
        color:#ccc;
        font-size:13px;
        text-align:right;
        padding-right:10px;
        white-space:nowrap;
    }}
    .cell {{
        text-align:center;
        padding:0;
    }}
    .pill {{
        border-radius:6px;
        padding:8px 10px;
        color:white;
        font-weight:700;
        font-size:13px;
        text-align:center;
        white-space:nowrap;
    }}
    .spot-row td {{
        padding:2px 0;
    }}
    .spot-label {{
        color:#1a1a1a;
        background:#fff;
        font-size:11px;
        font-weight:700;
        text-align:right;
        padding:2px 8px;
        border-radius:4px;
        white-space:nowrap;
    }}
    .spot-line {{
        border-top:2px dashed #f0d060;
    }}
    </style>
    <div class="heatmap-wrap">
    <table class="heatmap-table">
    <tr><th></th>{header_cells}</tr>
    {''.join(rows_html)}
    </table>
    </div>
    """

    st.markdown(heatmap_html, unsafe_allow_html=True)

with tab_chart:
    st.subheader(f"{symbol} price chart — top 5 strikes by volume")

    # Interval selector — maps display label to Questrade interval enum + sensible default lookback
    INTERVALS = {
        "1m":  ("OneMinute",    1),
        "5m":  ("FiveMinutes",  3),
        "15m": ("FifteenMinutes", 7),
        "1h":  ("OneHour",     30),
        "4h":  ("FourHours",   60),
        "1D":  ("OneDay",      90),
    }

    int_col1, int_col2, int_col3, int_col4, int_col5, int_col6 = st.columns(6)
    interval_cols = [int_col1, int_col2, int_col3, int_col4, int_col5, int_col6]
    labels = list(INTERVALS.keys())

    if "chart_interval" not in st.session_state:
        st.session_state["chart_interval"] = "1D"

    for col, label in zip(interval_cols, labels):
        with col:
            is_active = st.session_state["chart_interval"] == label
            if st.button(
                label,
                key=f"interval_{label}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                st.session_state["chart_interval"] = label

    selected_interval = st.session_state["chart_interval"]
    qt_interval, default_days = INTERVALS[selected_interval]

    chart_days = st.slider(
        "Days of price history",
        min_value=1,
        max_value=365,
        value=default_days,
        step=1,
    )

    @st.cache_data(ttl=60)
    def get_cached_candles(sym: str, days: int, interval: str):
        from qt_chain import get_candles
        return get_candles(sym, days=days, interval=interval)

    try:
        candles = get_cached_candles(symbol, chart_days, qt_interval)
    except Exception as e:
        candles = pd.DataFrame()
        st.error(f"Couldn't load price history: {e}")

    if not candles.empty:
        import plotly.graph_objects as go

        # Top 5 strikes by volume, across whichever expirations are currently
        # selected in the strike-range filter above (this side: call or put).
        top5 = (
            df_filtered.groupby("strike")["volume"].sum()
            .sort_values(ascending=False)
            .head(5)
        )

        price_fig = go.Figure()
        price_fig.add_trace(go.Candlestick(
            x=candles["date"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name=symbol,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ))

        line_colors = ["#f0b429", "#5b3aa0", "#26a69a", "#ef5350", "#42a5f5"]
        for i, (strike, vol) in enumerate(top5.items()):
            color = line_colors[i % len(line_colors)]
            price_fig.add_hline(
                y=strike,
                line_dash="dash",
                line_color=color,
                line_width=1.5,
                annotation_text=f"{strike:g} ({format_compact(vol)} vol)",
                annotation_position="right",
                annotation_font=dict(color=color, size=12),
            )

        if spot_price:
            price_fig.add_hline(
                y=spot_price,
                line_dash="dot",
                line_color="white",
                line_width=1,
                annotation_text=f"spot {spot_price:,.2f}",
                annotation_position="left",
                annotation_font=dict(color="white", size=11),
            )

        price_fig.update_layout(
            height=600,
            xaxis_rangeslider_visible=False,
            plot_bgcolor="#1a1a1a",
            paper_bgcolor="#1a1a1a",
            font=dict(color="#ccc"),
            margin=dict(l=10, r=80, t=20, b=10),
        )
        price_fig.update_xaxes(gridcolor="#333")
        price_fig.update_yaxes(gridcolor="#333")

        st.plotly_chart(price_fig, use_container_width=True)
        st.caption(
            f"Top 5 {option_side} strikes by volume (within currently selected "
            f"strike range / expirations) overlaid as horizontal lines."
        )
    else:
        st.info("No price history available for this symbol yet.")

with tab_exposure:
    from qt_exposure import compute_gex, compute_vex, detect_unusual_volume

    df_for_exposure = df[
        (df["strike"] >= strike_range[0]) & (df["strike"] <= strike_range[1])
    ]

    if not spot_price:
        st.warning("Spot price unavailable — exposure calculations need it to run.")
    else:
        gex_or_vex = st.radio(
            "Exposure type", ["GEX", "VEX"], horizontal=True, label_visibility="collapsed"
        )

        def signed_value_to_color(val: float, max_abs: float) -> str:
            """Negative -> red gradient. Positive -> dark purple -> gold gradient.
            Matches the Obsidian exposure heatmap color scheme."""
            if max_abs == 0:
                norm = 0
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

        def format_money(v: float) -> str:
            sign = "-" if v < 0 else ""
            v = abs(v)
            if v >= 1_000_000:
                return f"{sign}${v/1_000_000:.1f}M"
            if v >= 1_000:
                return f"{sign}${v/1_000:.1f}K"
            return f"{sign}${v:.0f}"

        if gex_or_vex == "GEX":
            exp_df = compute_gex(df_for_exposure, spot_price)
            value_col = "net_gex"
            title = "Gamma Exposure (GEX)"
            subtitle = (
                "Dollars of dealer hedging exposure per 1% move. Calls "
                "positive (purple/gold = stabilizing), puts negative (red = "
                "destabilizing)."
            )
        else:
            exp_df = compute_vex(df_for_exposure)
            value_col = "net_vex"
            title = "Vega Exposure (VEX)"
            subtitle = (
                "Dollars of dealer exposure per 1-point move in implied "
                "volatility. Dealer-short convention."
            )

        st.subheader(f"{symbol} {title}")
        st.caption(subtitle)

        if exp_df.empty:
            st.info("No data in this strike range to compute exposure.")
        else:
            strikes_desc = sorted(exp_df.index, reverse=True)
            max_abs_val = exp_df[value_col].abs().max()
            max_abs_val = max_abs_val if max_abs_val and max_abs_val > 0 else 1
            most_extreme_strike = exp_df[value_col].abs().idxmax()

            rows_html = []
            spot_marker_inserted = False

            for strike in strikes_desc:
                if not spot_marker_inserted and strike < spot_price:
                    spot_marker_inserted = True
                    rows_html.append(
                        f'<tr class="spot-row-exp"><td class="spot-label-exp">'
                        f'SPOT {spot_price:,.2f}</td>'
                        f'<td class="spot-line-exp"></td></tr>'
                    )

                val = exp_df.loc[strike, value_col]
                color = signed_value_to_color(val, max_abs_val)
                text = format_money(val)
                highlight = " exp-highlight" if strike == most_extreme_strike else ""

                rows_html.append(
                    f'<tr><td class="strike-label-exp">{strike:g}</td>'
                    f'<td class="cell-exp"><div class="pill-exp{highlight}" '
                    f'style="background:{color}">{text}</div></td></tr>'
                )

            exposure_html = f"""
            <style>
            .exp-wrap {{
                background:#0d0d0d;
                border-radius:8px;
                padding:12px;
                max-height:700px;
                overflow-y:auto;
            }}
            .exp-table {{
                border-collapse:separate;
                border-spacing:0 3px;
                width:100%;
                font-family:monospace;
            }}
            .strike-label-exp {{
                color:#999;
                font-size:13px;
                text-align:right;
                padding-right:12px;
                white-space:nowrap;
                width:60px;
            }}
            .cell-exp {{
                padding:0;
            }}
            .pill-exp {{
                border-radius:4px;
                padding:9px 14px;
                color:white;
                font-weight:700;
                font-size:13px;
                text-align:right;
                white-space:nowrap;
            }}
            .exp-highlight {{
                border:2px solid white;
            }}
            .spot-row-exp td {{
                padding:3px 0;
            }}
            .spot-label-exp {{
                color:#1a1a1a;
                background:#fff;
                font-size:11px;
                font-weight:700;
                text-align:right;
                padding:2px 8px;
                border-radius:4px;
                white-space:nowrap;
            }}
            .spot-line-exp {{
                border-top:2px dashed #f0d060;
            }}
            </style>
            <div class="exp-wrap">
            <table class="exp-table">
            {''.join(rows_html)}
            </table>
            </div>
            """
            st.markdown(exposure_html, unsafe_allow_html=True)

            net_total = exp_df[value_col].sum()
            label = "net positive" if net_total >= 0 else "net negative"
            st.metric(f"Total net {gex_or_vex}", format_money(net_total), help=label)

    st.divider()

    st.subheader(f"{symbol} Unusual Volume")
    st.caption(
        "Contracts where today's volume is at least 2x open interest — "
        "the signature of a fresh position opening today rather than "
        "ongoing activity in an already-established position."
    )

    unusual_df = detect_unusual_volume(df_for_exposure, min_volume=50)
    if unusual_df.empty:
        st.info("No unusual volume detected in this strike range right now.")
    else:
        st.dataframe(
            unusual_df.rename(columns={"volume_oi_ratio": "volume/OI ratio"}),
            use_container_width=True,
            hide_index=True,
        )

with tab_data:
    df_filtered = df_side[
        (df_side["strike"] >= strike_range[0]) & (df_side["strike"] <= strike_range[1])
    ]

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Max-volume strike per expiration")
        summary = max_volume_per_expiry(df)
        summary_side = summary[summary["type"] == option_side].drop(columns=["type"])
        st.dataframe(summary_side, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Top 10 by volume (this side)")
        top10 = df_side.sort_values("volume", ascending=False).head(10)[
            ["expiration", "strike", "volume", "openInterest"]
        ]
        st.dataframe(top10, use_container_width=True, hide_index=True)

    with st.expander("Raw data for this snapshot", expanded=True):
        st.dataframe(
            df_side.sort_values(["expiration", "strike"]), use_container_width=True
        )
