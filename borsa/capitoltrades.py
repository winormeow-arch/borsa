"""Fetch congressional trade disclosures from Capitol Trades.

Uses the JSON backend that powers capitoltrades.com. The response shape below
matches what the site served when this was written; if they change it, only
`parse_trade` should need updating.
"""
from dataclasses import dataclass
from datetime import date
from typing import Iterator, Optional

import requests

BFF_URL = "https://bff.capitoltrades.com/trades"
PAGE_SIZE = 100


@dataclass(frozen=True)
class Trade:
    tx_id: str
    politician_id: str
    politician: str
    ticker: str
    tx_type: str  # "buy" or "sell"
    tx_date: date
    pub_date: date
    value: float  # estimated dollar value (midpoint of the disclosed range)


def _ticker(raw: Optional[str]) -> Optional[str]:
    # Capitol Trades formats tickers as "AAPL:US"; skip non-US listings.
    if not raw:
        return None
    symbol, _, market = raw.partition(":")
    if market and market != "US":
        return None
    return symbol.replace("/", ".").upper() or None


def parse_trade(item: dict) -> Optional[Trade]:
    tx_type = (item.get("txType") or "").lower()
    if tx_type == "sell_partial" or tx_type == "sell_full":
        tx_type = "sell"
    if tx_type not in ("buy", "sell"):
        return None  # exchanges, receipts, etc. don't map to a position change
    ticker = _ticker((item.get("issuer") or {}).get("issuerTicker"))
    value = item.get("value")
    if not ticker or not value:
        return None
    pol = item.get("politician") or {}
    return Trade(
        tx_id=str(item.get("_txId")),
        politician_id=str(item.get("_politicianId") or pol.get("_politicianId")),
        politician=f"{pol.get('firstName', '')} {pol.get('lastName', '')}".strip(),
        ticker=ticker,
        tx_type=tx_type,
        tx_date=date.fromisoformat(str(item["txDate"])[:10]),
        pub_date=date.fromisoformat(str(item["pubDate"])[:10]),
        value=float(value),
    )


def _pages(session: requests.Session, params: dict) -> Iterator[list]:
    page = 1
    while True:
        resp = session.get(BFF_URL, params={**params, "page": page, "pageSize": PAGE_SIZE}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        yield body.get("data") or []
        paging = (body.get("meta") or {}).get("paging") or {}
        if page >= int(paging.get("totalPages") or 0):
            return
        page += 1


def fetch_trades(days: int = 365) -> list[Trade]:
    """All stock buys/sells with a transaction date in the last `days` days."""
    session = requests.Session()
    session.headers["User-Agent"] = "borsa/1.0"
    trades = []
    for items in _pages(session, {"txDate": f"{days}d"}):
        trades.extend(t for t in map(parse_trade, items) if t)
    return trades
