import streamlit as st
import pandas as pd
from datetime import datetime
from fyers_apiv3 import fyersModel

st.set_page_config(page_title="FYERS NIFTY Signals", page_icon="ðŸ“ˆ", layout="wide")

APP_ID = st.secrets["FYERS_APP_ID"]
SECRET_ID = st.secrets["FYERS_SECRET_ID"]
REDIRECT_URI = st.secrets["FYERS_REDIRECT_URI"]

def fyers_session():
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
        s = fyers_session()
        s.set_token(auth_code)
        result = s.generate_token()
        if "access_token" in result:
            st.session_state["access_token"] = result["access_token"]
            st.query_params.clear()
            st.rerun()
        else:
            st.error("FYERS did not return an access token.")
            st.json(result)
    except Exception as e:
        st.error("FYERS authentication failed.")
        st.exception(e)

if "access_token" not in st.session_state:
    st.title("ðŸ“ˆ FYERS NIFTY Signals")
    st.info("Connect FYERS to continue.")
    st.link_button("ðŸ” Connect FYERS", fyers_session().generate_authcode())
    st.stop()

fyers = fyersModel.FyersModel(
    token=st.session_state["access_token"],
    is_async=False,
    client_id=APP_ID,
    log_path=""
)

st.title("ðŸ“ˆ NIFTY Price + OI Signals")
st.success("FYERS Connected âœ…")

strike_count = st.selectbox("Strikes on each side of ATM", [5, 10, 15, 20], index=1)

if "previous_snapshot" not in st.session_state:
    st.session_state["previous_snapshot"] = None

def fetch_chain():
    response = fyers.optionchain(data={
        "symbol": "NSE:NIFTY50-INDEX",
        "strikecount": strike_count,
        "timestamp": ""
    })
    if response.get("s") != "ok":
        raise RuntimeError(str(response))
    return response

def make_frame(response):
    chain = response.get("data", {}).get("optionsChain", [])
    rows = []
    spot = None

    for item in chain:
        if item.get("symbol") == "NSE:NIFTY50-INDEX":
            spot = item.get("ltp")
            continue

        typ = str(item.get("option_type", "")).upper()
        if typ not in ("CE", "PE"):
            continue

        rows.append({
            "Strike": item.get("strike_price"),
            "Type": typ,
            "LTP": item.get("ltp"),
            "OI": item.get("oi"),
            "Volume": item.get("volume"),
            "Symbol": item.get("symbol")
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return spot, df

    for col in ["Strike", "LTP", "OI", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return spot, df

def classify(price_change, oi_change):
    if pd.isna(price_change) or pd.isna(oi_change):
        return "Unknown"
    if price_change > 0 and oi_change > 0:
        return "Long Buildup"
    if price_change > 0 and oi_change < 0:
        return "Short Covering"
    if price_change < 0 and oi_change > 0:
        return "Short Buildup"
    if price_change < 0 and oi_change < 0:
        return "Long Unwinding"
    return "Neutral"

st.caption(
    "Take two snapshots at different times. Signals compare price and OI "
    "between those snapshots; they are analytical labels, not trade recommendations."
)

if st.button("ðŸ“¸ Capture Snapshot", type="primary"):
    try:
        response = fetch_chain()
        spot, current = make_frame(response)

        st.session_state["previous_snapshot"] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "spot": spot,
            "chain": current
        }
        st.success(f"Snapshot captured at {st.session_state['previous_snapshot']['time']}")
    except Exception as e:
        st.error("Could not capture NIFTY option-chain snapshot.")
        st.exception(e)

previous = st.session_state["previous_snapshot"]

if previous is None:
    st.info("Capture the first snapshot. Then wait for your chosen interval and capture another snapshot.")
    st.stop()

st.write(f"**Previous snapshot:** {previous['time']}")

if st.button("ðŸ”Ž Capture New Snapshot & Calculate Signals"):
    try:
        response = fetch_chain()
        spot, current = make_frame(response)

        old = previous["chain"].copy()
        new = current.copy()

        old = old.rename(columns={"LTP": "Old LTP", "OI": "Old OI"})
        merged = new.merge(
            old[["Symbol", "Old LTP", "Old OI"]],
            on="Symbol",
            how="inner"
        )

        merged["Price Change"] = merged["LTP"] - merged["Old LTP"]
        merged["OI Change"] = merged["OI"] - merged["Old OI"]
        merged["Signal"] = merged.apply(
            lambda r: classify(r["Price Change"], r["OI Change"]), axis=1
        )

        bullish = merged["Signal"].isin(["Long Buildup", "Short Covering"]).sum()
        bearish = merged["Signal"].isin(["Short Buildup", "Long Unwinding"]).sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("NIFTY Spot", f"â‚¹{spot:,.2f}" if spot is not None else "â€”")
        c2.metric("Bullish Contracts", int(bullish))
        c3.metric("Bearish Contracts", int(bearish))

        st.subheader("Signal Summary")

        summary = (
            merged.groupby("Signal")
            .size()
            .reindex(
                ["Long Buildup", "Short Covering", "Short Buildup", "Long Unwinding", "Neutral", "Unknown"],
                fill_value=0
            )
            .rename("Contracts")
            .reset_index()
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)

        st.subheader("Strike-Level Signals")
        cols = [
            "Strike", "Type", "LTP", "Old LTP", "Price Change",
            "OI", "Old OI", "OI Change", "Signal"
        ]
        st.dataframe(
            merged[[c for c in cols if c in merged.columns]]
            .sort_values(["Strike", "Type"]),
            use_container_width=True,
            hide_index=True
        )

        # Keep the new snapshot for the next comparison.
        st.session_state["previous_snapshot"] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "spot": spot,
            "chain": current
        }

    except Exception as e:
        st.error("Could not compare the snapshots.")
        st.exception(e)

st.divider()
st.subheader("How we group the signals")
st.write("ðŸŸ¢ Bullish = Long Buildup + Short Covering")
st.write("ðŸ”´ Bearish = Short Buildup + Long Unwinding")
st.caption(
    "This first version uses two captured snapshots. The next version can add "
    "automatic refresh/storage and feed the results into the full dashboard."
)
