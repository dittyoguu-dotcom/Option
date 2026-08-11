import streamlit as st
from fyers_apiv3 import fyersModel

st.set_page_config(page_title="FYERS Trading App", page_icon="ðŸ“ˆ", layout="wide")

st.title("ðŸ“ˆ FYERS Trading App")
st.subheader("FYERS Connection")

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

query_params = st.query_params
auth_code = query_params.get("auth_code")

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

if "access_token" in st.session_state:
    st.success("FYERS Connected âœ…")

    try:
        fyers = fyersModel.FyersModel(
            token=st.session_state["access_token"],
            is_async=False,
            client_id=APP_ID,
            log_path=""
        )

        profile = fyers.get_profile()

        if profile.get("s") == "ok":
            st.success("FYERS account verified successfully.")
            st.write("Your FYERS API connection is working.")
        else:
            st.warning("Token was received, but FYERS profile verification returned:")
            st.json(profile)

    except Exception as e:
        st.error("Token was received, but the FYERS API test failed.")
        st.exception(e)
else:
    st.info("Your FYERS account is not connected yet.")

    session = create_fyers_session()
    login_url = session.generate_authcode()
    st.link_button("ðŸ” Connect FYERS", login_url)

st.divider()
st.caption("Next: after the connection works, we will fetch market data.")
