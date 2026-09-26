# borsa

Mirrors the stock trades of the best-performing active member of Congress in an Alpaca **paper** account.

Every run:
1. Pulls the last 12 months of stock trade disclosures (Periodic Transaction Reports) from the official sources: the [House Clerk](https://disclosures-clerk.house.gov/FinancialDisclosure) (yearly XML index + PTR PDFs) and the [Senate eFD](https://efdsearch.senate.gov). Scanned paper filings are skipped. Parsed filings are cached in `.cache/`, so later runs only download new reports.
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

Network access needed: `paper-api.alpaca.markets`, `data.alpaca.markets`, `api.resend.com`, `disclosures-clerk.house.gov`, `efdsearch.senate.gov`.

### Credentials

`ALPACA_API_KEY`, `ALPACA_SECRET_KEY` and `RESEND_API_KEY` are optional. In the Claude Code cloud environment the egress proxy injects the auth headers (`APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` for `*.alpaca.markets`, `Authorization: Bearer` for `api.resend.com`), so no keys are needed in the environment. For local runs, put them in `.env`.

`EMAIL_TO` is a plain environment variable. Without a verified Resend domain, the default sender `onboarding@resend.dev` only delivers to your own Resend account address. SMTP (`SMTP_USER` + `SMTP_PASSWORD`) is used only when no Resend key is set, and only works outside the cloud sandbox.

## Schedule

The bot runs on weekdays at 9:30 ET via a Claude Code cloud Routine that runs `python -m borsa`. At 9:30 the market may still report closed for a few seconds; in that case the orders are listed in the email but not sent.

## Caveats

- Disclosures can be filed up to 45 days after a trade, and sizes are dollar ranges (the midpoint is used).
- Holdings before the 12-month window aren't visible, so the mirrored portfolio is an approximation.
- If the leader changes, the next run rotates the whole portfolio.

Tests: `python -m unittest discover -s tests -t .`
