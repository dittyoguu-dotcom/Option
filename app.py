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
import streamlit as st

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="NIFTY OI Confluence Dashboard", layout="wide", page_icon="📈")

DARK_CSS = """
<style>
.stApp { background-color: #0b0e11; color: #e7e9ea; }
[data-testid="stMetricValue"] { font-family: monospace; }
</style>
"""
st.markdown(DARK_CSS, unsafe_allow_html=True)

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
    expiries, raw = fetch_expiries(fyers)
    if not expiries:
        st.error(f"Couldn't load expiries from Fyers: {raw}")
        st.stop()
    expiry_labels = [e["date"] for e in expiries]
    expiry_choice = st.sidebar.selectbox("Expiry", expiry_labels)
    expiry_ts = str(expiries[expiry_labels.index(expiry_choice)]["expiry"])
else:
    fyers = None
    expiry_ts = ""

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
st.markdown(f"### NIFTY {strike} {opt_type} &nbsp;·&nbsp; {mode}")
st.caption(f"Spot ref ₹{spot:,.2f}" if spot else "")

top1, top2, top3 = st.columns(3)
top1.metric("PCR (same strike)", f"{pcr:.2f}", pcr_label)
top2.metric("Market Control", control_verdict, f"Buy {buy_pct:.0f}% / Sell {sell_pct:.0f}%")
top3.metric("Current premium", f"₹{current_premium:.1f}")

st.markdown(
    f"<div style='background:#111417;border:1px solid {confluence_color}55;border-radius:10px;"
    f"padding:12px 16px;margin:10px 0;'><span style='color:#4b5158;font-family:monospace;"
    f"font-size:11px;'>CONFLUENCE</span><br><span style='color:{confluence_color};font-weight:700;"
    f"font-family:monospace;font-size:15px;'>{confluence_text}</span></div>",
    unsafe_allow_html=True,
)

sc1, sc2 = st.columns(2)
with sc1:
    st.markdown("**🟢 Support**")
    if sup:
        st.write(f"₹{sup['low']}–{sup['high']} · score {sup['score']:,}")
    else:
        st.caption("No conviction below current premium yet")
with sc2:
    st.markdown("**🔴 Resistance**")
    if resistance:
        st.write(f"₹{resistance['low']}–{resistance['high']} · score {resistance['score']:,}")
    else:
        st.caption("No conviction above current premium yet")

if alert_on and alerts:
    st.warning(f"⚠ {len(alerts)} level(s) crossed your threshold")
    for b, c, v in alerts[:3]:
        st.caption(f"₹{b['low']}–{b['high']} · {c['label']} = {v:,.0f}")

# --- Chart ---
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
    paper_bgcolor="#0b0e11", plot_bgcolor="#111417",
    height=380, legend=dict(orientation="h", y=1.1),
    margin=dict(l=10, r=10, t=10, b=10),
)
st.plotly_chart(fig, use_container_width=True)

# --- Legend / raw table ---
with st.expander("Show raw bucket data"):
    df = pd.DataFrame(buckets)
    st.dataframe(df, use_container_width=True)

# --- Auto refresh (live mode only) ---
if mode == "Live (Fyers)" and refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
