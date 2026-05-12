"""Risk management: position sizing and signal deduplication."""
import hashlib
import logging
import math
from collections import deque
from typing import Optional

from signal_parser import Signal

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        risk_pct: float = 0.01,
        force_min_units: bool = True,
        dedup_size: int = 10,
        min_trade_size: float = 0.1,
        units_precision: int = 1,
    ):
        self.risk_pct = risk_pct
        self.force_min_units = force_min_units
        self._seen = deque(maxlen=dedup_size)
        self.min_trade_size = min_trade_size
        self.units_precision = units_precision

    # ---- Deduplication ----
    def _hash(self, signal: Signal) -> str:
        key = f"{signal.direction}:{signal.entry}:{signal.stop_loss}:{signal.tp1}"
        return hashlib.md5(key.encode()).hexdigest()

    def is_duplicate(self, signal: Signal) -> bool:
        h = self._hash(signal)
        if h in self._seen:
            return True
        self._seen.append(h)
        return False

    # ---- Position sizing ----
    def calculate_units(
        self,
        balance_gbp: float,
        gbp_usd_rate: float,
        signal: Signal,
    ) -> Optional[float]:
        """Calculate units for XAU/USD given account balance in GBP.

        XAU/USD on OANDA: 1 unit = 1 oz of gold, price quoted in USD.
        P&L per unit on a 1-point move = $1.

        Returns the units (rounded down to `units_precision` decimals), or None
        if sizing would fall below the broker minimum and force_min_units is False.
        """
        risk_gbp = balance_gbp * self.risk_pct
        risk_usd = risk_gbp * gbp_usd_rate
        sl_distance = abs(signal.entry - signal.stop_loss)

        if sl_distance <= 0:
            logger.warning("Signal has zero SL distance — refusing to size")
            return None

        units_float = risk_usd / sl_distance

        # Round DOWN to the broker's allowed precision so we never exceed risk
        step = 10 ** (-self.units_precision)
        units = math.floor(units_float / step) * step
        units = round(units, self.units_precision)

        logger.info(
            f"Sizing: balance=£{balance_gbp:.2f}, risk_pct={self.risk_pct:.2%}, "
            f"risk_gbp=£{risk_gbp:.2f}, gbp_usd={gbp_usd_rate:.4f}, "
            f"risk_usd=${risk_usd:.2f}, sl_distance={sl_distance:.2f}, "
            f"units_float={units_float:.3f}, rounded_units={units}"
        )

        if units < self.min_trade_size:
            if self.force_min_units:
                units = self.min_trade_size
                actual_risk_usd = sl_distance * units
                actual_risk_gbp = actual_risk_usd / gbp_usd_rate
                actual_pct = actual_risk_gbp / balance_gbp
                logger.warning(
                    f"Calculated units < min ({self.min_trade_size}); forcing min. "
                    f"Actual risk: £{actual_risk_gbp:.2f} ({actual_pct:.2%} of balance)"
                )
                return units
            logger.warning(
                "Calculated units below minimum and FORCE_MIN_UNITS=false — skipping trade"
            )
            return None

        return units
