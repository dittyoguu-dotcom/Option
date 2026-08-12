import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel

st.set_page_config(page_title="FYERS NIFTY Option Chain", page_icon="ðŸ“ˆ", layout="wide")

APP_ID = st.secrets["FYERS_APP_ID"]
SECRET_ID = st.secrets["FYERS_SECRET_ID"]
REDIRECT_URI = st.secrets["FYERS_REDIRECT_URI"]

def create_fyers_session():
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
        session = create_fyers_session()
        session.set_token(auth_code)
        response = session.generate_token()
        if "access_token" in response:
            st.session_state["access_token"] = response["access_token"]
            st.query_params.clear()
            st.rerun()
        else:
            st.error("FYERS did not return an access token.")
            st.json(response)
    except Exception as e:
        st.error("FYERS connection failed.")
        st.exception(e)

if "access_token" not in st.session_state:
    st.title("ðŸ“ˆ FYERS Trading App")
    st.info("Connect your FYERS account to continue.")
    st.link_button("ðŸ” Connect FYERS", create_fyers_session().generate_authcode())
    st.stop()

fyers = fyersModel.FyersModel(
    token=st.session_state["access_token"],
    is_async=False,
    client_id=APP_ID,
    log_path=""
)

st.title("ðŸ“ˆ FYERS NIFTY Option Chain")
st.success("FYERS Connected âœ…")

strike_count = st.selectbox(
    "Number of strikes on each side of ATM",
    [5, 10, 15, 20],
    index=1
)

if st.button("ðŸ”„ Load NIFTY Option Chain", type="primary"):
    st.session_state["load_chain"] = True

if not st.session_state.get("load_chain"):
    st.info("Tap Load NIFTY Option Chain to request real NIFTY data from FYERS.")
    st.stop()

request_data = {
    "symbol": "NSE:NIFTY50-INDEX",
    "strikecount": strike_count,
    "timestamp": ""
}

try:
    response = fyers.optionchain(data=request_data)
except Exception as e:
    st.error("The FYERS option-chain request failed.")
    st.exception(e)
    st.stop()

if response.get("s") != "ok":
    st.error("FYERS returned an unsuccessful option-chain response.")
    st.json(response)
    st.stop()

data = response.get("data", {})
chain = data.get("optionsChain", [])

if not chain:
    st.warning("FYERS returned no option-chain rows. Try again during market hours.")
    st.json(response)
    st.stop()

underlying = next(
    (x for x in chain if x.get("symbol") == "NSE:NIFTY50-INDEX"),
    None
)

if underlying:
    c1, c2, c3 = st.columns(3)
    c1.metric("NIFTY Spot", f"â‚¹{underlying.get('ltp', 0):,.2f}")
    c2.metric("Change", f"{underlying.get('ch', 0):,.2f}")
    c3.metric("Change %", f"{underlying.get('chp', 0):,.2f}%")

rows = []
for item in chain:
    option_type = str(item.get("option_type", "")).upper()
    if option_type not in ("CE", "PE"):
        continue
    rows.append({
        "Strike": item.get("strike_price"),
        "Type": option_type,
        "LTP": item.get("ltp"),
        "OI": item.get("oi"),
        "OI Change": item.get("oich"),
        "Volume": item.get("volume"),
        "Bid": item.get("bid"),
        "Ask": item.get("ask"),
        "Symbol": item.get("symbol")
    })

if not rows:
    st.warning("No CE/PE rows were found in the FYERS response.")
    st.write("Returned keys:", list(chain[0].keys()) if chain else [])
    st.stop()

df = pd.DataFrame(rows)
df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
df = df.dropna(subset=["Strike"]).sort_values(["Strike", "Type"])

ce = df[df["Type"] == "CE"].copy().drop(columns=["Type"])
pe = df[df["Type"] == "PE"].copy().drop(columns=["Type"])

ce = ce.rename(columns={
    "LTP": "CE LTP", "OI": "CE OI", "OI Change": "CE OI Change",
    "Volume": "CE Volume", "Bid": "CE Bid", "Ask": "CE Ask", "Symbol": "CE Symbol"
})
pe = pe.rename(columns={
    "LTP": "PE LTP", "OI": "PE OI", "OI Change": "PE OI Change",
    "Volume": "PE Volume", "Bid": "PE Bid", "Ask": "PE Ask", "Symbol": "PE Symbol"
})

table = pd.merge(ce, pe, on="Strike", how="outer").sort_values("Strike")

st.subheader("Real NIFTY Option Chain")
st.caption("Data is requested directly from your connected FYERS account.")

display_cols = [
    "CE LTP", "CE OI", "CE OI Change", "CE Volume",
    "Strike",
    "PE LTP", "PE OI", "PE OI Change", "PE Volume"
]
display_cols = [c for c in display_cols if c in table.columns]

st.dataframe(table[display_cols], use_container_width=True, hide_index=True)

c1, c2 = st.columns(2)
with c1:
    st.metric("Total CE OI", f"{pd.to_numeric(table['CE OI'], errors='coerce').fillna(0).sum():,.0f}")
with c2:
    st.metric("Total PE OI", f"{pd.to_numeric(table['PE OI'], errors='coerce').fillna(0).sum():,.0f}")

st.divider()
st.subheader("Next stage")
st.write("After confirming real data, we will calculate Long Buildup, Short Covering, Short Buildup and Long Unwinding.")
