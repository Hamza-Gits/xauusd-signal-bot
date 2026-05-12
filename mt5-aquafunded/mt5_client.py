"""MetaAPI cloud client — connects to AquaFunded MT5 account.

MetaAPI acts as a REST/WebSocket bridge to your MT5 server.
No need to have MT5 installed locally or on the server.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MT5Error(Exception):
    pass


class MT5Client:
    def __init__(self, token: str, account_id: str):
        self.token = token
        self.account_id = account_id
        self._connection = None
        self._account = None

    async def connect(self):
        """Connect to MetaAPI and synchronise with the MT5 account."""
        try:
            from metaapi_cloud_sdk import MetaApi
        except ImportError:
            raise MT5Error(
                "metaapi-cloud-sdk not installed. Run: pip install metaapi-cloud-sdk"
            )

        logger.info("Connecting to MetaAPI...")
        api = MetaApi(self.token)

        try:
            self._account = await api.metatrader_account_api.get_account(self.account_id)
        except Exception as e:
            raise MT5Error(f"Could not get MetaAPI account: {e}") from e

        if self._account.state not in ("DEPLOYED", "DEPLOYING"):
            logger.info("Deploying MT5 account on MetaAPI...")
            await self._account.deploy()

        logger.info("Waiting for MT5 connection...")
        await self._account.wait_connected()

        self._connection = self._account.get_rpc_connection()
        await self._connection.connect()
        await self._connection.wait_synchronized()
        logger.info("MT5 synchronised and ready.")

    async def get_balance(self) -> float:
        """Return account balance in account currency (USD for AquaFunded)."""
        info = await self._connection.get_account_information()
        return float(info["balance"])

    async def place_limit_order(
        self,
        direction: str,
        volume: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        symbol: str = "XAUUSD",
    ) -> dict:
        """Place a LIMIT order with SL and TP attached.

        direction: "BUY" or "SELL"
        volume:    lot size e.g. 0.05
        """
        direction = direction.upper()
        opts = {"comment": "TG Signal Bot", "clientId": "xauusd-signal-bot"}

        try:
            if direction == "BUY":
                result = await self._connection.create_limit_buy_order(
                    symbol, volume, entry, stop_loss, take_profit, opts
                )
            elif direction == "SELL":
                result = await self._connection.create_limit_sell_order(
                    symbol, volume, entry, stop_loss, take_profit, opts
                )
            else:
                raise MT5Error(f"Invalid direction: {direction}")
        except Exception as e:
            raise MT5Error(f"Order failed: {e}") from e

        logger.info(f"Order placed: {result}")
        return result

    async def get_closed_positions(self, limit: int = 10) -> list:
        """Return recent closed positions for trade journal updates."""
        try:
            positions = await self._connection.get_history_orders_by_time_range(
                None, None, 0, limit
            )
            return positions.get("historyOrders", [])
        except Exception as e:
            logger.warning(f"Could not fetch history: {e}")
            return []
