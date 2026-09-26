import unittest
from datetime import date

from borsa import disclosures, portfolio, ranking
from borsa.__main__ import previous_weekday
from borsa.disclosures import Trade


def T(pid, ticker, kind, d, value=1000.0, pub=None):
    return Trade(f"{pid}{ticker}{d}{kind}", pid, f"Member {pid}", ticker, kind, d, pub or d, value)


HOUSE_PTR = """Name: Hon. Ann Lee
ID Owner Asset Transaction
Type
Date Notification
Date
Amount Cap.
Gains >
$200?
SP NVIDIA Corporation - Common Stock
(NVDA) [ST]
P 01/16/2026 01/16/2026 $250,001 -
$500,000
F\x00S\x00: New
D: Sold 20,000 shares (5,000 via options).
JP Morgan buffer note [CS]
P 12/30/2025 12/30/2025 $1,001 - $15,000
F\x00S\x00: New
SP Versant Media Group (VSNT) [ST]
E 01/02/2026 01/02/2026 $15.00
F\x00S\x00: New
Verizon Communications Inc. S (partial) 01/30/2026 01/30/2026 $15,001 -
Filing ID #20034034
ID Owner Asset Transaction
Type
Date Notification
Date
Amount Cap.
Gains >
$200?
Common Stock (VZ) [ST] $50,000
F\x00S\x00: New
Berkshire Hathaway Inc. (BRK/B) [ST] S 02/01/2026 02/01/2026 Over $50,000,000
F\x00S\x00: New
"""

SENATE_PTR = """<table><tbody>
<tr><td>1</td><td> 09/01/2026 </td><td>Spouse</td><td> <a href="x">WFC</a> </td>
<td> Wells Fargo &amp; Company </td><td>Stock</td><td>Purchase</td><td>$15,001 - $50,000</td><td>--</td></tr>
<tr><td>2</td><td>09/02/2026</td><td>Self</td><td>--</td><td>Muni bond</td><td>Municipal Security</td>
<td>Sale (Full)</td><td>$1,001 - $15,000</td><td>--</td></tr>
<tr><td>3</td><td>09/03/2026</td><td>Self</td><td>AAPL</td><td>Apple</td><td>Stock</td>
<td>Sale (Partial)</td><td>$1,001 - $15,000</td><td>--</td></tr>
</tbody></table>"""


class ParseTest(unittest.TestCase):
    def test_house_ptr(self):
        self.assertEqual(disclosures.parse_house_ptr(HOUSE_PTR), [
            ("NVDA", "buy", date(2026, 1, 16), 375000.5),
            ("VZ", "sell", date(2026, 1, 30), 32500.5),  # row split by a page break
            ("BRK.B", "sell", date(2026, 2, 1), 50000000.0),
        ])

    def test_senate_ptr(self):
        self.assertEqual(disclosures.parse_senate_ptr(SENATE_PTR), [
            ("WFC", "buy", date(2026, 9, 1), 32500.5),
            ("AAPL", "sell", date(2026, 9, 3), 8000.5),
        ])


class RankingTest(unittest.TestCase):
    closes = {
        "UP": [(date(2026, 1, 1), 100.0), (date(2026, 6, 1), 150.0), (date(2026, 9, 1), 200.0)],
        "DN": [(date(2026, 1, 1), 100.0), (date(2026, 9, 1), 50.0)],
    }

    def test_price_on_uses_last_close(self):
        self.assertEqual(ranking.price_on(self.closes, "UP", date(2026, 7, 4)), 150.0)
        self.assertIsNone(ranking.price_on(self.closes, "UP", date(2025, 12, 31)))

    def test_sale_locks_in_return(self):
        trades = [T("A", "UP", "buy", date(2026, 1, 1)), T("A", "UP", "sell", date(2026, 6, 1))]
        self.assertAlmostEqual(ranking.performance(trades, self.closes).ret, 0.5)

    def test_rank_orders_by_return(self):
        trades = [T("A", "UP", "buy", date(2026, 1, 1))] * 2 + [T("B", "DN", "buy", date(2026, 1, 1))] * 3
        ranked = ranking.rank(trades, self.closes, n_active=5, min_priced_buys=1)
        self.assertEqual([r.politician_id for r in ranked], ["A", "B"])
        self.assertAlmostEqual(ranked[1].ret, -0.5)


class PortfolioTest(unittest.TestCase):
    def test_holdings_net_out_sells(self):
        trades = [T("A", "X", "buy", date(2026, 1, 1), 3000), T("A", "X", "sell", date(2026, 2, 1), 1000),
                  T("A", "Y", "buy", date(2026, 1, 1), 2000), T("A", "Z", "sell", date(2026, 1, 1), 500)]
        self.assertEqual(portfolio.target_weights(portfolio.implied_holdings(trades)), {"X": 0.5, "Y": 0.5})

    def test_plan_closes_extras_and_sells_first(self):
        orders = portfolio.plan({"X": 0.5, "Y": 0.5}, 1000, {"X": 700.0, "OLD": 100.0})
        self.assertEqual([str(o) for o in orders], ["OLD: close", "X: sell $200.00", "Y: buy $500.00"])


class DateTest(unittest.TestCase):
    def test_monday_looks_back_to_friday(self):
        self.assertEqual(previous_weekday(date(2026, 9, 28)), date(2026, 9, 25))


if __name__ == "__main__":
    unittest.main()
