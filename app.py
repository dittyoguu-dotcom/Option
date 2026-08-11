import streamlit as st

st.set_page_config(
    page_title="FYERS Trading App",
    page_icon="📈",
    layout="wide"
)

st.title("📈 FYERS Trading App")

st.subheader("Price & Open Interest Analysis")

st.info(
    "Our trading dashboard will be connected to FYERS API in the next step."
)

col1, col2 = st.columns(2)

with col1:
    st.metric("Price", "--")

with col2:
    st.metric("Open Interest", "--")

st.divider()

st.subheader("Market Signal")

st.write("Waiting for FYERS market data...")

st.divider()

st.caption("Long Buildup + Short Covering = Bullish")
st.caption("Short Buildup + Long Unwinding = Bearish")
