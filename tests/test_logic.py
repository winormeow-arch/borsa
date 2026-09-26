import unittest
from datetime import date

from borsa import portfolio, ranking
from borsa.__main__ import previous_weekday
from borsa.capitoltrades import Trade, parse_trade


def T(pid, ticker, kind, d, value=1000.0, pub=None):
    return Trade(f"{pid}{ticker}{d}{kind}", pid, f"Member {pid}", ticker, kind, d, pub or d, value)


class ParseTest(unittest.TestCase):
    def test_parses_buy(self):
        t = parse_trade({
            "_txId": 1, "_politicianId": "P1", "txType": "buy", "value": 8000,
            "txDate": "2026-03-01", "pubDate": "2026-03-20T13:00:00Z",
            "issuer": {"issuerTicker": "NVDA:US"},
            "politician": {"firstName": "Ann", "lastName": "Lee"},
        })
        self.assertEqual((t.ticker, t.tx_type, t.politician, t.pub_date), ("NVDA", "buy", "Ann Lee", date(2026, 3, 20)))

    def test_skips_non_stock_and_foreign(self):
        base = {"_txId": 1, "txType": "buy", "value": 1, "txDate": "2026-01-01", "pubDate": "2026-01-02"}
        self.assertIsNone(parse_trade({**base, "issuer": {"issuerTicker": None}}))
        self.assertIsNone(parse_trade({**base, "issuer": {"issuerTicker": "SAP:GR"}}))
        self.assertIsNone(parse_trade({**base, "txType": "exchange", "issuer": {"issuerTicker": "A:US"}}))


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
