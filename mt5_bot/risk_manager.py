"""Lot-based position sizing for MT5 / 5ers ($ account)."""
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
        dedup_size: int = 20,
    ):
        self.risk_pct = risk_pct
        self._seen = deque(maxlen=dedup_size)

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

    # ---- Position sizing in LOTS ----
    def calculate_lots(
        self,
        balance_usd: float,
        signal: Signal,
        contract_size: float,
        min_lot: float,
        lot_step: float,
    ) -> Optional[float]:
        """Calculate total lot size for the signal.

        Risk per lot per USD price move = contract_size.
        For XAUUSD: contract_size = 100, so 1 lot risks $100 per $1 price move.
        SL distance in USD × contract_size × lots = USD risk.
        So: lots = risk_usd / (sl_distance × contract_size)

        Returns lot size rounded DOWN to lot_step precision, or None if below
        broker minimum.
        """
        risk_usd = balance_usd * self.risk_pct
        sl_distance = abs(signal.entry - signal.stop_loss)
        if sl_distance <= 0:
            logger.warning("Signal has zero SL distance — refusing to size")
            return None

        # Risk per lot = SL distance × contract_size
        risk_per_lot = sl_distance * contract_size
        lots_float = risk_usd / risk_per_lot

        # Floor to lot_step precision
        lots = math.floor(lots_float / lot_step) * lot_step
        # Defensive round to avoid floating-point ugliness like 0.030000000004
        decimals = max(0, -int(math.floor(math.log10(lot_step))))
        lots = round(lots, decimals)

        logger.info(
            f"Sizing: balance=${balance_usd:.2f}, risk_pct={self.risk_pct:.2%}, "
            f"risk_usd=${risk_usd:.2f}, sl_distance=${sl_distance:.2f}, "
            f"contract_size={contract_size}, risk_per_lot=${risk_per_lot:.2f}, "
            f"lots_float={lots_float:.4f}, rounded_lots={lots}"
        )

        if lots < min_lot:
            logger.warning(
                f"Calculated lots ({lots}) below broker minimum ({min_lot}) — skipping."
            )
            return None

        return lots
