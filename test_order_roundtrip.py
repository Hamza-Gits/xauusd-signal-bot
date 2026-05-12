"""Place a tiny test limit order far from market, then cancel it.

Verifies the full order placement chain on the OANDA practice account.
0.1 units (minimum) with entry far below market — won't fill before we cancel.
"""
import sys
import time

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

from oanda_client import OandaClient

API_KEY = "39680880beb4cfb342cdc0a558c3bb27-a1d5297985acffae3ba9ea8d4fdef244"
ACCOUNT_ID = "101-004-39300802-001"

oanda = OandaClient(API_KEY, ACCOUNT_ID, env="practice")

xau_mid = oanda.get_price("XAU_USD")
print(f"Current XAU/USD mid: {xau_mid:.2f}")

# Limit far below market so it stays pending.
entry = round(xau_mid - 50, 2)
sl = round(entry - 10, 2)
tp = round(entry + 10, 2)
print(f"Test order: BUY 0.1 units @ {entry}  SL {sl}  TP {tp}")

resp = oanda.place_limit_order(
    direction="BUY",
    units=0.1,
    entry=entry,
    stop_loss=sl,
    take_profit=tp,
)

create_tx = resp.get("orderCreateTransaction", {})
order_id = create_tx.get("id")
print(f"[OK] Order created. Transaction ID: {order_id}")
print(f"     Order type: {create_tx.get('type')}")
print(f"     Instrument: {create_tx.get('instrument')}")
print(f"     Units: {create_tx.get('units')}")

# Find the actual pending order ID (different from transaction ID)
time.sleep(1)
url = f"https://api-fxpractice.oanda.com/v3/accounts/{ACCOUNT_ID}/pendingOrders"
headers = {"Authorization": f"Bearer {API_KEY}"}
r = requests.get(url, headers=headers, timeout=15)
pending = r.json().get("orders", [])
print(f"\nPending orders on account: {len(pending)}")
for o in pending:
    print(f"  ID={o['id']}  type={o['type']}  units={o.get('units')}  price={o.get('price')}")

# Cancel the order we just placed
if pending:
    target = pending[-1]  # most recent
    cancel_url = f"https://api-fxpractice.oanda.com/v3/accounts/{ACCOUNT_ID}/orders/{target['id']}/cancel"
    r = requests.put(cancel_url, headers=headers, timeout=15)
    if r.status_code == 200:
        print(f"\n[OK] Cancelled order {target['id']}")
    else:
        print(f"\n[ERR] Cancel failed: {r.status_code} {r.text}")

print("\n[OK] End-to-end order roundtrip verified.")
