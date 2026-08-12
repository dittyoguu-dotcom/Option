# Corrected NIFTY OI Confluence Dashboard

Uses real FYERS NIFTY option-chain OI/OI-change data plus FYERS Quotes API price changes.

Signal logic:
- Price up + OI up = Long Buildup
- Price up + OI down = Short Covering
- Price down + OI up = Short Buildup
- Price down + OI down = Long Unwinding

PCR is total PE OI / total CE OI.
Support is the strongest PE-OI zone at/below ATM.
Resistance is the strongest CE-OI zone at/above ATM.

No order placement. Keep FYERS credentials in Streamlit Secrets.
