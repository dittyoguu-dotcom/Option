import streamlit as st
import pandas as pd
import numpy as np
from fyers_apiv3 import fyersModel

st.set_page_config(
    page_title="NIFTY OI Confluence Dashboard",
    page_icon="ðŸ“Š",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- FYERS authentication ----------
APP_ID = st.secrets["FYERS_APP_ID"]
SECRET_ID = st.secrets["FYERS_SECRET_ID"]
REDIRECT_URI = st.secrets["FYERS_REDIRECT_URI"]

def make_session():
    return fyersModel.SessionModel(
        client_id=APP_ID,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        state="streamlit",
        secret_key=SECRET_ID,
        grant_type="authorization_code",
    )

auth_code = st.query_params.get("auth_code")
if auth_code and "access_token" not in st.session_state:
    try:
        s = make_session()
        s.set_token(auth_code)
        result = s.generate_token()
        if "access_token" in result:
            st.session_state["access_token"] = result["access_token"]
            st.query_params.clear()
            st.rerun()
        else:
            st.error("FYERS authentication failed.")
            st.json(result)
    except Exception as e:
        st.error("FYERS authentication failed.")
        st.exception(e)

if "access_token" not in st.session_state:
    st.title("NIFTY OI Confluence Dashboard")
    st.info("Connect your FYERS account to start the live dashboard.")
    st.link_button("ðŸ” Connect FYERS", make_session().generate_authcode())
    st.stop()

fyers = fyersModel.FyersModel(
    token=st.session_state["access_token"],
    is_async=False,
    client_id=APP_ID,
    log_path="",
)

# ---------- Styling ----------
st.markdown("""
<style>
.stApp { background:#0b0e11; color:#e7e9ea; }
.block-container { max-width:1100px; padding-top:1.4rem; }
div[data-testid="stMetric"] {
    background:#111417; border:1px solid #1e2227;
    border-radius:10px; padding:12px 16px;
}
div[data-testid="stMetricLabel"] { color:#6b7280; }
div[data-testid="stMetricValue"] { color:#e7e9ea; }
.dashboard-card {
    background:#111417; border:1px solid #1e2227;
    border-radius:10px; padding:14px 16px; margin-bottom:12px;
}
.small-label { color:#6b7280; font-size:11px; letter-spacing:.05em; }
.bull { color:#3fb950; }
.bear { color:#f85149; }
.neutral { color:#9aa0a6; }
</style>
""", unsafe_allow_html=True)

# ---------- Fetch ----------
@st.cache_data(ttl=20, show_spinner=False)
def get_chain(strikecount):
    return fyers.optionchain(data={
        "symbol": "NSE:NIFTY50-INDEX",
        "strikecount": int(strikecount),
        "timestamp": ""
    })

with st.sidebar:
    st.header("Dashboard Controls")
    strikecount = st.selectbox("Strikes around ATM", [5, 10, 15, 20], index=1)
    bucket_size = st.selectbox("Premium bucket", [5, 10, 20], index=1)
    alert_threshold = st.number_input(
        "Alert threshold (OI contracts)",
        min_value=0,
        value=50000,
        step=5000
    )
    st.caption("Data-only dashboard. No orders are placed.")
    if st.button("ðŸ”„ Refresh data"):
        st.cache_data.clear()
        st.rerun()

try:
    response = get_chain(strikecount)
except Exception as e:
    st.error("Could not load the FYERS option chain.")
    st.exception(e)
    st.stop()

if response.get("s") != "ok":
    st.error("FYERS returned an unsuccessful option-chain response.")
    st.json(response)
    st.stop()

data = response.get("data", {})
chain = data.get("optionsChain", [])
if not chain:
    st.warning("No option-chain data was returned. Try refreshing during market hours.")
    st.stop()

# ---------- Normalize ----------
spot_row = next((x for x in chain if x.get("symbol") == "NSE:NIFTY50-INDEX"), None)
spot = float(spot_row.get("ltp", 0)) if spot_row and spot_row.get("ltp") is not None else np.nan
spot_change = float(spot_row.get("ch", 0)) if spot_row and spot_row.get("ch") is not None else 0.0
spot_change_pct = float(spot_row.get("chp", 0)) if spot_row and spot_row.get("chp") is not None else 0.0

rows = []
for x in chain:
    typ = str(x.get("option_type", "")).upper()
    if typ not in ("CE", "PE"):
        continue
    rows.append({
        "symbol": x.get("symbol"),
        "strike": pd.to_numeric(x.get("strike_price"), errors="coerce"),
        "type": typ,
        "ltp": pd.to_numeric(x.get("ltp"), errors="coerce"),
        "price_change": pd.to_numeric(x.get("ch"), errors="coerce"),
        "oi": pd.to_numeric(x.get("oi"), errors="coerce"),
        "oi_change": pd.to_numeric(x.get("oich"), errors="coerce"),
        "volume": pd.to_numeric(x.get("volume"), errors="coerce"),
        "bid": pd.to_numeric(x.get("bid"), errors="coerce"),
        "ask": pd.to_numeric(x.get("ask"), errors="coerce"),
    })

df = pd.DataFrame(rows).dropna(subset=["strike", "ltp"])
if df.empty:
    st.error("FYERS returned option rows, but no usable CE/PE rows were found.")
    st.stop()

for c in ["price_change", "oi", "oi_change", "volume", "bid", "ask"]:
    df[c] = df[c].fillna(0)

# ---------- Classify ----------
def classify(row):
    p = row["price_change"]
    o = row["oi_change"]
    if p > 0 and o > 0:
        return "Long Buildup"
    if p > 0 and o < 0:
        return "Short Covering"
    if p < 0 and o > 0:
        return "Short Buildup"
    if p < 0 and o < 0:
        return "Long Unwinding"
    return "Neutral"

df["signal"] = df.apply(classify, axis=1)
df["bullish"] = np.where(
    df["signal"].isin(["Long Buildup", "Short Covering"]),
    df["oi_change"].abs(), 0
)
df["bearish"] = np.where(
    df["signal"].isin(["Short Buildup", "Long Unwinding"]),
    df["oi_change"].abs(), 0
)

# ---------- Current strike ----------
strikes = sorted(df["strike"].dropna().unique().tolist())
atm = min(strikes, key=lambda x: abs(x - spot)) if np.isfinite(spot) else strikes[len(strikes)//2]

if "selected_strike" not in st.session_state or st.session_state["selected_strike"] not in strikes:
    st.session_state["selected_strike"] = atm

selected_strike = st.selectbox(
    "STRIKE",
    strikes,
    index=strikes.index(st.session_state["selected_strike"]),
    format_func=lambda x: f"{int(x)} {'(ATM)' if x == atm else ''}"
)
st.session_state["selected_strike"] = selected_strike

opt_type = st.radio("TYPE", ["CE", "PE"], horizontal=True, format_func=lambda x: "CALL" if x == "CE" else "PUT")

selected = df[(df["strike"] == selected_strike) & (df["type"] == opt_type)]
selected_row = selected.iloc[0] if not selected.empty else None
ce = df[(df["strike"] == selected_strike) & (df["type"] == "CE")]
pe = df[(df["strike"] == selected_strike) & (df["type"] == "PE")]

ce_oi = float(ce.iloc[0]["oi"]) if not ce.empty else 0
pe_oi = float(pe.iloc[0]["oi"]) if not pe.empty else 0
pcr = pe_oi / ce_oi if ce_oi else np.nan
pcr_label = "Bullish bias" if pcr >= 1.2 else "Bearish bias" if pcr <= 0.8 else "Neutral"

# ---------- Bucket by option premium ----------
work = df.copy()
work["bucket_low"] = np.floor((work["ltp"] - 1) / bucket_size) * bucket_size + 1
work["bucket_high"] = work["bucket_low"] + bucket_size - 1

def sum_abs(series):
    return float(series.abs().sum())

buckets = work.groupby(["bucket_low", "bucket_high"], as_index=False).agg(
    longBuild=("bullish", lambda s: 0.0),
    shortBuild=("bearish", lambda s: 0.0),
    volume=("volume", "sum"),
    oiAbs=("oi_change", sum_abs),
)

# Calculate categories by group without losing sign/category.
cat = work.groupby(["bucket_low", "bucket_high", "signal"])["oi_change"].apply(lambda s: float(s.abs().sum())).unstack(fill_value=0).reset_index()
for col in ["Long Buildup", "Short Buildup", "Short Covering", "Long Unwinding"]:
    if col not in cat.columns:
        cat[col] = 0.0

buckets = cat.rename(columns={
    "Long Buildup": "longBuild",
    "Short Buildup": "shortBuild",
    "Short Covering": "shortCover",
    "Long Unwinding": "longUnwind",
})

vol = work.groupby(["bucket_low", "bucket_high"], as_index=False).agg(
    volume=("volume", "sum"),
    oiAbs=("oi_change", lambda s: float(s.abs().sum()))
)
buckets = buckets.merge(vol, on=["bucket_low", "bucket_high"], how="left")
buckets["bullish"] = buckets["longBuild"] + buckets["shortCover"]
buckets["bearish"] = buckets["shortBuild"] + buckets["longUnwind"]
buckets["total"] = buckets["bullish"] + buckets["bearish"]

# ---------- Market control ----------
buy = float(buckets["bullish"].sum())
sell = float(buckets["bearish"].sum())
total = buy + sell
buy_pct = buy / total * 100 if total else 50
sell_pct = 100 - buy_pct
verdict = "Buyers in control" if buy_pct >= 60 else "Sellers in control" if sell_pct >= 60 else "Balanced"
verdict_class = "bull" if verdict == "Buyers in control" else "bear" if verdict == "Sellers in control" else "neutral"

# ---------- Support / resistance ----------
current_premium = float(selected_row["ltp"]) if selected_row is not None else float(df["ltp"].median())

below = buckets[(buckets["bucket_low"] + buckets["bucket_high"]) / 2 < current_premium]
above = buckets[(buckets["bucket_low"] + buckets["bucket_high"]) / 2 > current_premium]

support = below.loc[below["bullish"].idxmax()] if not below.empty and below["bullish"].max() > 0 else None
resistance = above.loc[above["bearish"].idxmax()] if not above.empty and above["bearish"].max() > 0 else None

def zone_pct(frame):
    b = float(frame["bullish"].sum()) if not frame.empty else 0
    s = float(frame["bearish"].sum()) if not frame.empty else 0
    t = b + s
    return (b / t * 100 if t else 50), (s / t * 100 if t else 50)

below_buy, below_sell = zone_pct(below)
above_buy, above_sell = zone_pct(above)

# ---------- Confluence ----------
signals = []
signals.append(("Market Control", "bull" if verdict == "Buyers in control" else "bear" if verdict == "Sellers in control" else "neutral"))
signals.append(("PCR", "bull" if pcr_label == "Bullish bias" else "bear" if pcr_label == "Bearish bias" else "neutral"))
if support is not None and resistance is not None:
    signals.append(("Zone strength", "bull" if support["bullish"] > resistance["bearish"] else "bear"))
elif support is not None:
    signals.append(("Zone strength", "bull"))
elif resistance is not None:
    signals.append(("Zone strength", "bear"))
else:
    signals.append(("Zone strength", "neutral"))

bulls = sum(1 for _, b in signals if b == "bull")
bears = sum(1 for _, b in signals if b == "bear")
if bulls >= 2 and bears == 0:
    confluence = "Aligned â€” bullish confluence"
    confluence_class = "bull"
elif bears >= 2 and bulls == 0:
    confluence = "Aligned â€” bearish confluence"
    confluence_class = "bear"
else:
    confluence = "Mixed signals â€” proceed with caution"
    confluence_class = "neutral"

# ---------- Header ----------
st.markdown("## NIFTY OI CONFLUENCE DASHBOARD")
st.caption("Live NIFTY option-chain analysis powered by your FYERS connection.")

m1, m2, m3 = st.columns(3)
m1.metric("NIFTY SPOT", f"â‚¹{spot:,.2f}" if np.isfinite(spot) else "â€”", f"{spot_change:+.2f} ({spot_change_pct:+.2f}%)")
m2.metric(f"PCR Â· {int(selected_strike)} STRIKE", f"{pcr:.2f}" if np.isfinite(pcr) else "â€”", pcr_label)
m3.metric("MARKET CONTROL", verdict, f"Buyers {buy_pct:.0f}% Â· Sellers {sell_pct:.0f}%")

st.progress(int(round(max(0, min(100, buy_pct)))))

st.markdown(f"### NIFTY {int(selected_strike)} {opt_type}")
st.caption("OI BUILDUP BY PREMIUM RANGE Â· Current FYERS option-chain snapshot")

# ---------- Alerts ----------
alerts = []
for _, b in buckets.iterrows():
    for key, label in [
        ("longBuild", "Long buildup"),
        ("shortBuild", "Short buildup"),
        ("shortCover", "Short covering"),
        ("longUnwind", "Long unwinding"),
    ]:
        if b[key] >= alert_threshold:
            alerts.append((b["bucket_low"], b["bucket_high"], label, b[key]))
alerts.sort(key=lambda x: x[3], reverse=True)

if alerts:
    st.warning(
        f"âš  {len(alerts)} level(s) crossed the OI threshold. "
        + " Â· ".join(f"â‚¹{int(a)}â€“{int(b)} {c}={int(v):,}" for a,b,c,v in alerts[:3])
    )

# ---------- Support / resistance ----------
c1, c2 = st.columns(2)
with c1:
    if support is not None:
        st.success(f"SUPPORT  â‚¹{int(support['bucket_low'])}â€“{int(support['bucket_high'])}  Â· Bullish OI {int(support['bullish']):,}")
    else:
        st.info("SUPPORT Â· No conviction below current premium")
with c2:
    if resistance is not None:
        st.error(f"RESISTANCE  â‚¹{int(resistance['bucket_low'])}â€“{int(resistance['bucket_high'])}  Â· Bearish OI {int(resistance['bearish']):,}")
    else:
        st.info("RESISTANCE Â· No conviction above current premium")

# ---------- Confluence ----------
st.markdown(f"### CONFLUENCE Â· :{confluence_class}[{confluence}]")
st.write(" Â· ".join(f"{name}: {bias.title()}" for name, bias in signals))

# ---------- Zone control ----------
z1, z2 = st.columns(2)
with z1:
    st.markdown(f"**BELOW â‚¹{current_premium:.0f} Â· support side**")
    st.progress(int(round(below_buy)))
    st.caption(f"Buyers {below_buy:.0f}% Â· Sellers {below_sell:.0f}%")
with z2:
    st.markdown(f"**ABOVE â‚¹{current_premium:.0f} Â· resistance side**")
    st.progress(int(round(above_buy)))
    st.caption(f"Buyers {above_buy:.0f}% Â· Sellers {above_sell:.0f}%")

# ---------- OI buildup chart ----------
st.markdown("### OI BUILDUP BY PREMIUM RANGE")

chart = buckets[["bucket_low", "bucket_high", "longBuild", "shortBuild", "shortCover", "longUnwind"]].copy()
chart["Range"] = chart.apply(lambda r: f"â‚¹{int(r.bucket_low)}â€“{int(r.bucket_high)}", axis=1)
chart = chart.set_index("Range")[["longBuild", "shortBuild", "shortCover", "longUnwind"]]
chart.columns = ["Long Buildup", "Short Buildup", "Short Covering", "Long Unwinding"]
st.bar_chart(chart, height=420)

# ---------- Live table ----------
st.markdown("### LIVE OPTION CHAIN")
chain_view = df.pivot_table(
    index="strike",
    columns="type",
    values=["ltp", "price_change", "oi", "oi_change", "volume"],
    aggfunc="first"
).sort_index()

st.dataframe(chain_view, use_container_width=True)

# ---------- Signal details ----------
st.markdown("### SIGNAL BREAKDOWN")
signal_table = (
    df.groupby("signal")
      .agg(Contracts=("symbol", "count"), OI_Change=("oi_change", lambda s: float(s.abs().sum())))
      .reindex(["Long Buildup", "Short Covering", "Short Buildup", "Long Unwinding", "Neutral"], fill_value=0)
      .reset_index()
)
st.dataframe(signal_table, use_container_width=True, hide_index=True)

st.caption(
    "Signal classification uses the FYERS option-chain price change and OI change fields. "
    "The original uploaded dashboard used tick-to-tick premium/OI changes; this live version "
    "uses the fields actually returned by the FYERS option-chain snapshot."
)
