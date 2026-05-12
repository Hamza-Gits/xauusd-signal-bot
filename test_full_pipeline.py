"""Full pipeline test — places a REAL order on your OANDA demo account.

Simulates receiving a signal from each group format and executes it.
Run this to confirm every component works end-to-end.
Does NOT require Telegram to be running.
"""
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv
load_dotenv()

import config
from oanda_client import OandaClient, OandaError
from risk_manager import RiskManager
from signal_parser import parse_signal

# Real signal formats from your groups
TEST_SIGNALS = [
    {
        "group": "TradewithQasem (Format 1)",
        "text": "GOLD BUY 4673\n\n🔷TP1 - 4675.4\n🔷TP2 - 4679\n🔷TP3 - 4683\n\n🔶SL -  4664",
    },
    {
        "group": "Evolute (Format 2)",
        "text": "XAUUSD | Potential upward movement\n\nXAUUSD | BUY 4672\n\n❌ Stop Loss 4665 (70 pips)\n\n✅TP1 4675\n✅TP2 4680\n✅TP3 4685",
    },
]

def main():
    oanda = OandaClient(config.OANDA_API_KEY, config.OANDA_ACCOUNT_ID, env=config.OANDA_ENV)
    risk = RiskManager(risk_pct=config.RISK_PCT, force_min_units=config.FORCE_MIN_UNITS)

    balance = oanda.get_account_balance()
    gbp_usd = oanda.get_price("GBP_USD")
    xau_usd = oanda.get_price("XAU_USD")

    print(f"Account:  £{balance:.2f} GBP  (OANDA {config.OANDA_ENV})")
    print(f"GBP/USD:  {gbp_usd:.4f}")
    print(f"XAU/USD:  {xau_usd:.2f}")
    print(f"Risk/trade: {config.RISK_PCT*100:.1f}%  = £{balance*config.RISK_PCT:.2f}")
    print("=" * 60)

    placed_order_ids = []

    for t in TEST_SIGNALS:
        print(f"\nGroup:  {t['group']}")
        print(f"Signal: {t['text'][:80].replace(chr(10), ' | ')}")

        sig = parse_signal(t["text"])
        if not sig:
            print("  [FAIL] Could not parse signal!")
            continue

        units = risk.calculate_units(balance, gbp_usd, sig)
        if not units:
            print("  [SKIP] Risk sizing returned None")
            continue

        sl_dist = abs(sig.entry - sig.stop_loss)
        risk_gbp = (sl_dist * units) / gbp_usd
        print(f"  Parsed: {sig.direction} @ {sig.entry}  SL={sig.stop_loss}  TP1={sig.tp1}")
        print(f"  Units:  {units}  |  Risk: £{risk_gbp:.2f} ({risk_gbp/balance*100:.2f}%)")

        try:
            result = oanda.place_limit_order(
                direction=sig.direction,
                units=units,
                entry=sig.entry,
                stop_loss=sig.stop_loss,
                take_profit=sig.tp1,
            )
            order_id = result["orderCreateTransaction"]["id"]
            placed_order_ids.append(order_id)
            print(f"  [OK] Order placed. ID={order_id}")
        except OandaError as e:
            print(f"  [ERROR] {e}")

    print("\n" + "=" * 60)
    if placed_order_ids:
        print(f"[OK] {len(placed_order_ids)} order(s) placed on demo account: {placed_order_ids}")
        print("\nCheck your OANDA demo account:")
        print("  https://trade.oanda.com  -> Activity -> Orders")
        print("\nThese are PENDING LIMIT orders. They will only fill if price")
        print("reaches the entry price. Cancel them manually if you wish.")
    else:
        print("[FAIL] No orders were placed. Check errors above.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
