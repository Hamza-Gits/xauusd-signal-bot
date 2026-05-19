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
# 1% per signal on $5K = $50 risk per signal.
RISK_PCT = float(os.getenv("RISK_PCT", "0.01"))

# ---- Prop firm safety guards (5ers Standard / Bootcamp defaults) ----
# Daily loss circuit breaker — stop trading for the rest of the day if
# daily P&L drops below this %. 5ers' actual daily limit is typically 5%,
# we trip at 3% to keep a 2% safety buffer.
DAILY_LOSS_HALT_PCT = float(os.getenv("DAILY_LOSS_HALT_PCT", "0.03"))

# Consecutive loss pause — after this many SLs in a row, pause for an hour.
# Prevents catastrophic loss-streaks from compounding into account death.
CONSECUTIVE_LOSS_HALT = int(os.getenv("CONSECUTIVE_LOSS_HALT", "3"))
CONSECUTIVE_LOSS_PAUSE_MIN = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_MIN", "60"))

# Total drawdown floor — if account equity drops below this % of starting
# balance, halt the bot entirely. 5ers' actual limit is typically 8-10%,
# we trip at 5% to give a 3-5% safety buffer.
TOTAL_DD_HALT_PCT = float(os.getenv("TOTAL_DD_HALT_PCT", "0.05"))

# Starting balance baseline — used for total DD calculations. Updated
# automatically the first time the bot starts on a fresh account.
STARTING_BALANCE_FILE = "starting_balance.json"

# Account currency (5ers MT5 accounts are USD)
ACCOUNT_CURRENCY = "USD"
