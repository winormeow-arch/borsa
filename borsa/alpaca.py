"""Minimal Alpaca trading + market data client."""
from datetime import date
from typing import Optional

import requests

from .config import Config


class Alpaca:
    def __init__(self, cfg: Config):
        base = cfg.alpaca_base_url
        self.base = base if base.endswith("/v2") else base + "/v2"
        self.data = cfg.alpaca_data_url
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": cfg.alpaca_key,
            "APCA-API-SECRET-KEY": cfg.alpaca_secret,
        })

    def _req(self, method: str, url: str, **kw):
        resp = self.session.request(method, url, timeout=30, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"Alpaca {method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    # --- trading ---
    def account(self) -> dict:
        return self._req("GET", f"{self.base}/account")

    def clock(self) -> dict:
        return self._req("GET", f"{self.base}/clock")

    def positions(self) -> dict[str, dict]:
        return {p["symbol"]: p for p in self._req("GET", f"{self.base}/positions")}

    def asset(self, symbol: str) -> Optional[dict]:
        try:
            return self._req("GET", f"{self.base}/assets/{symbol}")
        except RuntimeError:
            return None

    def close_position(self, symbol: str) -> dict:
        return self._req("DELETE", f"{self.base}/positions/{symbol}")

    def market_order(self, symbol: str, side: str, *, notional: float = None, qty: float = None) -> dict:
        order = {"symbol": symbol, "side": side, "type": "market", "time_in_force": "day"}
        if notional is not None:
            order["notional"] = f"{notional:.2f}"
        else:
            order["qty"] = f"{qty:.9f}".rstrip("0").rstrip(".")
        return self._req("POST", f"{self.base}/orders", json=order)

    # --- market data ---
    def daily_closes(self, symbols: list[str], start: date) -> dict[str, list[tuple[date, float]]]:
        """Split/dividend-adjusted daily closes per symbol, oldest first."""
        out: dict[str, list[tuple[date, float]]] = {}
        for i in range(0, len(symbols), 100):
            params = {
                "symbols": ",".join(symbols[i:i + 100]),
                "timeframe": "1Day",
                "start": start.isoformat(),
                "adjustment": "all",
                "feed": "iex",
                "limit": 10000,
            }
            while True:
                body = self._req("GET", f"{self.data}/stocks/bars", params=params)
                for sym, bars in (body.get("bars") or {}).items():
                    out.setdefault(sym, []).extend(
                        (date.fromisoformat(b["t"][:10]), float(b["c"])) for b in bars
                    )
                token = body.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
        return out
