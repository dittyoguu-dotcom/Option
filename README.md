# NIFTY OI Confluence Dashboard

This is the live Streamlit version of the uploaded OI Confluence dashboard.

It connects directly to the existing FYERS API session and uses the real NIFTY option chain.

Dashboard features:
- NIFTY spot
- Strike selector
- CE/PE selector
- PCR
- Market Control
- Bullish: Long Buildup + Short Covering
- Bearish: Short Buildup + Long Unwinding
- Support / Resistance zones
- Confluence
- OI buildup by premium range
- Alert threshold
- Live option-chain table
- Signal breakdown

The uploaded React dashboard's mock data has been removed.

Important:
The original dashboard classified each mock tick using tick-to-tick premium and OI direction. The live FYERS option-chain endpoint provides LTP and OI/OI-change fields, so this first live dashboard classifies using those returned fields.

No order placement is included.

Keep FYERS credentials only in Streamlit Secrets.
