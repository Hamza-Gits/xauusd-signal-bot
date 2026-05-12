"""OANDA REST API v20 client for XAU/USD trading."""
import logging
from typing import Optional

# Inject system trust store into ssl before importing requests so corporate /
# Windows-signed roots are honoured (works around certifi-bundle mismatches on
# locked-down machines).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

logger = logging.getLogger(__name__)


class OandaError(Exception):
    """Raised when an OANDA API call fails."""


BASE_URLS = {
    "live": "https://api-fxtrade.oanda.com",
    "practice": "https://api-fxpractice.oanda.com",
}


class OandaClient:
    def __init__(self, api_key: str, account_id: str, env: str = "live", timeout: int = 15):
        if env not in BASE_URLS:
            raise ValueError(f"env must be 'live' or 'practice', got {env}")
        self.account_id = account_id
        self.base_url = BASE_URLS[env]
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        })

    # ---- Internal request helper ----
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise OandaError(f"Network error calling {method} {path}: {e}") from e

        if resp.status_code >= 400:
            raise OandaError(
                f"OANDA {method} {path} failed [{resp.status_code}]: {resp.text}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise OandaError(f"Invalid JSON from {path}: {resp.text}") from e

    # ---- Public methods ----
    def get_account_summary(self) -> dict:
        data = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        return data["account"]

    def get_account_balance(self) -> float:
        """Return account NAV in account currency (GBP for this user)."""
        acct = self.get_account_summary()
        return float(acct["balance"])

    def get_closed_trades(self, count: int = 10) -> list:
        """Get the N most recent closed trades."""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/trades",
            params={"state": "CLOSED", "count": count},
        )
        return data.get("trades", [])

    def get_price(self, instrument: str) -> float:
        """Return the current mid price for an instrument (e.g. GBP_USD)."""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/pricing",
            params={"instruments": instrument},
        )
        prices = data.get("prices", [])
        if not prices:
            raise OandaError(f"No pricing returned for {instrument}")
        p = prices[0]
        bid = float(p["bids"][0]["price"])
        ask = float(p["asks"][0]["price"])
        return (bid + ask) / 2.0

    def place_limit_order(
        self,
        direction: str,
        units: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        instrument: str = "XAU_USD",
        time_in_force: str = "GTC",
        price_precision: int = 3,
        units_precision: int = 1,
    ) -> dict:
        """Place a LIMIT order with attached SL and TP.

        BUY -> positive units, SELL -> negative units.
        XAU/USD typically uses 3 decimal places for the price and 1 decimal
        for units (e.g. 0.5 oz).
        """
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")
        if units <= 0:
            raise ValueError("units must be > 0")

        signed_units = units if direction == "BUY" else -units
        units_str = f"{signed_units:.{units_precision}f}"

        body = {
            "order": {
                "type": "LIMIT",
                "instrument": instrument,
                "units": units_str,
                "price": f"{entry:.{price_precision}f}",
                "timeInForce": time_in_force,
                "positionFill": "DEFAULT",
                "stopLossOnFill": {
                    "price": f"{stop_loss:.{price_precision}f}",
                    "timeInForce": "GTC",
                },
                "takeProfitOnFill": {
                    "price": f"{take_profit:.{price_precision}f}",
                    "timeInForce": "GTC",
                },
            }
        }

        logger.info(f"Submitting OANDA limit order: {body}")
        return self._request(
            "POST", f"/v3/accounts/{self.account_id}/orders", json=body
        )
