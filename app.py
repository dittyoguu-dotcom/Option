"""
NIFTY OI Confluence Dashboard — powered by live Fyers API data.

What this app does
-------------------
- Logs you into Fyers (inside the app, no coding needed).
- Polls the live option chain for a strike + type you pick.
- Classifies every price tick into Long Buildup / Short Buildup /
  Short Covering / Long Unwinding, exactly like the demo you saw.
- Shows PCR, Market Control, Support/Resistance zones, a Confluence
  verdict, and OI alerts — same layout as the mock dashboard.

Everything runs from Streamlit Secrets — you never paste your
API key/secret into the code itself.
"""

import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="NIFTY OI Confluence Dashboard", layout="wide", page_icon="📈")

DARK_CSS = """
<style>
.stApp { background-color: #0b0e11; color: #e7e9ea; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; }
[data-testid="stMetricValue"] { font-family: monospace; }

/* Stat cards used throughout instead of st.metric, so labels/values never
   truncate on a narrow phone screen. */
.stat-row { display: flex; gap: 10px; margin: 6px 0 14px 0; flex-wrap: wrap; }
.stat-card {
    flex: 1 1 0; min-width: 104px; background: #12161b; border: 1px solid #20252c;
    border-radius: 12px; padding: 12px 14px;
}
.stat-label {
    color: #7d8590; font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    font-family: monospace; margin-bottom: 4px;
}
.stat-value {
    font-family: monospace; font-size: 22px; font-weight: 700; color: #e7e9ea;
    line-height: 1.15; word-break: break-word;
}
.stat-badge {
    display: inline-block; margin-top: 6px; font-size: 11px; font-family: monospace;
    padding: 2px 8px; border-radius: 999px; font-weight: 600;
}

.section-title {
    font-family: monospace; font-size: 12px; color: #7d8590; text-transform: uppercase;
    letter-spacing: .05em; margin: 18px 0 6px 0;
}

.confluence-box {
    border-radius: 12px; padding: 14px 16px; margin: 4px 0 16px 0; border: 1px solid;
}
</style>
"""
st.markdown(DARK_CSS, unsafe_allow_html=True)


def stat_card(label, value, badge=None, badge_bg="#1c2b20", badge_color="#3fb950"):
    badge_html = (
        f"<span class='stat-badge' style='background:{badge_bg};color:{badge_color};'>{badge}</span>"
        if badge else ""
    )
    return (
        f"<div class='stat-card'><div class='stat-label'>{label}</div>"
        f"<div class='stat-value'>{value}</div>{badge_html}</div>"
    )


def stat_row(cards_html):
    st.markdown(f"<div class='stat-row'>{''.join(cards_html)}</div>", unsafe_allow_html=True)


# Shared config for every Plotly chart in the app — no modebar clutter
# (camera/zoom/pan icons colliding with legends), touch pinch-zoom stays on.
CHART_CONFIG = {"scrollZoom": True, "displayModeBar": False}

CATS = [
    {"key": "long_build", "label": "Long buildup", "sub": "premium ↑ · OI ↑", "color": "#3fb950"},
    {"key": "short_build", "label": "Short buildup", "sub": "premium ↓ · OI ↑", "color": "#f85149"},
    {"key": "short_cover", "label": "Short covering", "sub": "premium ↑ · OI ↓", "color": "#58a6ff"},
    {"key": "long_unwind", "label": "Long unwinding", "sub": "premium ↓ · OI ↓", "color": "#d29922"},
]

UNDERLYING = "NSE:NIFTY50-INDEX"

# ---------------------------------------------------------------------------
# Fyers auth — done inside the app via redirect, no manual code pasting.
# Put these three in Streamlit Cloud -> App settings -> Secrets:
#   FYERS_APP_ID = "XXXXXXX-100"
#   FYERS_SECRET_ID = "XXXXXXXXXX"
#   FYERS_REDIRECT_URI = "https://your-app-name.streamlit.app"
#     (must exactly match the Redirect URL you set in myapi.fyers.in/dashboard)
# ---------------------------------------------------------------------------
try:
    from fyers_apiv3 import fyersModel
except ImportError:
    st.error("fyers-apiv3 is not installed. Check requirements.txt.")
    st.stop()


def get_secret(name):
    return st.secrets.get(name, "")


APP_ID = get_secret("FYERS_APP_ID")
SECRET_ID = get_secret("FYERS_SECRET_ID")
REDIRECT_URI = get_secret("FYERS_REDIRECT_URI")


def build_session():
    return fyersModel.SessionModel(
        client_id=APP_ID,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        state="oi_dashboard",
        secret_key=SECRET_ID,
        grant_type="authorization_code",
    )


def do_login_flow():
    """Handles the whole Fyers OAuth handshake using the URL Fyers redirects
    back to. Stores the access token in session_state once obtained."""
    if "fyers_token" in st.session_state:
        return True

    if not (APP_ID and SECRET_ID and REDIRECT_URI):
        st.warning(
            "Fyers credentials aren't configured yet. Add FYERS_APP_ID, "
            "FYERS_SECRET_ID and FYERS_REDIRECT_URI in Streamlit Secrets "
            "(see SETUP.md), then reload this page."
        )
        return False

    params = st.query_params
    auth_code = params.get("auth_code")

    if auth_code:
        session = build_session()
        session.set_token(auth_code)
        try:
            response = session.generate_token()
            token = response["access_token"]
            st.session_state["fyers_token"] = token
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {response if 'response' in dir() else e}")
            st.query_params.clear()
        return False

    # Not logged in yet — show the login link.
    session = build_session()
    login_url = session.generate_authcode()
    st.info("You're not logged in to Fyers yet.")
    st.link_button("🔑 Log in with Fyers", login_url, use_container_width=True)
    st.caption(
        "This opens Fyers' login page. After you sign in, it redirects you "
        "straight back here and the dashboard unlocks automatically."
    )
    return False


def get_fyers_client():
    return fyersModel.FyersModel(
        token=st.session_state["fyers_token"], is_async=False, client_id=APP_ID, log_path=""
    )


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_expiries(_fyers):
    resp = _fyers.optionchain(data={"symbol": UNDERLYING, "strikecount": 1, "timestamp": ""})
    if resp.get("s") != "ok":
        return [], resp
    expiries = resp["data"].get("expiryData", [])
    return expiries, resp


def fetch_chain(fyers, timestamp, strikecount=20):
    resp = fyers.optionchain(
        data={"symbol": UNDERLYING, "strikecount": strikecount, "timestamp": timestamp}
    )
    return resp


def fetch_spot(fyers):
    resp = fyers.quotes(data={"symbols": UNDERLYING})
    try:
        return resp["d"][0]["v"]["lp"]
    except Exception:
        return None


@st.cache_data(ttl=20, show_spinner=False)
def fetch_candles_range(_fyers, symbol, resolution, date_from, date_to):
    """Candles for any date range on any tradable Fyers symbol — used for
    both the live today-chart and the historical backtest view. (OI history
    isn't available from any broker API, but price history like this is.)"""
    fyers = _fyers
    resp = fyers.history(data={
        "symbol": symbol,
        "resolution": resolution,
        "date_format": "1",
        "range_from": date_from,
        "range_to": date_to,
        "cont_flag": "0",
    })
    if resp.get("s") != "ok":
        return [], resp
    return resp.get("candles", []), resp


def fetch_today_candles(fyers, symbol, resolution):
    today = datetime.now().strftime("%Y-%m-%d")
    return fetch_candles_range(fyers, symbol, resolution, today, today)


def swing_levels(candles, lookback=4):
    """Simple swing-high/low pivot detector, used as support/resistance for
    the backtest view since there's no OI to lean on for a past date."""
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        h, l = candles[i][2], candles[i][3]
        if h == max(c[2] for c in window):
            highs.append(h)
        if l == min(c[3] for c in window):
            lows.append(l)
    resistance = max(highs) if highs else None
    support = min(lows) if lows else None
    return support, resistance


def demo_candles(strike, opt_type, resolution_minutes=5):
    """Synthetic full-session candles for demo mode, built from the same
    seeded random walk as demo_ticks, spread across market hours."""
    ticks = demo_ticks(strike, opt_type, n=150)
    now = datetime.now()
    session_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    session_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now < session_start:
        session_end = session_start + timedelta(hours=6, minutes=15)
    elif now < session_end:
        session_end = now
    span = max(60, (session_end - session_start).total_seconds())
    step = span / len(ticks)
    for i, t in enumerate(ticks):
        t["dt"] = session_start + timedelta(seconds=i * step)

    bins = {}
    for t in ticks:
        floored_minute = t["dt"].minute - (t["dt"].minute % resolution_minutes)
        bin_key = t["dt"].replace(minute=floored_minute, second=0, microsecond=0)
        bins.setdefault(bin_key, []).append(t)
    candles = []
    for k in sorted(bins):
        vals = bins[k]
        prices = [v["premium"] for v in vals]
        vol = sum(v["volume"] for v in vals)
        candles.append([k.timestamp(), prices[0], max(prices), min(prices), prices[-1], vol])
    return candles


def render_price_chart(candles, support=None, resistance=None):
    """TradingView-style candlestick + volume panel."""
    if not candles:
        st.info("No candle data yet — try again shortly, or check if the market is open.")
        return
    times = [datetime.fromtimestamp(c[0]) for c in candles]
    opens = [c[1] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    vols = [c[5] for c in candles]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=times, open=opens, high=highs, low=lows, close=closes,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
        name="Premium", showlegend=False,
    ), row=1, col=1)

    if support:
        fig.add_hline(y=(support["low"] + support["high"]) / 2, line_dash="dot", line_color="#3fb950",
                       annotation_text="Support", annotation_font_color="#3fb950",
                       annotation_position="right", row=1, col=1)
    if resistance:
        fig.add_hline(y=(resistance["low"] + resistance["high"]) / 2, line_dash="dot", line_color="#f85149",
                       annotation_text="Resistance", annotation_font_color="#f85149",
                       annotation_position="right", row=1, col=1)

    vol_colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(opens, closes)]
    fig.add_trace(go.Bar(x=times, y=vols, marker_color=vol_colors, name="Volume", showlegend=False), row=2, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722",
        height=440, margin=dict(l=10, r=48, t=18, b=10),
        xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False,
        dragmode="pan",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#1e222d")
    fig.update_yaxes(showgrid=True, gridcolor="#1e222d", row=1, col=1)
    fig.update_yaxes(showgrid=False, row=2, col=1)
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)


# ---------------------------------------------------------------------------
# Tick classification — identical logic to the mock demo, applied to real
# polled data. Each poll = one "tick" for the selected strike+type.
# ---------------------------------------------------------------------------
def classify_and_bucket(ticks, bucket_size):
    buckets = {}
    for t in ticks:
        low = ((t["premium"] - 1) // bucket_size) * bucket_size + 1
        b = buckets.setdefault(
            low,
            {"low": low, "high": low + bucket_size - 1, "long_build": 0, "short_build": 0,
             "long_unwind": 0, "short_cover": 0, "volume": 0, "oi_abs": 0},
        )
        price_up = t["premium"] >= t["prev_premium"]
        oi_up = t["oi_delta"] >= 0
        mag = abs(t["oi_delta"])
        if price_up and oi_up:
            b["long_build"] += mag
        elif not price_up and oi_up:
            b["short_build"] += mag
        elif not price_up and not oi_up:
            b["long_unwind"] += mag
        else:
            b["short_cover"] += mag
        b["volume"] += t.get("volume", 0)
        b["oi_abs"] += mag
    return sorted(buckets.values(), key=lambda b: b["low"])


def vol_oi_tag(b):
    if b["oi_abs"] == 0:
        return "No OI activity", "#4b5158"
    ratio = b["volume"] / b["oi_abs"] if b["oi_abs"] else 0
    if ratio > 9:
        return "High volume · low OI Δ — churn/scalping", "#d29922"
    if ratio < 3:
        return "Low volume · high OI Δ — quiet buildup", "#58a6ff"
    return "Balanced volume vs OI", "#9aa0a6"


# ---------------------------------------------------------------------------
# Demo mode — same seeded mock generator as the original preview, so the
# dashboard is still meaningful outside market hours.
# ---------------------------------------------------------------------------
def demo_ticks(strike, opt_type, n=150):
    import math
    import random
    rand = random.Random(f"{strike}-{opt_type}")
    dist = abs(strike - 24525)
    time_value = max(6, 70 - dist * 0.11)
    intrinsic = max(0, 24525 - strike) if opt_type == "CE" else max(0, strike - 24525)
    premium = max(4, intrinsic + time_value)
    oi = 400000 + rand.randint(0, 500000)
    ticks = []
    for i in range(n):
        # sine wander + noise, same shape as the original JS mock, so a full
        # session spans a realistic premium range instead of a flat ₹10-20 band
        drift = math.sin(i / 9 + rand.random() * 3) * 1.6 + (rand.random() - 0.5) * 2.4
        prev = premium
        premium = max(2, premium + drift)
        oi_delta = round((rand.random() - 0.42) * 9000)
        oi = max(1000, oi + oi_delta)
        volume = int(400 + abs(premium - prev) * 900 + rand.random() * 1800)
        ticks.append({"time": (datetime.now() - timedelta(minutes=(n - i) * 2)).strftime("%H:%M"),
                       "premium": round(premium, 1), "prev_premium": round(prev, 1),
                       "oi_delta": oi_delta, "oi": oi, "volume": volume})
    return ticks


def demo_day_candles(symbol_label, day, resolution_minutes=5):
    """Synthetic full-session candles for a chosen past date in demo mode —
    seeded by the date itself, so the same date always replays identically."""
    import math
    import random
    rand = random.Random(f"{symbol_label}-{day.isoformat()}")
    session_start = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15)
    session_end = datetime.combine(day, datetime.min.time()).replace(hour=15, minute=30)
    n = 150
    base = 24500 + rand.randint(-300, 300)
    price = base
    candles = []
    step = (session_end - session_start).total_seconds() / n
    for i in range(n):
        drift = math.sin(i / 11 + rand.random() * 3) * 12 + (rand.random() - 0.5) * 18
        o = price
        price = max(1, price + drift)
        h = max(o, price) + rand.random() * 6
        l = min(o, price) - rand.random() * 6
        vol = int(2000 + abs(price - o) * 400 + rand.random() * 4000)
        ts = (session_start + timedelta(seconds=i * step)).timestamp()
        candles.append([ts, o, h, l, price, vol])
    return candles


def render_backtest(fyers, mode):
    """Historical price backtest — scrub through any past session candle by
    candle. There's no historical OI to backtest against (no broker API
    exposes it), so this view works on price action only: real candles,
    swing-based support/resistance, and a time slider."""
    st.sidebar.subheader("Backtest settings")
    default_day = datetime.now().date() - timedelta(days=1)
    bt_date = st.sidebar.date_input("Date", value=default_day, max_value=datetime.now().date())
    bt_resolution = st.sidebar.select_slider(
        "Candle interval", options=["1", "5", "15", "60"], value="5",
        format_func=lambda v: f"{v} min",
    )
    instrument = st.sidebar.radio("Instrument", ["NIFTY Index", "Custom option symbol"])
    if instrument == "Custom option symbol":
        symbol = st.sidebar.text_input(
            "Fyers symbol", placeholder="e.g. NSE:NIFTY25AUG24500CE",
            help="Exact contract symbol as Fyers names it. Only works if that "
                 "contract existed and traded on the date you picked.",
        )
        if not symbol:
            st.info("Enter a Fyers option symbol in the sidebar to backtest it, "
                     "or switch to NIFTY Index.")
            return
        label = symbol
    else:
        symbol = UNDERLYING
        label = "NIFTY 50 Index"

    day_str = bt_date.strftime("%Y-%m-%d")

    if mode == "Live (Fyers)":
        candles, resp = fetch_candles_range(fyers, symbol, bt_resolution, day_str, day_str)
        if not candles:
            st.warning(
                f"No candle data for {label} on {day_str}: "
                f"{resp.get('message', resp)}. Try a different date, or check "
                "the market was open that day."
            )
            return
    else:
        candles = demo_day_candles(label, bt_date, resolution_minutes=int(bt_resolution))

    st.markdown(f"### 🔁 Backtest — {label} · {day_str}")
    st.caption(
        "Price-only replay. There's no historical OI available from Fyers "
        "or any broker API, so buildup categories can't be reconstructed "
        "for past sessions — only from days you record going forward."
    )

    # Scrub slider — like the original demo's time toggle
    n = len(candles)
    idx = st.slider(
        "Scrub through the session", 0, n - 1, n - 1,
        format=f"candle %d of {n}",
    )
    visible = candles[: idx + 1]
    current_time = datetime.fromtimestamp(visible[-1][0]).strftime("%H:%M")
    support, resistance = swing_levels(visible)

    chg_badge = None
    chg_positive = True
    if len(visible) > 1:
        chg = visible[-1][4] - visible[0][1]
        chg_pct = chg / visible[0][1] * 100
        chg_badge = f"{chg:+.1f} ({chg_pct:+.2f}%)"
        chg_positive = chg >= 0
    stat_row([
        stat_card("Time", current_time),
        stat_card("Price", f"₹{visible[-1][4]:.1f}"),
        stat_card("Change from open", chg_badge or "—",
                   badge_bg="#1c2b20" if chg_positive else "#2b1c1c",
                   badge_color="#3fb950" if chg_positive else "#f85149") if chg_badge else
        stat_card("Change from open", "—"),
    ])

    sup_obj = {"low": support, "high": support} if support else None
    res_obj = {"low": resistance, "high": resistance} if resistance else None
    render_price_chart(visible, support=sup_obj, resistance=res_obj)

    stat_row([
        stat_card("🟢 Swing support", f"₹{support:.1f}" if support else "—",
                   badge_bg="#1c2b20", badge_color="#3fb950"),
        stat_card("🔴 Swing resistance", f"₹{resistance:.1f}" if resistance else "—",
                   badge_bg="#2b1c1c", badge_color="#f85149"),
    ])

    with st.expander("Show candle data"):
        df = pd.DataFrame(visible, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="s").dt.strftime("%H:%M")
        st.dataframe(df[["time", "open", "high", "low", "close", "volume"]], use_container_width=True)


# ---------------------------------------------------------------------------
# Spot + OI-by-strike chart
# ---------------------------------------------------------------------------
def update_oi_accumulator(rows):
    """Runs on every poll against the FULL option chain. Keeps a running
    baseline (first poll of the session) and cumulative buildup/unwind
    totals per (strike, type) — same 4-way classification as the rest of
    the app, just tracked for every strike at once instead of one."""
    store = st.session_state.setdefault("oi_accum", {})
    for r in rows:
        strike = r.get("strike_price", -1)
        typ = r.get("option_type")
        if strike <= 0 or typ not in ("CE", "PE"):
            continue
        k = (strike, typ)
        oi = r.get("oi", 0)
        ltp = r.get("ltp", 0)
        entry = store.get(k)
        if entry is None:
            store[k] = {
                "baseline_oi": oi, "last_oi": oi, "last_premium": ltp,
                "long_build": 0, "short_build": 0, "long_unwind": 0, "short_cover": 0,
            }
            continue
        oi_delta = oi - entry["last_oi"]
        price_up = ltp >= entry["last_premium"]
        oi_up = oi_delta >= 0
        mag = abs(oi_delta)
        if price_up and oi_up:
            entry["long_build"] += mag
        elif not price_up and oi_up:
            entry["short_build"] += mag
        elif not price_up and not oi_up:
            entry["long_unwind"] += mag
        else:
            entry["short_cover"] += mag
        entry["last_oi"] = oi
        entry["last_premium"] = ltp
    return store


def demo_oi_accumulator(strikes, spot):
    """Deterministic-but-varied fake OI-change data per strike for demo mode."""
    import random
    store = {}
    for s in strikes:
        for typ in ("CE", "PE"):
            rand = random.Random(f"{s}-{typ}-oiwall")
            dist = (s - spot) / 50
            # Calls build up more above spot, puts build up more below spot —
            # a plausible-looking wall shape, purely for demo purposes.
            bias = -dist if typ == "CE" else dist
            base_change = int(bias * 15000 + rand.randint(-8000, 8000))
            long_build = max(0, base_change) + rand.randint(0, 4000)
            short_build = rand.randint(0, 6000)
            long_unwind = rand.randint(0, 5000)
            short_cover = max(0, -base_change) + rand.randint(0, 3000)
            store[(s, typ)] = {
                "baseline_oi": 400000, "last_oi": 400000 + base_change, "last_premium": 0,
                "long_build": long_build, "short_build": short_build,
                "long_unwind": long_unwind, "short_cover": short_cover,
            }
    return store


def render_spot_oi_chart(fyers, mode):
    """NIFTY spot candlestick with a linked OI-change-by-strike panel —
    calls in red, puts in green, sharing the same price axis so OI walls
    line up visually with the price levels that matter."""
    st.sidebar.subheader("Spot + OI chart settings")
    resolution = st.sidebar.select_slider(
        "Candle interval", options=["1", "5", "15"], value="5",
        format_func=lambda v: f"{v} min", key="soi_res",
    )
    strike_span = st.sidebar.slider("Strikes shown around spot", 6, 20, 12, key="soi_span")
    refresh_secs = st.sidebar.slider("Refresh every (sec)", 10, 60, 15, key="soi_refresh") if mode == "Live (Fyers)" else None

    if mode == "Live (Fyers)":
        expiries, raw = fetch_expiries(fyers)
        if not expiries:
            st.error(f"Couldn't load expiries from Fyers: {raw}")
            return
        expiry_labels = [e["date"] for e in expiries]
        expiry_choice = st.sidebar.selectbox("Expiry", expiry_labels, key="soi_expiry")
        expiry_ts = str(expiries[expiry_labels.index(expiry_choice)]["expiry"])

        chain_resp = fetch_chain(fyers, expiry_ts, strikecount=strike_span)
        if chain_resp.get("s") != "ok":
            st.error(f"Fyers error: {chain_resp}")
            return
        rows = chain_resp["data"]["optionsChain"]
        spot = fetch_spot(fyers) or 0
        store = update_oi_accumulator(rows)
        strikes = sorted({r["strike_price"] for r in rows if r.get("strike_price", -1) > 0})
        candles, cresp = fetch_today_candles(fyers, UNDERLYING, resolution)
        if not candles:
            st.caption(f"Spot chart unavailable right now: {cresp.get('message', cresp)}")
    else:
        spot = 24525
        strikes = sorted({spot + i * 50 for i in range(-strike_span // 2, strike_span // 2 + 1)})
        store = demo_oi_accumulator(strikes, spot)
        candles = demo_candles(24550, "CE", resolution_minutes=int(resolution))

    if not strikes:
        st.info("No strikes to show yet.")
        return

    strike_gap = 50
    if len(strikes) > 1:
        diffs = sorted(strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1))
        strike_gap = diffs[len(diffs) // 2]

    ce_changes = [store.get((s, "CE"), {}).get("last_oi", 0) - store.get((s, "CE"), {}).get("baseline_oi", 0) for s in strikes]
    pe_changes = [store.get((s, "PE"), {}).get("last_oi", 0) - store.get((s, "PE"), {}).get("baseline_oi", 0) for s in strikes]

    # --- Support / resistance from OI walls, with a strength label ---
    all_mags = [abs(v) for v in ce_changes + pe_changes] or [1]
    max_mag = max(all_mags)

    def strength_label(v):
        r = abs(v) / max_mag if max_mag else 0
        return "Strong" if r >= 0.66 else "Moderate" if r >= 0.33 else "Weak"

    resistance_strike = resistance_val = None
    support_strike = support_val = None
    for s, c in zip(strikes, ce_changes):
        if s >= spot and c > 0 and (resistance_val is None or c > resistance_val):
            resistance_strike, resistance_val = s, c
    for s, p in zip(strikes, pe_changes):
        if s <= spot and p > 0 and (support_val is None or p > support_val):
            support_strike, support_val = s, p

    # --- Build the chart: candlestick + linked OI-wall panel ---
    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, column_widths=[0.66, 0.34],
        horizontal_spacing=0.02, subplot_titles=("", "OI change by strike"),
    )

    if candles:
        times = [datetime.fromtimestamp(c[0]) for c in candles]
        fig.add_trace(go.Candlestick(
            x=times, open=[c[1] for c in candles], high=[c[2] for c in candles],
            low=[c[3] for c in candles], close=[c[4] for c in candles],
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
            name="NIFTY", showlegend=False,
        ), row=1, col=1)

    bar_width = strike_gap * 0.42
    fig.add_trace(go.Bar(
        x=ce_changes, y=[s + bar_width * 0.55 for s in strikes], orientation="h",
        marker_color="#ef5350", name="CE (Call) OI Δ", width=bar_width,
        customdata=[[s, "CE"] for s in strikes],
        hovertemplate="Strike %{customdata[0]}<br>CE OI change: %{x:,.0f}<extra></extra>",
    ), row=1, col=2)
    fig.add_trace(go.Bar(
        x=pe_changes, y=[s - bar_width * 0.55 for s in strikes], orientation="h",
        marker_color="#26a69a", name="PE (Put) OI Δ", width=bar_width,
        customdata=[[s, "PE"] for s in strikes],
        hovertemplate="Strike %{customdata[0]}<br>PE OI change: %{x:,.0f}<extra></extra>",
    ), row=1, col=2)

    if spot:
        fig.add_hline(y=spot, line_dash="dash", line_color="#9aa0a6", row=1, col=1)
        fig.add_hline(y=spot, line_dash="dash", line_color="#9aa0a6", row=1, col=2)
    if resistance_strike:
        lbl = f"Resistance {resistance_strike} ({strength_label(resistance_val)})"
        fig.add_hline(y=resistance_strike, line_dash="dot", line_color="#f85149",
                       annotation_text=lbl, annotation_font_color="#f85149", row=1, col=1)
        fig.add_hline(y=resistance_strike, line_dash="dot", line_color="#f85149", row=1, col=2)
    if support_strike:
        lbl = f"Support {support_strike} ({strength_label(support_val)})"
        fig.add_hline(y=support_strike, line_dash="dot", line_color="#3fb950",
                       annotation_text=lbl, annotation_font_color="#3fb950", row=1, col=1)
        fig.add_hline(y=support_strike, line_dash="dot", line_color="#3fb950", row=1, col=2)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722",
        height=540, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False, dragmode="pan",
        legend=dict(orientation="h", y=-0.06, x=0.5, xanchor="center"),
        barmode="overlay",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#1e222d", row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="#1e222d", zeroline=True, zerolinecolor="#3a3f4b", row=1, col=2)
    fig.update_yaxes(showgrid=True, gridcolor="#1e222d", row=1, col=1)
    fig.update_yaxes(showticklabels=False, row=1, col=2)

    st.markdown("### NIFTY Spot · OI change by strike")
    st.caption(
        f"Spot ₹{spot:,.2f} · red = Call OI change · green = Put OI change · "
        "dotted lines mark developing support/resistance"
    )
    event = st.plotly_chart(
        fig, use_container_width=True, config=CHART_CONFIG,
        on_select="rerun", key="spotoi_chart",
    )

    # --- Click a bar to see the buildup/unwind breakdown for that strike ---
    points = (event or {}).get("selection", {}).get("points", [])
    if points:
        cd = points[0].get("customdata")
        if cd:
            sel_strike, sel_type = cd[0], cd[1]
            entry = store.get((sel_strike, sel_type), {})
            net = entry.get("last_oi", 0) - entry.get("baseline_oi", 0)
            st.markdown(f"<div class='section-title'>NIFTY {sel_strike} {sel_type} — intraday OI breakdown</div>", unsafe_allow_html=True)
            stat_row([
                stat_card("Net OI change", f"{net:+,.0f}",
                           badge_bg="#1c2b20" if net >= 0 else "#2b1c1c",
                           badge_color="#3fb950" if net >= 0 else "#f85149"),
                stat_card("Long buildup", f"{entry.get('long_build', 0):,.0f}"),
            ])
            stat_row([
                stat_card("Short buildup", f"{entry.get('short_build', 0):,.0f}"),
                stat_card("Short covering", f"{entry.get('short_cover', 0):,.0f}"),
                stat_card("Long unwinding", f"{entry.get('long_unwind', 0):,.0f}"),
            ])
    else:
        st.caption("Tap a bar to see its long-build / short-build / covering / unwind breakdown.")

    if mode == "Live (Fyers)" and refresh_secs:
        time.sleep(refresh_secs)
        st.rerun()


# ---------------------------------------------------------------------------
# Sidebar — mode + controls
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Controls")
mode = st.sidebar.radio("Mode", ["Live (Fyers)", "Demo (no login needed)"])

if mode == "Live (Fyers)":
    logged_in = do_login_flow()
    if not logged_in:
        st.stop()
    fyers = get_fyers_client()
else:
    fyers = None

page = st.sidebar.radio("View", ["Live dashboard", "Historical backtest", "Spot + OI Chart"])
st.sidebar.divider()

if page == "Historical backtest":
    render_backtest(fyers, mode)
    st.stop()

if page == "Spot + OI Chart":
    render_spot_oi_chart(fyers, mode)
    st.stop()

if mode == "Live (Fyers)":
    expiries, raw = fetch_expiries(fyers)
    if not expiries:
        st.error(f"Couldn't load expiries from Fyers: {raw}")
        st.stop()
    expiry_labels = [e["date"] for e in expiries]
    expiry_choice = st.sidebar.selectbox("Expiry", expiry_labels)
    expiry_ts = str(expiries[expiry_labels.index(expiry_choice)]["expiry"])
else:
    expiry_ts = ""

chart_resolution = st.sidebar.select_slider(
    "Chart interval", options=["1", "5", "15"], value="5",
    format_func=lambda v: f"{v} min",
)
bucket_size = st.sidebar.select_slider("Bucket size (₹)", options=[5, 10, 20], value=10)
alert_on = st.sidebar.checkbox("Alert when a category exceeds", value=True)
alert_threshold = st.sidebar.number_input("Alert threshold (OI contracts)", value=50000, step=5000)
refresh_secs = st.sidebar.slider("Refresh every (sec)", 5, 60, 10) if mode == "Live (Fyers)" else None

st.sidebar.caption(
    "History only accumulates while this tab stays open. If the app "
    "restarts, the tick history resets."
)

# ---------------------------------------------------------------------------
# Strike / type selector
# ---------------------------------------------------------------------------
if mode == "Live (Fyers)":
    chain_resp = fetch_chain(fyers, expiry_ts, strikecount=20)
    if chain_resp.get("s") != "ok":
        st.error(f"Fyers error: {chain_resp}")
        st.stop()
    rows = chain_resp["data"]["optionsChain"]
    strikes = sorted({r["strike_price"] for r in rows if r.get("strike_price", -1) > 0})
    spot = fetch_spot(fyers) or chain_resp["data"].get("callOi", 0)
else:
    strikes = [24400, 24450, 24500, 24550, 24600, 24650, 24700]
    spot = 24525

c1, c2 = st.sidebar.columns(2)
strike = c1.selectbox("Strike", strikes, index=len(strikes) // 2)
opt_type = c2.radio("Type", ["CE", "PE"], horizontal=True)

# ---------------------------------------------------------------------------
# Tick history — accumulate real polls in session_state
# ---------------------------------------------------------------------------
key = f"ticks_{strike}_{opt_type}_{expiry_ts}"
baseline_key = f"baseline_{strike}_{opt_type}_{expiry_ts}"
if key not in st.session_state:
    st.session_state[key] = []

if mode == "Live (Fyers)":
    match = next((r for r in rows if r["strike_price"] == strike and r["option_type"] == opt_type), None)
    if match:
        hist = st.session_state[key]
        baseline = st.session_state.get(baseline_key)

        if baseline is None:
            # First poll for this contract — nothing to compare against yet,
            # so just record a baseline instead of a fake zero-change tick.
            st.session_state[baseline_key] = {
                "premium": match["ltp"], "oi": match["oi"], "volume": match.get("volume", 0),
            }
        else:
            new_tick = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "premium": match["ltp"],
                "prev_premium": baseline["premium"],
                "oi": match["oi"],
                "oi_delta": match["oi"] - baseline["oi"],
                # Fyers reports cumulative day volume, not per-poll volume —
                # take the difference so buckets reflect actual trading in
                # that interval, not the whole day's total re-added each poll.
                "volume": max(0, match.get("volume", 0) - baseline["volume"]),
            }
            # Only append if it's actually a new poll (avoid dup on same rerun)
            if not hist or hist[-1]["time"] != new_tick["time"]:
                hist.append(new_tick)
            st.session_state[baseline_key] = {
                "premium": match["ltp"], "oi": match["oi"], "volume": match.get("volume", 0),
            }
    ticks = st.session_state[key]
    # also pull CE/PE OI totals for PCR from this same poll (no extra call)
    ce_oi = sum(r["oi"] for r in rows if r["option_type"] == "CE")
    pe_oi = sum(r["oi"] for r in rows if r["option_type"] == "PE")
else:
    ticks = demo_ticks(strike, opt_type)
    ce_oi = sum(t["oi"] for t in demo_ticks(strike, "CE"))
    pe_oi = sum(t["oi"] for t in demo_ticks(strike, "PE"))

if not ticks:
    if mode == "Live (Fyers)":
        st.info(
            f"Collecting the first data point for NIFTY {strike} {opt_type}... "
            f"the chart needs at least two polls (~{refresh_secs}s apart) before "
            "it can show a change. It'll appear automatically."
        )
    else:
        st.info("Waiting for the first tick... this fills in as the market moves.")
    st.stop()

current_premium = ticks[-1]["premium"]
buckets = classify_and_bucket(ticks, bucket_size)

# ---------------------------------------------------------------------------
# Derived metrics — same logic as the demo
# ---------------------------------------------------------------------------
pcr = (pe_oi / ce_oi) if ce_oi else 0
pcr_label = "Bullish bias" if pcr >= 1.2 else "Bearish bias" if pcr <= 0.8 else "Neutral"
pcr_color = "#3fb950" if pcr >= 1.2 else "#f85149" if pcr <= 0.8 else "#9aa0a6"

resistance = sup = None
for b in buckets:
    mid = (b["low"] + b["high"]) / 2
    bearish = b["short_build"] + b["long_unwind"]
    bullish = b["long_build"] + b["short_cover"]
    if mid > current_premium and bearish > 0:
        if not resistance or bearish > resistance["score"]:
            resistance = {**b, "score": bearish}
    if mid < current_premium and bullish > 0:
        if not sup or bullish > sup["score"]:
            sup = {**b, "score": bullish}

buy = sum(b["long_build"] + b["short_cover"] for b in buckets)
sell = sum(b["short_build"] + b["long_unwind"] for b in buckets)
total = (buy + sell) or 1
buy_pct, sell_pct = buy / total * 100, sell / total * 100
control_verdict = "Buyers in control" if buy_pct >= 60 else "Sellers in control" if sell_pct >= 60 else "Balanced"

signals = []
signals.append(("Market Control", "bull" if control_verdict == "Buyers in control" else "bear" if control_verdict == "Sellers in control" else "neutral"))
signals.append(("PCR", "bull" if pcr_label == "Bullish bias" else "bear" if pcr_label == "Bearish bias" else "neutral"))
if sup and resistance:
    signals.append(("Zone strength", "bull" if sup["score"] > resistance["score"] else "bear"))
elif sup:
    signals.append(("Zone strength", "bull"))
elif resistance:
    signals.append(("Zone strength", "bear"))
else:
    signals.append(("Zone strength", "neutral"))

bulls = sum(1 for _, b in signals if b == "bull")
bears = sum(1 for _, b in signals if b == "bear")
if bulls >= 2 and bears == 0:
    confluence_text, confluence_color = "Aligned — bullish confluence", "#3fb950"
elif bears >= 2 and bulls == 0:
    confluence_text, confluence_color = "Aligned — bearish confluence", "#f85149"
else:
    confluence_text, confluence_color = "Mixed signals — proceed with caution", "#d29922"

alerts = []
if alert_on:
    for b in buckets:
        for c in CATS:
            if b[c["key"]] >= alert_threshold:
                alerts.append((b, c, b[c["key"]]))
    alerts.sort(key=lambda x: -x[2])

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
st.markdown(f"### NIFTY {strike} {opt_type}")
st.caption(f"{mode} · Spot ref ₹{spot:,.2f}" if spot else mode)

# --- Premium chart (TradingView-style candles) ---
if mode == "Live (Fyers)" and match:
    candles, candle_resp = fetch_today_candles(fyers, match["symbol"], chart_resolution)
    if not candles and candle_resp.get("s") != "ok":
        st.caption(f"Chart data unavailable for this contract: {candle_resp.get('message', candle_resp)}")
else:
    candles = demo_candles(strike, opt_type, resolution_minutes=int(chart_resolution))

if candles and len(candles) < 8:
    st.caption(f"Session just started — {len(candles)} candle(s) so far, more fill in as time passes.")

render_price_chart(candles, support=sup, resistance=resistance)

# --- Key stats, as cards (no truncation, consistent look) ---
stat_row([
    stat_card("PCR (same strike)", f"{pcr:.2f}", pcr_label,
              badge_bg="#1c2b20" if pcr_label == "Bullish bias" else "#2b1c1c" if pcr_label == "Bearish bias" else "#20242c",
              badge_color="#3fb950" if pcr_label == "Bullish bias" else "#f85149" if pcr_label == "Bearish bias" else "#9aa0a6"),
    stat_card("Market control", control_verdict, f"Buy {buy_pct:.0f}% / Sell {sell_pct:.0f}%",
              badge_bg="#1c2b20" if control_verdict == "Buyers in control" else "#2b1c1c" if control_verdict == "Sellers in control" else "#20242c",
              badge_color="#3fb950" if control_verdict == "Buyers in control" else "#f85149" if control_verdict == "Sellers in control" else "#9aa0a6"),
    stat_card("Current premium", f"₹{current_premium:.1f}"),
])

st.markdown(
    f"<div class='confluence-box' style='background:#111417;border-color:{confluence_color}55;'>"
    f"<span style='color:#7d8590;font-family:monospace;font-size:11px;text-transform:uppercase;"
    f"letter-spacing:.05em;'>Confluence</span><br><span style='color:{confluence_color};font-weight:700;"
    f"font-family:monospace;font-size:15px;'>{confluence_text}</span></div>",
    unsafe_allow_html=True,
)

stat_row([
    stat_card("🟢 Support", f"₹{sup['low']}–{sup['high']}" if sup else "—",
              f"score {sup['score']:,}" if sup else "no conviction yet",
              badge_bg="#1c2b20", badge_color="#3fb950"),
    stat_card("🔴 Resistance", f"₹{resistance['low']}–{resistance['high']}" if resistance else "—",
              f"score {resistance['score']:,}" if resistance else "no conviction yet",
              badge_bg="#2b1c1c", badge_color="#f85149"),
])

if alert_on and alerts:
    st.markdown("<div class='section-title'>⚠ Alerts</div>", unsafe_allow_html=True)
    for b, c, v in alerts[:3]:
        st.markdown(
            f"<div style='background:#1a1408;border:1px solid #4a3a0f;border-radius:8px;"
            f"padding:8px 12px;margin-bottom:6px;font-family:monospace;font-size:13px;'>"
            f"₹{b['low']}–{b['high']} · <span style='color:{c['color']};'>{c['label']}</span> "
            f"= {v:,.0f}</div>",
            unsafe_allow_html=True,
        )

# --- OI buildup chart ---
st.markdown("<div class='section-title'>OI buildup by premium range</div>", unsafe_allow_html=True)
fig = go.Figure()
for c in CATS:
    fig.add_trace(go.Bar(
        name=c["label"],
        x=[f"₹{b['low']}–{b['high']}" for b in buckets],
        y=[b[c["key"]] for b in buckets],
        marker_color=c["color"],
    ))
fig.update_layout(
    barmode="stack", template="plotly_dark",
    paper_bgcolor="#0b0e11", plot_bgcolor="#12161b",
    height=360, legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
    margin=dict(l=10, r=10, t=10, b=10),
)
fig.update_xaxes(showgrid=False)
fig.update_yaxes(showgrid=True, gridcolor="#1e222d")
st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)

# --- Legend / raw table ---
with st.expander("Show raw bucket data"):
    df = pd.DataFrame(buckets)
    st.dataframe(df, use_container_width=True)

# --- Auto refresh (live mode only) ---
if mode == "Live (Fyers)" and refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
