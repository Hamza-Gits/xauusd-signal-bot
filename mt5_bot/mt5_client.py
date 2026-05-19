"""Wrapper around the MetaTrader5 Python library.

Mirrors the surface of oanda_client.py (place_limit_order, get_open_trades,
modify_trade_sl, cancel_order, etc.) so main.py reads cleanly.
"""
import logging
from typing import Optional

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Error(Exception):
    """Raised when an MT5 operation fails."""


class MT5Client:
    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        magic: int,
        symbol: str,
        path: Optional[str] = None,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic
        self.symbol = symbol
        self.path = path
        self.symbol_info = None  # set on connect()

    # ---- Lifecycle ----
    def connect(self) -> None:
        """Initialise MT5 and log into the broker. Raises MT5Error on failure."""
        if self.path:
            ok = mt5.initialize(
                path=self.path,
                login=self.login,
                password=self.password,
                server=self.server,
            )
        else:
            ok = mt5.initialize(
                login=self.login,
                password=self.password,
                server=self.server,
            )
        if not ok:
            err = mt5.last_error()
            raise MT5Error(f"initialize() failed: {err}")

        # Confirm we logged into the right account
        account = mt5.account_info()
        if account is None:
            raise MT5Error(f"account_info() returned None — login may have failed: {mt5.last_error()}")
        if account.login != self.login:
            raise MT5Error(f"Logged into wrong account: expected {self.login}, got {account.login}")

        # Resolve symbol — 5ers brokers vary on naming
        sym = mt5.symbol_info(self.symbol)
        if sym is None:
            available = [s.name for s in mt5.symbols_get() if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]
            raise MT5Error(
                f"Symbol '{self.symbol}' not found. Possible matches on this broker: {available}"
            )
        # Make sure it's enabled in MarketWatch
        if not sym.visible:
            if not mt5.symbol_select(self.symbol, True):
                raise MT5Error(f"Could not enable {self.symbol} in MarketWatch")
            sym = mt5.symbol_info(self.symbol)  # reload after enabling

        self.symbol_info = sym
        logger.info(
            f"MT5 connected. Account {account.login} ({account.server}). "
            f"Balance ${account.balance:.2f}, Equity ${account.equity:.2f}. "
            f"Symbol {self.symbol}: bid={sym.bid}, ask={sym.ask}, "
            f"digits={sym.digits}, contract_size={sym.trade_contract_size}, "
            f"min_lot={sym.volume_min}, lot_step={sym.volume_step}"
        )

    def disconnect(self) -> None:
        mt5.shutdown()

    # ---- Account info ----
    def get_account(self) -> dict:
        info = mt5.account_info()
        if info is None:
            raise MT5Error(f"account_info() failed: {mt5.last_error()}")
        return info._asdict()

    def get_balance(self) -> float:
        return float(self.get_account()["balance"])

    def get_equity(self) -> float:
        return float(self.get_account()["equity"])

    # ---- Quotes ----
    def get_current_price(self) -> tuple:
        """Return (bid, ask) for the trading symbol."""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise MT5Error(f"symbol_info_tick failed: {mt5.last_error()}")
        return float(tick.bid), float(tick.ask)

    # ---- Order placement ----
    def place_limit_order(
        self,
        direction: str,
        volume_lots: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        comment: str = "",
    ) -> dict:
        """Place a pending LIMIT order with attached SL and TP.

        volume_lots is in lots (e.g. 0.01 = 1 oz of gold on most brokers).
        Returns the broker's order_send result as a dict.
        """
        direction = direction.upper()
        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
        elif direction == "SELL":
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
        else:
            raise ValueError(f"direction must be BUY or SELL, got {direction}")

        digits = self.symbol_info.digits

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": self.symbol,
            "volume": round(volume_lots, 2),
            "type": order_type,
            "price": round(entry, digits),
            "sl": round(stop_loss, digits),
            "tp": round(take_profit, digits),
            "magic": self.magic,
            "comment": comment[:31],  # MT5 caps comment at 31 chars
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._pick_filling_mode(),
        }

        logger.info(f"MT5 order_send: {request}")
        result = mt5.order_send(request)
        if result is None:
            raise MT5Error(f"order_send returned None: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(
                f"order_send failed: retcode={result.retcode}, comment={result.comment}, "
                f"request_id={result.request_id}"
            )
        return result._asdict()

    def _pick_filling_mode(self):
        """Pick the right filling mode for this broker — varies by 5ers vendor."""
        modes = self.symbol_info.filling_mode
        if modes & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if modes & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    # ---- Position & order queries ----
    def get_open_positions(self) -> list:
        """Return all open positions for our symbol/magic."""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return []
        return [p._asdict() for p in positions if p.magic == self.magic]

    def get_pending_orders(self) -> list:
        """Return all pending orders for our symbol/magic."""
        orders = mt5.orders_get(symbol=self.symbol)
        if orders is None:
            return []
        return [o._asdict() for o in orders if o.magic == self.magic]

    def get_closed_deals(self, hours: int = 48) -> list:
        """Return closed deals from the last N hours that belong to us."""
        from datetime import datetime, timedelta
        now = datetime.now()
        deals = mt5.history_deals_get(now - timedelta(hours=hours), now)
        if deals is None:
            return []
        return [d._asdict() for d in deals if d.magic == self.magic and d.symbol == self.symbol]

    # ---- Modify / cancel ----
    def modify_position_sl(self, ticket: int, new_sl: float, tp: float) -> dict:
        """Modify SL (and preserve TP) on an open position."""
        digits = self.symbol_info.digits
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": ticket,
            "sl": round(new_sl, digits),
            "tp": round(tp, digits),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else mt5.last_error()
            raise MT5Error(f"modify_position_sl failed: {err}")
        return result._asdict()

    def cancel_order(self, ticket: int) -> dict:
        """Cancel a pending order by ticket."""
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else mt5.last_error()
            raise MT5Error(f"cancel_order failed: {err}")
        return result._asdict()
