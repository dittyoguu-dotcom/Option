
import streamlit as st
import pandas as pd
import numpy as np
from fyers_apiv3 import fyersModel

st.set_page_config(page_title="NIFTY OI Confluence",page_icon="ðŸ“Š",layout="wide")

APP_ID=st.secrets["FYERS_APP_ID"]
SECRET_ID=st.secrets["FYERS_SECRET_ID"]
REDIRECT_URI=st.secrets["FYERS_REDIRECT_URI"]

def session():
    return fyersModel.SessionModel(client_id=APP_ID,redirect_uri=REDIRECT_URI,
        response_type="code",state="streamlit",secret_key=SECRET_ID,
        grant_type="authorization_code")

code=st.query_params.get("auth_code")
if code and "access_token" not in st.session_state:
    try:
        s=session(); s.set_token(code); r=s.generate_token()
        if "access_token" in r:
            st.session_state.access_token=r["access_token"]; st.query_params.clear(); st.rerun()
        else: st.error("FYERS authentication failed."); st.json(r)
    except Exception as e: st.error("FYERS authentication failed."); st.exception(e)

if "access_token" not in st.session_state:
    st.title("NIFTY OI CONFLUENCE DASHBOARD")
    st.info("Connect your FYERS account to start.")
    st.link_button("ðŸ” Connect FYERS",session().generate_authcode()); st.stop()

fyers=fyersModel.FyersModel(token=st.session_state.access_token,is_async=False,
    client_id=APP_ID,log_path="")

st.markdown("""<style>
.stApp{background:#0b0e11;color:#e7e9ea}.block-container{max-width:1180px;padding-top:1rem}
div[data-testid="stMetric"]{background:#111417;border:1px solid #252a31;border-radius:10px;padding:12px}
</style>""",unsafe_allow_html=True)

def n(x,default=0.0):
    try:return default if x is None or x=="" else float(x)
    except:return default

def chain():
    return fyers.optionchain({"symbol":"NSE:NIFTY50-INDEX","strikecount":strikecount,"timestamp":""})

def parse_chain(r):
    rows=[]; spot=np.nan
    for x in r.get("data",{}).get("optionsChain",[]):
        if x.get("symbol")=="NSE:NIFTY50-INDEX":
            spot=n(x.get("ltp"),np.nan); continue
        typ=str(x.get("option_type","")).upper()
        if typ in ("CE","PE"):
            rows.append({"symbol":x.get("symbol"),"strike":n(x.get("strike_price"),np.nan),
                "type":typ,"ltp":n(x.get("ltp"),np.nan),"oi":n(x.get("oi")),
                "oi_change":n(x.get("oich")),"volume":n(x.get("volume"))})
    return spot,pd.DataFrame(rows)

def parse_quotes(r):
    out={}
    for x in r.get("d",[]) if isinstance(r.get("d",[]),list) else []:
        if not isinstance(x,dict): continue
        sym=x.get("n") or x.get("symbol"); v=x.get("v",x.get("data",{}))
        if sym and isinstance(v,dict):
            out[sym]={"ltp":n(v.get("lp",v.get("ltp")),np.nan),
                      "ch":n(v.get("ch",v.get("change"))),
                      "chp":n(v.get("chp",v.get("change_pct")))}
    return out

def quotes(symbols):
    out={}
    for i in range(0,len(symbols),50):
        try: out.update(parse_quotes(fyers.quotes({"symbols":",".join(symbols[i:i+50])})))
        except: pass
    return out

def signal(p,o):
    if p>0 and o>0:return "Long Buildup"
    if p<0 and o>0:return "Short Buildup"
    if p>0 and o<0:return "Short Covering"
    if p<0 and o<0:return "Long Unwinding"
    return "Neutral"

with st.sidebar:
    strikecount=st.selectbox("Strikes around ATM",[5,10,15,20],index=1)
    threshold=st.number_input("OI-change alert threshold",0,10000000,50000,5000)
    if st.button("ðŸ”„ Refresh",use_container_width=True): st.cache_data.clear(); st.rerun()

try:r=chain()
except Exception as e:st.error("Could not load FYERS option chain.");st.exception(e);st.stop()
if r.get("s")!="ok":st.error("FYERS returned an unsuccessful response.");st.json(r);st.stop()

spot,df=parse_chain(r)
if df.empty:st.warning("No NIFTY option data returned.");st.stop()

q=quotes(df.symbol.dropna().tolist())
df["price_change"]=df.symbol.map(lambda s:q.get(s,{}).get("ch",0.0))
df["price_change_pct"]=df.symbol.map(lambda s:q.get(s,{}).get("chp",0.0))
df["quote_ltp"]=df.symbol.map(lambda s:q.get(s,{}).get("ltp",np.nan))
df["ltp"]=df["quote_ltp"].where(df.quote_ltp.notna(),df.ltp)
df["signal"]=[signal(p,o) for p,o in zip(df.price_change,df.oi_change)]
df["bullish_oi"]=np.where(df.signal.isin(["Long Buildup","Short Covering"]),df.oi_change.abs(),0)
df["bearish_oi"]=np.where(df.signal.isin(["Short Buildup","Long Unwinding"]),df.oi_change.abs(),0)

try:
    sq=parse_quotes(fyers.quotes({"symbols":"NSE:NIFTY50-INDEX"})).get("NSE:NIFTY50-INDEX",{})
    spot=n(sq.get("ltp"),spot); spot_ch=n(sq.get("ch")); spot_chp=n(sq.get("chp"))
except:
    spot_ch=spot_chp=0.0

strikes=sorted(df.strike.dropna().unique())
atm=min(strikes,key=lambda x:abs(x-spot))
ceoi=df.loc[df.type=="CE","oi"].sum(); peoi=df.loc[df.type=="PE","oi"].sum()
pcr=peoi/ceoi if ceoi else np.nan
pcr_label="Bullish bias" if pcr>=1.2 else "Bearish bias" if pcr<=.8 else "Neutral"

buy=float(df.bullish_oi.sum()); sell=float(df.bearish_oi.sum()); total=buy+sell
bp=buy/total*100 if total else 50; sp=100-bp
control="Buyers in control" if bp>=60 else "Sellers in control" if sp>=60 else "Balanced"

# Strike-level table
p=df.pivot_table(index="strike",columns="type",values=["ltp","price_change","oi","oi_change","volume","signal"],aggfunc="first")
p.columns=[f"{a}_{b}" for a,b in p.columns];p=p.reset_index().sort_values("strike")
for c in ["ltp_CE","price_change_CE","oi_CE","oi_change_CE","volume_CE","signal_CE",
          "ltp_PE","price_change_PE","oi_PE","oi_change_PE","volume_PE","signal_PE"]:
    if c not in p:p[c]=np.nan

# Classic strike-based zones
pe=df[df.type=="PE"].copy(); ce=df[df.type=="CE"].copy()
pc=pe[pe.strike<=atm].copy(); rc=ce[ce.strike>=atm].copy()
support=pc.loc[(pc.oi+pc.oi_change.abs()*.5).idxmax()] if not pc.empty else None
resistance=rc.loc[(rc.oi+rc.oi_change.abs()*.5).idxmax()] if not rc.empty else None

zone="bull" if support is not None and resistance is not None and abs(support.oi_change)>abs(resistance.oi_change) else "bear" if resistance is not None else "neutral"
mb="bull" if control=="Buyers in control" else "bear" if control=="Sellers in control" else "neutral"
pb="bull" if pcr_label=="Bullish bias" else "bear" if pcr_label=="Bearish bias" else "neutral"
bulls=sum(x=="bull" for x in [mb,pb,zone]);bears=sum(x=="bear" for x in [mb,pb,zone])
confluence="Aligned â€” bullish confluence" if bulls>=2 and bears==0 else "Aligned â€” bearish confluence" if bears>=2 and bulls==0 else "Mixed signals"

st.markdown("## NIFTY OI CONFLUENCE DASHBOARD")
st.caption("Real NIFTY option-chain data from your FYERS connection.")
a,b,c=st.columns(3)
a.metric("NIFTY SPOT",f"â‚¹{spot:,.2f}",f"{spot_ch:+.2f} ({spot_chp:+.2f}%)")
b.metric("OVERALL PCR",f"{pcr:.2f}",pcr_label)
c.metric("MARKET CONTROL",control,f"Buyers {bp:.0f}% Â· Sellers {sp:.0f}%")
st.progress(int(max(0,min(100,bp))))

selected=st.selectbox("STRIKE",strikes,index=strikes.index(atm),format_func=lambda x:f"{int(x)}  â† ATM" if x==atm else str(int(x)))
otype=st.radio("TYPE",["CE","PE"],horizontal=True,format_func=lambda x:"CALL" if x=="CE" else "PUT")
row=df[(df.strike==selected)&(df.type==otype)].iloc[0]
st.markdown(f"### NIFTY {int(selected)} {'CALL' if otype=='CE' else 'PUT'}")
x1,x2,x3,x4=st.columns(4)
x1.metric("LTP",f"â‚¹{row.ltp:,.2f}");x2.metric("PRICE CHANGE",f"{row.price_change:+.2f}")
x3.metric("OI",f"{row.oi:,.0f}");x4.metric("OI CHANGE",f"{row.oi_change:+,.0f}")

st.markdown("### OI BUILDUP")
cols=st.columns(4)
for col,label,sub in zip(cols,["Long Buildup","Short Covering","Short Buildup","Long Unwinding"],
                         ["Price â†‘ + OI â†‘","Price â†‘ + OI â†“","Price â†“ + OI â†‘","Price â†“ + OI â†“"]):
    val=df.loc[df.signal==label,"oi_change"].abs().sum()
    col.metric(label,f"{val:,.0f}");col.caption(sub)

u,v=st.columns(2)
u.success(f"ðŸŸ¢ BULLISH PRESSURE\n\nLong Buildup + Short Covering Â· {buy:,.0f} OI")
v.error(f"ðŸ”´ BEARISH PRESSURE\n\nShort Buildup + Long Unwinding Â· {sell:,.0f} OI")

st.markdown("### SUPPORT & RESISTANCE")
u,v=st.columns(2)
if support is not None:u.success(f"SUPPORT Â· {int(support.strike):,}\n\nPE OI {support.oi:,.0f} Â· OI Chg {support.oi_change:+,.0f}")
else:u.info("SUPPORT Â· Not available")
if resistance is not None:v.error(f"RESISTANCE Â· {int(resistance.strike):,}\n\nCE OI {resistance.oi:,.0f} Â· OI Chg {resistance.oi_change:+,.0f}")
else:v.info("RESISTANCE Â· Not available")

st.markdown("### CONFLUENCE")
st.success(confluence) if confluence.startswith("Aligned â€” bullish") else st.error(confluence) if confluence.startswith("Aligned â€” bearish") else st.info(confluence)
st.caption(f"Market Control: {'Bullish' if mb=='bull' else 'Bearish' if mb=='bear' else 'Neutral'} Â· PCR: {'Bullish' if pb=='bull' else 'Bearish' if pb=='bear' else 'Neutral'} Â· Zones: {'Bullish' if zone=='bull' else 'Bearish' if zone=='bear' else 'Neutral'}")

st.markdown("### OI BUILDUP BY STRIKE")
chart=df.groupby(["strike","signal"])["oi_change"].apply(lambda s:float(s.abs().sum())).unstack(fill_value=0)
for c in ["Long Buildup","Short Covering","Short Buildup","Long Unwinding"]:
    if c not in chart:chart[c]=0
st.bar_chart(chart[["Long Buildup","Short Covering","Short Buildup","Long Unwinding"]],height=380)

alerts=df[df.oi_change.abs()>=threshold]
if not alerts.empty:st.warning(f"âš  {len(alerts)} contract(s) crossed the OI-change alert threshold.")

st.markdown("### LIVE NIFTY OPTION CHAIN")
view=p[["strike","ltp_CE","oi_CE","oi_change_CE","price_change_CE","volume_CE","signal_CE",
        "ltp_PE","oi_PE","oi_change_PE","price_change_PE","volume_PE","signal_PE"]].rename(columns={
"strike":"STRIKE","ltp_CE":"CE LTP","oi_CE":"CE OI","oi_change_CE":"CE OI Chg","price_change_CE":"CE Price Chg","volume_CE":"CE Volume","signal_CE":"CE Signal",
"ltp_PE":"PE LTP","oi_PE":"PE OI","oi_change_PE":"PE OI Chg","price_change_PE":"PE Price Chg","volume_PE":"PE Volume","signal_PE":"PE Signal"})
view["distance"]=(view.STRIKE-atm).abs()
st.dataframe(view.sort_values(["distance","STRIKE"]).drop(columns="distance").head(15),use_container_width=True,hide_index=True)
with st.expander("Show all strikes"):st.dataframe(view.drop(columns="distance"),use_container_width=True,hide_index=True)

st.caption("OI Chg is FYERS' change in open interest from the previous trading session. Price change comes from FYERS Quotes API; the two are combined for the four-way signal.")
