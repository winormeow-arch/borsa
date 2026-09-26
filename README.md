# borsa

Mirrors the stock trades of the best-performing active member of Congress in an Alpaca **paper** account.

Every run:
1. Pulls the last 12 months of disclosures from [Capitol Trades](https://www.capitoltrades.com).
2. Picks the `ACTIVE_MEMBERS` (default 20) members with the most trades and ranks them by the dollar-weighted return of their disclosed buys (priced with Alpaca market data).
3. Estimates the leader's current holdings (disclosed buys minus sells) and rebalances the account to those weights using `MIRROR_ALLOCATION` of equity. **Positions not in the target get closed.**
4. Emails a summary: ranking, target weights, orders, and new disclosures since the previous weekday.

## Setup

```sh
pip install -r requirements.txt
cp .env.example .env   # fill in keys; .env is git-ignored
python -m borsa --dry-run --no-email   # check the plan first
python -m borsa
```

Only paper URLs are allowed unless you pass `--allow-live`.

Network access needed: `bff.capitoltrades.com`, `paper-api.alpaca.markets`, `data.alpaca.markets`, and your SMTP host.

## Caveats

- Disclosures can be filed up to 45 days after a trade, and sizes are dollar ranges (the midpoint is used).
- Holdings before the 12-month window aren't visible, so the mirrored portfolio is an approximation.
- If the leader changes, the next run rotates the whole portfolio.

Tests: `python -m unittest discover -s tests -t .`
