"""Turn a member's disclosures into target weights and rebalance orders."""
from collections import defaultdict
from dataclasses import dataclass

from .disclosures import Trade

MIN_ORDER_DOLLARS = 5.0


def implied_holdings(trades: list[Trade]) -> dict[str, float]:
    """Estimated dollars still held per ticker: disclosed buys minus sells.

    Only trades inside the lookback window are visible, so positions opened
    earlier are unknown and sells can over-cancel buys (floored at zero).
    """
    net = defaultdict(float)
    for t in trades:
        net[t.ticker] += t.value if t.tx_type == "buy" else -t.value
    return {k: v for k, v in net.items() if v > 0}


def target_weights(holdings: dict[str, float]) -> dict[str, float]:
    total = sum(holdings.values())
    return {k: v / total for k, v in holdings.items()} if total else {}


@dataclass
class PlannedOrder:
    symbol: str
    side: str  # "buy" | "sell"
    dollars: float
    close: bool = False  # sell the entire position

    def __str__(self):
        what = "close" if self.close else f"{self.side} ${self.dollars:,.2f}"
        return f"{self.symbol}: {what}"


def plan(weights: dict[str, float], budget: float, positions: dict[str, float]) -> list[PlannedOrder]:
    """Orders that move `positions` (symbol -> market value) to `weights` * `budget`.

    Positions outside the target are closed. Sells come first so their cash
    is available for the buys.
    """
    sells, buys = [], []
    for sym, value in positions.items():
        if sym not in weights:
            sells.append(PlannedOrder(sym, "sell", value, close=True))
    for sym, w in weights.items():
        diff = w * budget - positions.get(sym, 0.0)
        if abs(diff) < MIN_ORDER_DOLLARS:
            continue
        (buys if diff > 0 else sells).append(PlannedOrder(sym, "buy" if diff > 0 else "sell", abs(diff)))
    return sorted(sells, key=lambda o: o.symbol) + sorted(buys, key=lambda o: -o.dollars)
