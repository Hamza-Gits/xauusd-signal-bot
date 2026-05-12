"""Dry-run: parse real signal messages and show what would happen.

No orders are placed. Connects to OANDA only to fetch live balance + GBP/USD.
"""
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from oanda_client import OandaClient
from risk_manager import RiskManager
from signal_parser import parse_signal


API_KEY = "39680880beb4cfb342cdc0a558c3bb27-a1d5297985acffae3ba9ea8d4fdef244"
ACCOUNT_ID = "101-004-39300802-001"

# Real messages pasted by the user.
RAW_MESSAGES = [
    # Group 1: Evolute
    "XAUUSD | Potential upward movement \n\nXAUUSD | BUY 4659.6\n\n❌ Stop Loss 4653 (60 pips)\n\n✅TP1 4663\n✅TP2 4668\n✅TP3 4675",
    "Stop loss got tagged.",
    "YOUR NEXT FREE TRADE IS COMING 💰\n\nDrop a (🔥) if you are watching!",
    "XAUUSD | Potential upward movement \n\nXAUUSD | BUY 4660\n\n❌ Stop Loss 4653 (70 pips)\n\n✅TP1 4663\n✅TP2 4668\n✅TP3 4675",
    "XAUUSD | Potential upward movement \n\nXAUUSD | BUY 4672\n\n❌ Stop Loss 4665 (70 pips)\n\n✅TP1 4675\n✅TP2 4680\n✅TP3 4685",
    "XAUUSD | Potential upward movement \n\nXAUUSD | BUY 4699\n\n❌ Stop Loss 4693 (60 pips)\n\n✅TP1 4702\n✅TP2 4705\n✅TP3 4713",
    # Group 2: TradewithQasem
    "Ready 🔥🔥",
    "GOLD BUY 4577\n\n🔷TP1 - 4580\n🔷TP2 - 4584\n🔷TP3 - 4588\n\n🔶SL -  4570",
    "GOLD BUY 4550\n\n🔷TP1 - 4553\n🔷TP2 - 4556\n🔷TP3 - 4560\n\n🔶SL -  4542",
    "GOLD SELL 4675\n\n🔷TP1 - 4672.6\n🔷TP2 - 4669\n🔷TP3 - 4665\n\n🔶SL -  4685",
    "Move SL 4685",
    "GOLD BUY 4726\n\n🔷TP1 - 4729\n🔷TP2 - 4732\n🔷TP3 - 4736\n\n🔶SL -  4715",
    "GOLD BUY 4673\n\n🔷TP1 - 4675.4\n🔷TP2 - 4679\n🔷TP3 - 4683\n\n🔶SL -  4664",
    "GOLD BUY 4704\n\n🔷TP1 - 4707\n🔷TP2 - 4710\n🔷TP3 - 4714\n\n🔶SL -  4694",
]


def main():
    oanda = OandaClient(API_KEY, ACCOUNT_ID, env="practice")
    balance = oanda.get_account_balance()
    gbp_usd = oanda.get_price("GBP_USD")
    print(f"Live balance: £{balance:.2f}  |  GBP/USD mid: {gbp_usd:.4f}\n")
    print("=" * 80)

    risk = RiskManager(risk_pct=0.01, force_min_units=True)

    parsed_count = 0
    skipped_count = 0
    for i, raw in enumerate(RAW_MESSAGES, 1):
        preview = raw.replace("\n", " | ")[:70]
        sig = parse_signal(raw)
        if sig is None:
            skipped_count += 1
            print(f"[{i:2}] IGNORED (not a signal): {preview}")
            continue

        parsed_count += 1
        is_dup = risk.is_duplicate(sig)
        units = None if is_dup else risk.calculate_units(balance, gbp_usd, sig)

        sl_dist = abs(sig.entry - sig.stop_loss)
        risk_usd = sl_dist * (units or 0)
        risk_gbp = risk_usd / gbp_usd
        risk_pct = (risk_gbp / balance) * 100

        status = "DUPLICATE" if is_dup else "WOULD PLACE"
        print(f"\n[{i:2}] {status}")
        print(f"     Direction: {sig.direction}  Entry: {sig.entry}  SL: {sig.stop_loss}  TP1: {sig.tp1}")
        print(f"     SL distance: {sl_dist} points")
        if not is_dup and units:
            print(f"     Units: {units}  |  Risk: £{risk_gbp:.2f} ({risk_pct:.2f}% of balance)")

    print("\n" + "=" * 80)
    print(f"Parsed signals: {parsed_count}  |  Ignored messages: {skipped_count}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
