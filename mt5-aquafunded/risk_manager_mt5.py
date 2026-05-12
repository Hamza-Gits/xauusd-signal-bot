"""Risk management for MT5 — lot-based position sizing and deduplication.

For XAUUSD on MT5:
  1 standard lot = 100 oz of gold
  If price moves $1, P&L = $1 per oz = $100 per lot
  So: risk_per_lot = sl_distance_in_points * 100

Example:
  Balance: $5,000  |  Risk: 1% = $50
  SL distance: 9 points
  risk_per_lot = 9 * 100 = $900
  lots = $50 / $900 = 0.055 → rounded down to 0.05
"""
import hashlib
import logging
import math
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class RiskManagerMT5:
    def __init__(
        self,
        risk_pct: float = 0.01,
        min_lot: float = 0.01,
        lot_precision: int = 2,
        dedup_size: int = 10,
    ):
        self.risk_pct = risk_pct
        self.min_lot = min_lot
        self.lot_precision = lot_precision
        self._seen = deque(maxlen=dedup_size)

    def _hash(self, direction, entry, stop_loss, tp1) -> str:
        key = f"{direction}:{entry}:{stop_loss}:{tp1}"
        return hashlib.md5(key.encode()).hexdigest()

    def is_duplicate(self, direction, entry, stop_loss, tp1) -> bool:
        h = self._hash(direction, entry, stop_loss, tp1)
        if h in self._seen:
            return True
        self._seen.append(h)
        return False

    def calculate_lots(self, balance_usd: float, sl_distance: float) -> Optional[float]:
        """Return lot size rounded DOWN to lot_precision, or None if below min_lot.

        XAUUSD: 1 lot = 100 oz → P&L per lot = sl_distance * 100
        """
        if sl_distance <= 0:
            logger.warning("Zero SL distance — refusing to size")
            return None

        risk_usd = balance_usd * self.risk_pct
        risk_per_lot = sl_distance * 100  # $100 per point per lot for XAUUSD
        lots_float = risk_usd / risk_per_lot

        # Always round DOWN to avoid exceeding risk
        step = 10 ** (-self.lot_precision)
        lots = math.floor(lots_float / step) * step
        lots = round(lots, self.lot_precision)

        logger.info(
            f"Sizing: balance=${balance_usd:.2f}, risk={self.risk_pct:.2%}, "
            f"risk_usd=${risk_usd:.2f}, sl_dist={sl_distance:.2f}, "
            f"lots_float={lots_float:.4f}, lots={lots}"
        )

        if lots < self.min_lot:
            logger.warning(
                f"Calculated lots ({lots}) < min ({self.min_lot}). "
                f"Forcing min lot. Actual risk: ${sl_distance * 100 * self.min_lot:.2f}"
            )
            return self.min_lot

        return lots
