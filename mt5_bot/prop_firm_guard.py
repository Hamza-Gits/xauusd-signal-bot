"""Safety guards specific to prop firm accounts (5ers Bootcamp / Standard).

Tracks:
- Daily P&L vs starting-of-day equity — halts trading if loss > halt threshold
- Consecutive losses — pauses trading for X minutes after N SLs in a row
- Total drawdown from starting balance — full halt if breached

Persisted to disk so state survives bot restarts.
"""
import json
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# 5ers/most prop firms use a 5pm New York reset (ICT MT5 default). Approx 22:00 UTC.
# Adjust if your specific 5ers broker resets at a different time.
BROKER_DAY_RESET_UTC_HOUR = 22


def broker_day_today() -> str:
    """Return a YYYY-MM-DD string for the current broker trading day."""
    now = datetime.now(timezone.utc)
    if now.hour < BROKER_DAY_RESET_UTC_HOUR:
        return now.strftime("%Y-%m-%d")
    # After reset = next broker day
    return (now + timedelta(days=1)).strftime("%Y-%m-%d")


class PropFirmGuard:
    def __init__(
        self,
        starting_balance: float,
        daily_loss_halt_pct: float,
        consecutive_loss_halt: int,
        consecutive_loss_pause_min: int,
        total_dd_halt_pct: float,
        state_file: str = "prop_firm_state.json",
    ):
        self.starting_balance = starting_balance
        self.daily_loss_halt_pct = daily_loss_halt_pct
        self.consecutive_loss_halt = consecutive_loss_halt
        self.consecutive_loss_pause_min = consecutive_loss_pause_min
        self.total_dd_halt_pct = total_dd_halt_pct
        self.state_file = Path(state_file)
        self.state = self._load()

    def _load(self) -> dict:
        if not self.state_file.exists():
            return {
                "broker_day": broker_day_today(),
                "day_start_equity": self.starting_balance,
                "consecutive_losses": 0,
                "pause_until": None,
                "halted_total_dd": False,
            }
        try:
            with open(self.state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("prop_firm_state.json corrupt — resetting")
            return {
                "broker_day": broker_day_today(),
                "day_start_equity": self.starting_balance,
                "consecutive_losses": 0,
                "pause_until": None,
                "halted_total_dd": False,
            }

    def _save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def _roll_day_if_needed(self, current_equity: float):
        """If the broker day has rolled over since last call, reset daily counters."""
        today = broker_day_today()
        if self.state["broker_day"] != today:
            logger.info(
                f"Broker day rolled {self.state['broker_day']} → {today}. "
                f"Resetting daily counters. New day_start_equity=${current_equity:.2f}"
            )
            self.state["broker_day"] = today
            self.state["day_start_equity"] = current_equity
            self.state["consecutive_losses"] = 0
            self.state["pause_until"] = None
            self._save()

    # ---- Public API ----
    def can_trade(self, current_equity: float) -> tuple:
        """Check all guards. Returns (allowed: bool, reason: str|None)."""
        self._roll_day_if_needed(current_equity)

        # 1. Total drawdown guard (hard halt)
        if self.state.get("halted_total_dd"):
            return False, f"Total DD halt active (account dropped below {(1 - self.total_dd_halt_pct):.0%} of ${self.starting_balance:.2f})"

        total_dd_pct = (self.starting_balance - current_equity) / self.starting_balance
        if total_dd_pct >= self.total_dd_halt_pct:
            self.state["halted_total_dd"] = True
            self._save()
            return False, (
                f"TOTAL DD HALT: equity ${current_equity:.2f} is {total_dd_pct:.1%} "
                f"below starting ${self.starting_balance:.2f}. Bot stopped to protect prop account."
            )

        # 2. Daily loss circuit breaker
        day_start = self.state["day_start_equity"]
        daily_loss_pct = (day_start - current_equity) / day_start if day_start > 0 else 0
        if daily_loss_pct >= self.daily_loss_halt_pct:
            return False, (
                f"DAILY LOSS HALT: down {daily_loss_pct:.1%} today "
                f"(${day_start - current_equity:.2f} from day start ${day_start:.2f}). "
                f"Trading paused until next broker day."
            )

        # 3. Consecutive loss pause
        pause_until = self.state.get("pause_until")
        if pause_until:
            until = datetime.fromisoformat(pause_until)
            if datetime.now(timezone.utc) < until:
                remaining = (until - datetime.now(timezone.utc)).total_seconds() / 60
                return False, (
                    f"Consecutive-loss pause active: {self.state['consecutive_losses']} losses in a row, "
                    f"paused {remaining:.0f} more min."
                )
            # Pause expired — clear it
            self.state["pause_until"] = None
            self._save()

        return True, None

    def record_outcome(self, won: bool):
        """Call after every trade closes — updates loss streak counter."""
        if won:
            if self.state["consecutive_losses"] > 0:
                logger.info(f"Win — resetting consecutive-loss counter (was {self.state['consecutive_losses']})")
            self.state["consecutive_losses"] = 0
        else:
            self.state["consecutive_losses"] += 1
            if self.state["consecutive_losses"] >= self.consecutive_loss_halt:
                pause_until = datetime.now(timezone.utc) + timedelta(minutes=self.consecutive_loss_pause_min)
                self.state["pause_until"] = pause_until.isoformat()
                logger.warning(
                    f"{self.state['consecutive_losses']} consecutive losses — "
                    f"pausing trading until {pause_until.isoformat()}"
                )
        self._save()

    def status_line(self, current_equity: float) -> str:
        """Pretty one-liner for Telegram notifications."""
        day_start = self.state["day_start_equity"]
        daily_pnl = current_equity - day_start
        daily_pct = (daily_pnl / day_start * 100) if day_start > 0 else 0
        total_dd = (self.starting_balance - current_equity) / self.starting_balance * 100
        return (
            f"Day P&L: ${daily_pnl:+.2f} ({daily_pct:+.2f}%) | "
            f"Total DD: {total_dd:.2f}% | "
            f"Streak losses: {self.state['consecutive_losses']}"
        )
