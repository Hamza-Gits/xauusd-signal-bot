"""Load and validate configuration for the 5ers MT5 bot."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"[FATAL] Required environment variable missing: {name}", file=sys.stderr)
        sys.exit(1)
    return value


# ---- MT5 / 5ers credentials ----
# MT5 login is numeric, password and server are strings.
# MT5_PATH is optional — if omitted, MT5 uses the default install location.
MT5_LOGIN = int(_require("MT5_LOGIN"))
MT5_PASSWORD = _require("MT5_PASSWORD")
MT5_SERVER = _require("MT5_SERVER")              # e.g. "FivePercentOnline-Real"
MT5_PATH = os.getenv("MT5_PATH", "").strip() or None  # full path to terminal64.exe if non-default

# Magic number — tags all orders placed by this bot so we can filter our
# trades vs anything you place manually. Pick any 6-digit number.
MT5_MAGIC = int(os.getenv("MT5_MAGIC", "271828"))

# Trading symbol — 5ers brokers may use "XAUUSD", "GOLD", "XAUUSD.r", etc.
# The bot will validate this exists at startup.
INSTRUMENT = os.getenv("MT5_INSTRUMENT", "XAUUSD").strip()

# ---- Telegram ----
TELEGRAM_API_ID = int(_require("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _require("TELEGRAM_API_HASH")
TELEGRAM_PHONE = _require("TELEGRAM_PHONE")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

_raw_groups = _require("TELEGRAM_GROUP_IDS")
TELEGRAM_GROUP_IDS = [g.strip() for g in _raw_groups.split(",") if g.strip()]

NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()

# ---- Risk ----
# 5ers Bootcamp Phase 1: max DD is 5% absolute from initial balance,
# NO daily loss limit. Profit target ~10% to advance.
# Risk per signal kept very tight because each SL bites a noticeable
# chunk out of the 5% drawdown budget.
RISK_PCT = float(os.getenv("RISK_PCT", "0.005"))  # 0.5% = $25/signal on $5K

# ---- Prop firm safety guards ----
# 5ers Bootcamp has NO daily loss limit, so we set this very high
# (effectively disabling it). Override via env if your plan differs.
DAILY_LOSS_HALT_PCT = float(os.getenv("DAILY_LOSS_HALT_PCT", "1.0"))  # 100% = disabled

# Consecutive loss pause — pause trading after N SLs in a row. Tighter
# than the OANDA defaults because we have less margin for error here.
CONSECUTIVE_LOSS_HALT = int(os.getenv("CONSECUTIVE_LOSS_HALT", "2"))
CONSECUTIVE_LOSS_PAUSE_MIN = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_MIN", "120"))

# Total drawdown floor — hard halt if equity drops this % below the
# INITIAL balance (not current). 5ers actual limit is 5%; we halt at
# 4.5% to leave a tiny safety buffer for slippage on the closing trade.
TOTAL_DD_HALT_PCT = float(os.getenv("TOTAL_DD_HALT_PCT", "0.045"))

# IMPORTANT: this is the ORIGINAL account starting balance, not your
# current equity. For a 5ers $5K Bootcamp, this MUST be 5000.00 even
# if you've already drawn down. The bot uses this as the immovable
# baseline for max-DD calculations. If unset, the bot will auto-detect
# from your first balance reading — which can be wrong if you've
# already lost money.
MT5_INITIAL_BALANCE = float(os.getenv("MT5_INITIAL_BALANCE", "0")) or None
STARTING_BALANCE_FILE = "starting_balance.json"

# Account currency (5ers MT5 accounts are USD)
ACCOUNT_CURRENCY = "USD"
