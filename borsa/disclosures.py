"""Congressional stock trade disclosures from the official sources.

- House: Clerk of the House yearly index (XML) + each electronic Periodic
  Transaction Report PDF (text-extracted). Scanned paper filings are skipped.
- Senate: eFD search (efdsearch.senate.gov) PTR pages. Paper filings are skipped.

Parsed filings are cached in `.cache/filings.json` (filings never change once
published), so only new reports are downloaded on later runs.
"""
import html
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

HOUSE_INDEX = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
SENATE = "https://efdsearch.senate.gov"
CACHE = Path(__file__).resolve().parent.parent / ".cache" / "filings.json"
CACHE_VERSION = 1
USER_AGENT = "Mozilla/5.0 (compatible; borsa/1.0)"


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


@dataclass(frozen=True)
class Filing:
    key: str  # "H:<doc id>" or "S:<report uuid>"
    politician_id: str
    politician: str
    filed: date
    url: str


def _mdy(s: str) -> date:
    return datetime.strptime(s.strip(), "%m/%d/%Y").date()


def _amount(low: str, high: Optional[str]) -> float:
    low_v = float(low.replace(",", ""))
    return (low_v + float(high.replace(",", ""))) / 2 if high else low_v


def _ticker(raw: str) -> Optional[str]:
    t = raw.strip().upper().replace("/", ".")
    return t if re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(\.[A-Z])?", t) else None


# --- House -----------------------------------------------------------------

_HOUSE_TX = re.compile(
    r"(?<![A-Za-z(])(P|S\s*\(partial\)|S|E)\s+(\d\d/\d\d/\d{4})\s*(\d\d/\d\d/\d{4})\s*"
    r"(?:Over\s+)?\$([\d,]+)(?:\s*-\s*(?:\$([\d,]+))?)?"
)
# Repeated on every page; removing it rejoins rows split by a page break.
_PAGE_HEADER = re.compile(
    r"Filing ID #\d+\s*|ID\s+Owner\s+Asset\s+Transaction\s+Type\s+Date\s+Notification\s+Date\s+"
    r"Amount\s+Cap\.\s+Gains\s+>\s+\$200\?\s*"
)
_HOUSE_TICKER = re.compile(r"\(([A-Z][A-Z0-9./]{0,7})\)")
_ASSET_TYPE = re.compile(r"\[([A-Z]{2})\]")
_FILING_STATUS = re.compile(r"^F\W+S\W*:", re.M)


def parse_house_ptr(text: str) -> list[tuple[str, str, date, float]]:
    """(ticker, buy|sell, trade date, value) for each stock row in a PTR's text."""
    text = _PAGE_HEADER.sub(" ", text.replace("\x00", " "))
    rows, prev_end = [], 0
    matches = list(_HOUSE_TX.finditer(text))
    for i, m in enumerate(matches):
        chunk = text[prev_end:m.start()]
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        tail = text[m.end():next_start]
        status = _FILING_STATUS.search(tail)
        tail = tail[:status.start()] if status else ""
        prev_end = m.end() + (status.end() if status else 0)
        # A page break can push the end of the asset name, "[ST]" and the
        # upper end of the amount range below the transaction line.
        kinds = _ASSET_TYPE.findall(tail) or _ASSET_TYPE.findall(chunk)
        tickers = _HOUSE_TICKER.findall(tail) or _HOUSE_TICKER.findall(chunk)
        high = m.group(5)
        if not high and m.group(0).rstrip().endswith("-"):
            more = re.search(r"\$([\d,]+)", tail)
            high = more.group(1) if more else None
        kind = m.group(1)[0]
        if not kinds or kinds[-1] != "ST" or not tickers or kind == "E":
            continue
        ticker = _ticker(tickers[-1])
        if ticker:
            rows.append((ticker, "buy" if kind == "P" else "sell", _mdy(m.group(2)), _amount(m.group(4), high)))
    return rows


def house_filings(session: requests.Session, since: date, today: date) -> list[Filing]:
    out = []
    for year in range(since.year, today.year + 1):
        resp = session.get(HOUSE_INDEX.format(year=year), timeout=60)
        resp.raise_for_status()
        xml = zipfile.ZipFile(io.BytesIO(resp.content)).read(f"{year}FD.xml").decode("utf-8-sig")
        for m in ET.fromstring(xml):
            f = {c.tag: (c.text or "").strip() for c in m}
            # Electronic filings have 200xxxxx IDs; others are scanned paper.
            if f.get("FilingType") != "P" or not f.get("DocID", "").startswith("2"):
                continue
            filed = _mdy(f["FilingDate"])
            if filed < since:
                continue
            name = " ".join(filter(None, [f.get("First"), f.get("Last"), f.get("Suffix")]))
            out.append(Filing(
                key=f"H:{f['DocID']}",
                politician_id=f"H:{f.get('Last')}:{f.get('First')}:{f.get('StateDst')}",
                politician=f"{name} (H-{f.get('StateDst', '')[:2]})",
                filed=filed,
                url=HOUSE_PTR.format(year=year, doc_id=f["DocID"]),
            ))
    return out


def _house_rows(session: requests.Session, f: Filing) -> list:
    from pypdf import PdfReader  # heavy import; only needed for new filings

    resp = session.get(f.url, timeout=60)
    resp.raise_for_status()
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages)
    return parse_house_ptr(text)


# --- Senate ----------------------------------------------------------------

_LINK = re.compile(r'href="(/search/view/(ptr|paper)/([^/"]+)/)"')
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")


def senate_session() -> requests.Session:
    """A session that has accepted the eFD usage agreement."""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    home = s.get(f"{SENATE}/search/home/", timeout=30)
    home.raise_for_status()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
    if token:
        s.post(f"{SENATE}/search/home/", timeout=30, headers={"Referer": f"{SENATE}/search/home/"},
               data={"prohibition_agreement": "1", "csrfmiddlewaretoken": token.group(1)}).raise_for_status()
    return s


def senate_filings(s: requests.Session, since: date) -> list[Filing]:
    out, start = [], 0
    while True:
        csrf = s.cookies.get("csrftoken", "")
        resp = s.post(f"{SENATE}/search/report/data/", timeout=60,
                      headers={"Referer": f"{SENATE}/search/", "X-CSRFToken": csrf},
                      data={"start": start, "length": 100, "report_types": "[11]", "filer_types": "[]",
                            "submitted_start_date": f"{since:%m/%d/%Y} 00:00:00", "submitted_end_date": "",
                            "candidate_state": "", "senator_state": "", "office_id": "",
                            "first_name": "", "last_name": "", "csrfmiddlewaretoken": csrf})
        resp.raise_for_status()
        body = resp.json()
        for first, last, _office, link, filed in body.get("data") or []:
            m = _LINK.search(link)
            if not m or m.group(2) != "ptr":
                continue  # paper filings are scanned images
            first, last = html.unescape(first).strip(), html.unescape(last).strip()
            out.append(Filing(
                key=f"S:{m.group(3)}",
                politician_id=f"S:{last}:{first}",
                politician=f"{first} {last} (Sen.)",
                filed=_mdy(filed),
                url=SENATE + m.group(1),
            ))
        start += 100
        if start >= int(body.get("recordsTotal") or 0):
            return out


def parse_senate_ptr(page: str) -> list[tuple[str, str, date, float]]:
    rows = []
    tbody = page.split("<tbody>", 1)[-1]
    for row in _ROW.findall(tbody):
        cells = [html.unescape(_TAG.sub(" ", c)).split() for c in _CELL.findall(row)]
        cells = [" ".join(c) for c in cells]
        if len(cells) < 8:
            continue
        _, tx_date, _owner, ticker, _asset, asset_type, kind, amount = cells[:8]
        ticker = _ticker(ticker) if ticker != "--" else None
        if not ticker or asset_type != "Stock":
            continue
        side = "buy" if kind.startswith("Purchase") else "sell" if kind.startswith("Sale") else None
        amt = re.search(r"\$([\d,]+)(?:\s*-\s*\$([\d,]+))?", amount)
        if side and amt:
            rows.append((ticker, side, _mdy(tx_date), _amount(amt.group(1), amt.group(2))))
    return rows


def _senate_rows(s: requests.Session, f: Filing) -> list:
    resp = s.get(f.url, timeout=60)
    resp.raise_for_status()
    if "<tbody>" not in resp.text:
        raise RuntimeError(f"unexpected Senate PTR page for {f.url}")
    return parse_senate_ptr(resp.text)


# --- combined --------------------------------------------------------------

def _load_cache() -> dict:
    try:
        data = json.loads(CACHE.read_text())
        return data["filings"] if data.get("version") == CACHE_VERSION else {}
    except (OSError, ValueError, KeyError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps({"version": CACHE_VERSION, "filings": cache}))
    except OSError:
        pass


def fetch_trades(days: int = 365, today: Optional[date] = None, log=print) -> list[Trade]:
    """All House and Senate stock buys/sells with a trade date in the last `days` days."""
    today = today or date.today()
    since = today - timedelta(days=days)
    house = requests.Session()
    house.headers["User-Agent"] = USER_AGENT
    senate = senate_session()
    filings = [(house, f, _house_rows) for f in house_filings(house, since, today)]
    filings += [(senate, f, _senate_rows) for f in senate_filings(senate, since)]

    cache = _load_cache()
    todo = [x for x in filings if x[1].key not in cache]
    failed = []

    def work(item):
        session, f, parse = item
        try:
            return f.key, [(t, k, d.isoformat(), v) for t, k, d, v in parse(session, f)]
        except Exception as exc:  # one bad filing shouldn't sink the run
            failed.append(f"{f.key}: {exc}")
            return f.key, None

    with ThreadPoolExecutor(8) as pool:
        for key, rows in pool.map(work, todo):
            if rows is not None:
                cache[key] = rows
    _save_cache(cache)
    n_house = sum(f.key.startswith("H:") for _, f, _ in filings)
    log(f"Disclosures: {n_house} House + {len(filings) - n_house} Senate electronic PTRs filed since {since} "
        f"({len(todo)} downloaded, {len(failed)} failed)")
    for msg in failed[:5]:
        log(f"  failed {msg}")

    trades = []
    for _, f, _ in filings:
        for i, (ticker, kind, tx_date, value) in enumerate(cache.get(f.key) or []):
            d = date.fromisoformat(tx_date)
            if d >= since:
                trades.append(Trade(f"{f.key}:{i}", f.politician_id, f.politician, ticker, kind, d, f.filed, value))
    return trades
