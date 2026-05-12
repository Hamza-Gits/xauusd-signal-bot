"""One-off verification: list accounts, fetch balance, get GBP/USD and XAU/USD prices.

Run: python verify_oanda.py
Does NOT place any orders.
"""
import os
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

API_KEY = os.environ.get("OANDA_API_KEY") or sys.argv[1] if len(sys.argv) > 1 else None
if not API_KEY:
    print("Pass API key as arg or set OANDA_API_KEY env var")
    sys.exit(1)

BASE = "https://api-fxpractice.oanda.com"
HEAD = {"Authorization": f"Bearer {API_KEY}", "Accept-Datetime-Format": "RFC3339"}


def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HEAD, params=params, timeout=15)
    if r.status_code >= 400:
        print(f"ERROR {r.status_code} on {path}: {r.text}")
        sys.exit(1)
    return r.json()


print("=== 1. List accounts ===")
accts = get("/v3/accounts")
for a in accts["accounts"]:
    print(f"  Account ID: {a['id']}  Tags: {a.get('tags', [])}")

if not accts["accounts"]:
    print("No accounts found.")
    sys.exit(1)

acct_id = accts["accounts"][0]["id"]
print(f"\nUsing account: {acct_id}")

print("\n=== 2. Account summary ===")
summary = get(f"/v3/accounts/{acct_id}/summary")["account"]
print(f"  Currency:    {summary['currency']}")
print(f"  Balance:     {summary['balance']}")
print(f"  NAV:         {summary['NAV']}")
print(f"  Margin avail:{summary['marginAvailable']}")
print(f"  Open trades: {summary['openTradeCount']}")

print("\n=== 3. Pricing: GBP_USD + XAU_USD ===")
prices = get(f"/v3/accounts/{acct_id}/pricing", {"instruments": "GBP_USD,XAU_USD"})
for p in prices["prices"]:
    bid = float(p["bids"][0]["price"])
    ask = float(p["asks"][0]["price"])
    mid = (bid + ask) / 2
    print(f"  {p['instrument']}: bid={bid} ask={ask} mid={mid:.4f}")

print("\n=== 4. Instrument details for XAU_USD ===")
instr = get(f"/v3/accounts/{acct_id}/instruments", {"instruments": "XAU_USD"})
xau = instr["instruments"][0]
print(f"  Name:           {xau['displayName']}")
print(f"  Pip location:   {xau['pipLocation']}")
print(f"  Display prec:   {xau['displayPrecision']}")
print(f"  Trade unit prec:{xau['tradeUnitsPrecision']}")
print(f"  Min trade size: {xau['minimumTradeSize']}")

print("\n[OK] All OANDA checks passed.")
print(f"\nPaste this into .env:")
print(f"  OANDA_ACCOUNT_ID={acct_id}")
print(f"  OANDA_ENV=practice")
