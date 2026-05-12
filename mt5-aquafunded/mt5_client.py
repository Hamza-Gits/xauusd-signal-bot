"""Direct MetaTrader5 Python client — free, no third-party service.

Requirements:
- MetaTrader5 installed on Windows (download from AquaFunded dashboard)
- MT5 terminal must be running when this script runs
- pip install MetaTrader5

This connects directly to your MT5 terminal on the same machine.
"""
import logging
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Error(Exception):
    pass


class MT5Client:
    def __init__(self, login: int, password: str, server: str):
        self.login = login
        self.password = password
        self.server = server

    async def connect(self):
        """Initialise and log in to MT5 terminal."""
        if not mt5.initialize():
            raise MT5Error(f"MT5 initialize() failed: {mt5.last_error()}")

        authorised = mt5.login(self.login, password=self.password, server=self.server)
        if not authorised:
            raise MT5Error(f"MT5 login failed: {mt5.last_error()}")

        info = mt5.account_info()
        logger.info(
            f"MT5 connected: {info.name} | Balance: ${info.balance:.2f} | "
            f"Server: {info.server}"
        )

    async def get_balance(self) -> float:
        info = mt5.account_info()
        if info is None:
            raise MT5Error(f"Could not get account info: {mt5.last_error()}")
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

        order_type = (
            mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY"
            else mt5.ORDER_TYPE_SELL_LIMIT
        )

        request = {
            "action":      mt5.TRADE_ACTION_PENDING,
            "symbol":      symbol,
            "volume":      volume,
            "type":        order_type,
            "price":       round(entry, 2),
            "sl":          round(stop_loss, 2),
            "tp":          round(take_profit, 2),
            "comment":     "TG Signal Bot",
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "None"
            comment = result.comment if result else mt5.last_error()
            raise MT5Error(f"Order rejected [{code}]: {comment}")

        logger.info(f"Order placed: ticket={result.order}")
        return {"orderId": result.order, "retcode": result.retcode}

    async def get_closed_positions(self, limit: int = 10) -> list:
        """Return recent closed deals for trade journal updates."""
        from datetime import datetime, timedelta
        from_date = datetime.now() - timedelta(days=7)
        deals = mt5.history_deals_get(from_date, datetime.now())
        if deals is None:
            return []
        # Filter only closed positions (entry=1 means exit deal)
        closed = [d._asdict() for d in deals if d.entry == 1]
        return closed[-limit:]
