# FYERS NIFTY Price + OI Signals

This version compares two real NIFTY option-chain snapshots from FYERS.

Signals:
- Price up + OI up = Long Buildup
- Price up + OI down = Short Covering
- Price down + OI up = Short Buildup
- Price down + OI down = Long Unwinding

Bullish group:
- Long Buildup
- Short Covering

Bearish group:
- Short Buildup
- Long Unwinding

This is an analytical tool, not a trade recommendation.

Keep FYERS credentials in Streamlit Secrets and never commit them to GitHub.
