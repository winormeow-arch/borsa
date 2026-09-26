"""Rank members of Congress by the return on their disclosed trades."""
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from .capitoltrades import Trade

Closes = dict[str, list[tuple[date, float]]]


def price_on(closes: Closes, symbol: str, day: date):
    """Last close on or before `day` (None if we have no data that early)."""
    series = closes.get(symbol)
    if not series:
        return None
    i = bisect_right([d for d, _ in series], day)
    return series[i - 1][1] if i else None


def latest_price(closes: Closes, symbol: str):
    series = closes.get(symbol)
    return series[-1][1] if series else None


@dataclass
class Performance:
    politician_id: str
    politician: str
    trades: int
    priced_buys: int
    invested: float
    ret: float  # dollar-weighted return, e.g. 0.12 == +12%


def most_active(trades: list[Trade], n: int) -> list[str]:
    counts = Counter(t.politician_id for t in trades)
    return [pid for pid, _ in counts.most_common(n)]


def performance(trades: list[Trade], closes: Closes) -> Performance:
    """Dollar-weighted return of every disclosed buy.

    Each buy is marked from its transaction-date close to either the close on
    the member's next sale of that ticker or, if still held, the latest close.
    Sales of stock bought before the window have no known cost basis and are
    not scored. Disclosed sizes are ranges, so `value` is an estimate.
    """
    by_ticker = defaultdict(list)
    for t in sorted(trades, key=lambda t: t.tx_date):
        by_ticker[t.ticker].append(t)

    invested = pnl = 0.0
    priced = 0
    for ticker, txs in by_ticker.items():
        for i, t in enumerate(txs):
            if t.tx_type != "buy":
                continue
            entry = price_on(closes, ticker, t.tx_date)
            sale = next((s for s in txs[i + 1:] if s.tx_type == "sell"), None)
            exit_ = price_on(closes, ticker, sale.tx_date) if sale else latest_price(closes, ticker)
            if not entry or not exit_:
                continue
            invested += t.value
            pnl += t.value * (exit_ / entry - 1)
            priced += 1

    first = trades[0]
    return Performance(
        politician_id=first.politician_id,
        politician=first.politician,
        trades=len(trades),
        priced_buys=priced,
        invested=invested,
        ret=pnl / invested if invested else 0.0,
    )


def rank(trades: list[Trade], closes: Closes, n_active: int, min_priced_buys: int = 5) -> list[Performance]:
    by_pol = defaultdict(list)
    for t in trades:
        by_pol[t.politician_id].append(t)
    results = [performance(by_pol[pid], closes) for pid in most_active(trades, n_active)]
    results = [r for r in results if r.priced_buys >= min_priced_buys]
    return sorted(results, key=lambda r: r.ret, reverse=True)
