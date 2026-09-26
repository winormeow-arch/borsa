"""Daily run: rank Congress by 12-month returns, mirror the leader, email a summary.

    python -m borsa            # rank, rebalance the paper account, email summary
    python -m borsa --dry-run  # everything except placing orders
"""
import argparse
import math
import sys
from datetime import date, timedelta

from . import config, disclosures, notify, portfolio, ranking
from .alpaca import Alpaca


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def execute(api: Alpaca, orders, positions: dict, closes) -> list[str]:
    log = []
    for o in orders:
        try:
            if o.close:
                api.close_position(o.symbol)
                log.append(f"OK   {o}")
                continue
            asset = api.asset(o.symbol)
            if not asset or not asset.get("tradable"):
                log.append(f"SKIP {o} (not tradable on Alpaca)")
                continue
            price = float(positions.get(o.symbol, {}).get("current_price") or 0) or ranking.latest_price(closes, o.symbol)
            if o.side == "buy" and asset.get("fractionable"):
                api.market_order(o.symbol, "buy", notional=o.dollars)
            else:
                qty = o.dollars / price
                if not asset.get("fractionable"):
                    qty = math.floor(qty)
                if qty <= 0:
                    log.append(f"SKIP {o} (less than one share, not fractionable)")
                    continue
                api.market_order(o.symbol, o.side, qty=qty)
            log.append(f"OK   {o}")
        except Exception as exc:  # keep going; report every failure in the summary
            log.append(f"FAIL {o}: {exc}")
    return log


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="borsa")
    parser.add_argument("--dry-run", action="store_true", help="don't place orders")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--allow-live", action="store_true", help="permit a non-paper Alpaca URL")
    args = parser.parse_args(argv)

    cfg = config.load()
    if not cfg.is_paper and not args.allow_live:
        raise SystemExit(f"Refusing to trade against non-paper URL {cfg.alpaca_base_url}")
    api = Alpaca(cfg)
    today = date.today()
    lines = [f"Congress mirror run — {today:%A %Y-%m-%d}", ""]

    trades = disclosures.fetch_trades(365, today, log=lines.append)
    if not trades:
        raise SystemExit("No stock trades parsed from House/Senate disclosures")
    tickers = sorted({t.ticker for t in trades})
    closes = api.daily_closes(tickers, today - timedelta(days=380))
    ranked = ranking.rank(trades, closes, cfg.active_members)
    if not ranked:
        raise SystemExit("No members had enough priced trades to rank")
    leader = ranked[0]

    lines += [""]
    lines.append(f"Top {len(ranked)} of the {cfg.active_members} most active members, by 12-month return on disclosed buys:")
    for i, r in enumerate(ranked[:10], 1):
        lines.append(f"  {i:2}. {r.politician:<28} {r.ret:+7.1%}  ({r.trades} trades, {r.priced_buys} scored buys)")
    lines += ["", f"Mirroring: {leader.politician}"]

    leader_trades = [t for t in trades if t.politician_id == leader.politician_id]
    weights = portfolio.target_weights(portfolio.implied_holdings(leader_trades))
    lines.append("Target weights:")
    lines += [f"  {s:<6} {w:6.1%}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])]

    account = api.account()
    equity = float(account["equity"])
    positions = api.positions()
    orders = portfolio.plan(
        weights, equity * cfg.mirror_allocation,
        {s: float(p["market_value"]) for s, p in positions.items()},
    )
    lines += ["", f"Account equity ${equity:,.2f}; allocating {cfg.mirror_allocation:.0%}."]
    if args.dry_run:
        lines.append("Dry run — planned orders:")
        lines += [f"  {o}" for o in orders] or ["  (none)"]
    elif not api.clock().get("is_open"):
        lines.append("Market is closed — no orders placed. Planned:")
        lines += [f"  {o}" for o in orders] or ["  (none)"]
    else:
        lines.append("Orders:")
        lines += [f"  {l}" for l in execute(api, orders, positions, closes)] or ["  (none)"]

    since = previous_weekday(today)
    ranked_ids = {r.politician_id for r in ranked}
    new = sorted(
        (t for t in trades if t.pub_date >= since and t.politician_id in ranked_ids),
        key=lambda t: (t.politician_id != leader.politician_id, t.politician, t.ticker),
    )
    lines += ["", f"New disclosures from ranked members published since {since}: {len(new)}"]
    for t in new:
        star = "*" if t.politician_id == leader.politician_id else " "
        lines.append(f" {star}{t.politician:<28} {t.tx_type:<4} {t.ticker:<6} ~${t.value:>11,.0f}  traded {t.tx_date}")
    lines += ["", "Disclosures are filed up to 45 days after the trade and sizes are ranges;",
              "returns and holdings are estimates from disclosed trades only."]

    summary = "\n".join(lines)
    print(summary)
    if cfg.email_enabled and not args.no_email:
        prefix = "[DRY RUN] " if args.dry_run else ""
        notify.send_email(cfg, f"{prefix}Congress mirror {today}: {leader.politician}, {len(new)} new disclosures", summary)
    elif not args.no_email:
        print("\n(email not configured; set EMAIL_TO)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
