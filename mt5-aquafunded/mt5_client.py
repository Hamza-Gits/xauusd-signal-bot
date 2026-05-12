"""MT5 client — works on both Windows and Linux (via mt5linux bridge).

On Windows: uses MetaTrader5 package directly.
On Linux (Oracle Cloud): uses mt5linux which bridges to MT5 running under Wine.
"""
import logging
import platform
import sys

logger = logging.getLogger(__name__)


def _get_mt5():
    """Return the right MT5 module for the current OS."""
    if platform.system() == "Windows":
        import MetaTrader5 as mt5
        return mt5
    else:
        # Linux — connect to mt5linux bridge running on localhost:18812
        try:
            from mt5linux import MetaTrader5
            return MetaTrader5(host="localhost", port=18812)
        except ImportError:
            print("ERROR: mt5linux not installed. Run: pip3 install mt5linux")
            sys.exit(1)


class MT5Error(Exception):
    pass


class MT5Client:
    def __init__(self, login: int, password: str, server: str):
        self.login = login
        self.password = password
        self.server = server
        self.mt5 = _get_mt5()

    async def connect(self):
        """Initialise MT5 and log in to AquaFunded."""
        if not self.mt5.initialize():
            raise MT5Error(f"MT5 initialize() failed: {self.mt5.last_error()}")

        ok = self.mt5.login(self.login, password=self.password, server=self.server)
        if not ok:
            raise MT5Error(f"MT5 login failed: {self.mt5.last_error()}")

        info = self.mt5.account_info()
        logger.info(
            f"MT5 connected: {info.name} | "
            f"Balance: ${info.balance:.2f} | "
            f"Server: {info.server}"
        )

    async def get_balance(self) -> float:
        info = self.mt5.account_info()
        if info is None:
            raise MT5Error(f"account_info() failed: {self.mt5.last_error()}")
        return float(info.balance)

    async def place_limit_order(
        self,
        direction: str,
        volume: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        symbol: str = "XAUUSD",
    ) -> dict:
        """Place a pending LIMIT order with SL and TP."""
        direction = direction.upper()
        mt5 = self.mt5

        order_type = (
            mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY"
            else mt5.ORDER_TYPE_SELL_LIMIT
        )

        request = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       symbol,
            "volume":       volume,
            "type":         order_type,
            "price":        round(entry, 2),
            "sl":           round(stop_loss, 2),
            "tp":           round(take_profit, 2),
            "comment":      "TG Signal Bot",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code    = result.retcode if result else "None"
            comment = result.comment if result else str(mt5.last_error())
            raise MT5Error(f"Order rejected [{code}]: {comment}")

        logger.info(f"Order placed: ticket={result.order}")
        return {"orderId": result.order, "retcode": result.retcode}

    async def get_closed_positions(self, limit: int = 10) -> list:
        from datetime import datetime, timedelta
        from_date = datetime.now() - timedelta(days=7)
        deals = self.mt5.history_deals_get(from_date, datetime.now())
        if deals is None:
            return []
        closed = [d._asdict() for d in deals if d.entry == 1]
        return closed[-limit:]
