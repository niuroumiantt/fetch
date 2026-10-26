"""Warm equity quotes for listed companies (US Nasdaq + non-US Yahoo chart).

Writes quote snapshots under the listed data root and optionally mirrors them
into an inresearch company-quotes cache directory. Provides no investment advice.
Skips companies marked quote_status=delisted and tickers that cannot be mapped.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote as urlquote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fetch.core.http import now
from fetch.teams.fetchfilings.listed import load_listed

US_TICKER = re.compile(r"(NASDAQ|NYSE):([A-Z][A-Z0-9.\-]{0,14})\Z")
# Home-market tickers → Yahoo Finance chart symbols.
YAHOO_SUFFIX = {
    "TWSE": ".TW",
    "TYO": ".T",
    "EPA": ".PA",
    "ETR": ".DE",
    "LON": ".L",
    "STO": ".ST",
    "HEL": ".HE",
    "KRX": ".KS",
    "SSE": ".SS",
}
NON_US_TICKER = re.compile(
    r"(" + "|".join(YAHOO_SUFFIX) + r"):([A-Z0-9.\-]{1,14})\Z", re.I)
BARE_CN = re.compile(r"(\d{6})\.(SS|SZ)\Z", re.I)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value):
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if not isinstance(value, str) or not re.fullmatch(r"[$+\-\d,.% ]+", value):
        return None
    try:
        n = float(value.replace("$", "").replace(",", "").replace("%", "").strip())
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def read_nasdaq(symbol, kind="info"):
    url = f"https://api.nasdaq.com/api/quote/{symbol}/{kind}?assetclass=stocks"
    # Nasdaq's public JSON endpoint expects a browser-like UA (same as inresearch).
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nasdaq.com/",
    })
    with build_opener(_NoRedirect()).open(req, timeout=10) as response:
        body = response.read(262145)
    if len(body) > 262144:
        raise ValueError("quote_response_too_large")
    return json.loads(body.decode("utf-8"))["data"]


def read_yahoo(symbol):
    """Latest daily bar via Yahoo chart API (stdlib JSON)."""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urlquote(symbol, safe="")
        + "?interval=1d&range=5d"
    )
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    with build_opener(_NoRedirect()).open(req, timeout=10) as response:
        body = response.read(262145)
    if len(body) > 262144:
        raise ValueError("quote_response_too_large")
    payload = json.loads(body.decode("utf-8"))
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        err = ((payload.get("chart") or {}).get("error") or {}).get("description")
        raise ValueError(err or "yahoo_chart_empty")
    return result


def normalize(symbol, info, summary=None):
    if not isinstance(info, dict) or str(info.get("symbol", "")).upper() != symbol:
        raise ValueError("quote_symbol_mismatch")
    primary = info.get("primaryData") or {}
    if not isinstance(primary, dict):
        raise ValueError("invalid_quote_data")
    price = _number(primary.get("lastSalePrice"))
    stamp = primary.get("lastTradeTimestamp")
    if price is None or price <= 0 or not isinstance(stamp, str) or not stamp.strip():
        raise ValueError("quote_missing_price_or_time")
    summary_data = (summary or {}).get("summaryData") or {}
    cap_data = summary_data.get("MarketCap") if isinstance(summary_data, dict) else None
    cap = _number(cap_data.get("value")) if isinstance(cap_data, dict) else None
    return {
        "symbol": symbol,
        "price": price,
        "currency": "USD",
        "market_cap": cap if cap and cap > 0 else None,
        "change": _number(primary.get("netChange")),
        "change_percent": _number(primary.get("percentageChange")),
        "as_of": stamp,
        "market_status": str(info.get("marketStatus") or "")[:60],
        "provider": "Nasdaq",
        "source_url": f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "retrieved_epoch": time.time(),
        "delay_note": "按提供方时间展示；不保证实时行情",
    }


def normalize_yahoo(symbol, chart):
    meta = chart.get("meta") if isinstance(chart, dict) else None
    if not isinstance(meta, dict):
        raise ValueError("invalid_yahoo_meta")
    price = _number(meta.get("regularMarketPrice"))
    if price is None or price <= 0:
        # fall back to last close in indicators
        closes = ((((chart.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or [])
        closes = [c for c in closes if isinstance(c, (int, float)) and c > 0]
        price = closes[-1] if closes else None
    if price is None or price <= 0:
        raise ValueError("quote_missing_price")
    ts = meta.get("regularMarketTime")
    if isinstance(ts, (int, float)) and ts > 0:
        as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    else:
        as_of = datetime.now(timezone.utc).isoformat()
    currency = str(meta.get("currency") or "")[:8] or None
    prev = _number(meta.get("chartPreviousClose") or meta.get("previousClose"))
    change = (price - prev) if prev is not None else None
    change_pct = ((change / prev) * 100.0) if change is not None and prev else None
    cap = _number(meta.get("marketCap"))
    exchange = str(meta.get("exchangeName") or meta.get("fullExchangeName") or "")[:40]
    return {
        "symbol": symbol,
        "price": float(price),
        "currency": currency,
        "market_cap": cap if cap and cap > 0 else None,
        "change": change,
        "change_percent": change_pct,
        "as_of": as_of,
        "market_status": exchange,
        "provider": "Yahoo",
        "source_url": f"https://finance.yahoo.com/quote/{urlquote(symbol, safe='')}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "retrieved_epoch": time.time(),
        "delay_note": "按提供方时间展示；不保证实时行情",
    }


def yahoo_symbol_for(ticker):
    """Map a non-US seed ticker onto a Yahoo chart symbol, or None."""
    if not ticker:
        return None
    bare = BARE_CN.fullmatch(ticker.strip())
    if bare:
        return f"{bare.group(1)}.{bare.group(2).upper()}"
    match = NON_US_TICKER.fullmatch(ticker.strip())
    if not match:
        return None
    exch, sym = match.group(1).upper(), match.group(2)
    return sym + YAHOO_SUFFIX[exch]


def us_listed(path=None):
    rows = []
    for company in load_listed(path)["records"]:
        ticker = company.get("ticker") or ""
        match = US_TICKER.fullmatch(ticker)
        if not match:
            continue
        rows.append({**company, "exchange": match.group(1), "symbol": match.group(2),
                     "provider": "nasdaq"})
    return rows


def non_us_listed(path=None):
    rows = []
    for company in load_listed(path)["records"]:
        if (company.get("quote_status") or "").lower() == "delisted":
            continue
        if US_TICKER.fullmatch(company.get("ticker") or ""):
            continue
        override = (company.get("yahoo_symbol") or "").strip()
        symbol = override or yahoo_symbol_for(company.get("ticker") or "")
        if not symbol:
            continue
        rows.append({**company, "symbol": symbol, "provider": "yahoo"})
    return rows


def quote_targets(path=None):
    return us_listed(path) + non_us_listed(path)


def quotes_root(data_root):
    return Path(data_root).expanduser() / "quotes"


def mirror_targets():
    """Candidate inresearch quote-cache directories on this collector."""
    home = Path.home()
    return [
        home / ".local/share/inresearch.ai/data/raw/company-quotes",
        home / "code/inresearch.ai/data/raw/company-quotes",
    ]


def refresh_quotes(*, data_root=None, listed_path=None, company_id=None, sleep=time.sleep,
                   reader=read_nasdaq, yahoo_reader=read_yahoo, mirror=True):
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/listed"
    out = quotes_root(root)
    out.mkdir(parents=True, exist_ok=True)
    companies = quote_targets(listed_path)
    if company_id:
        companies = [c for c in companies if c["company_id"] == company_id]
    results = []
    started = now()
    listed = load_listed(listed_path)["records"]
    delisted = sum(1 for c in listed if (c.get("quote_status") or "").lower() == "delisted")
    for company in companies:
        symbol = company["symbol"]
        cid = company["company_id"]
        provider = company["provider"]
        try:
            if provider == "nasdaq":
                info = reader(symbol, "info")
                try:
                    summary = reader(symbol, "summary")
                except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError):
                    summary = None
                value = normalize(symbol, info, summary)
            else:
                chart = yahoo_reader(symbol)
                value = normalize_yahoo(symbol, chart)
            value["company_id"] = cid
            value["ticker"] = company["ticker"]
            path = out / (cid + ".json")
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mirrored = []
            if mirror:
                for target_root in mirror_targets():
                    try:
                        target_root.mkdir(parents=True, exist_ok=True)
                        dest = target_root / (cid + ".json")
                        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                        mirrored.append(str(dest))
                    except OSError:
                        continue
            results.append({"company_id": cid, "symbol": symbol, "provider": provider,
                            "outcome": "success", "path": str(path), "mirrored": mirrored,
                            "price": value["price"], "currency": value.get("currency")})
        except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError) as error:
            results.append({"company_id": cid, "symbol": symbol, "provider": provider,
                            "outcome": "failure", "error_type": type(error).__name__})
        sleep(0.35)
    unsupported = len(listed) - len(quote_targets(listed_path)) - delisted
    return {
        "lane": "equity_quotes",
        "started_at": started,
        "finished_at": now(),
        "path": str(out),
        "counts": {
            "attempted": len(results),
            "success": sum(1 for r in results if r["outcome"] == "success"),
            "failure": sum(1 for r in results if r["outcome"] == "failure"),
            "nasdaq": sum(1 for r in results if r.get("provider") == "nasdaq"),
            "yahoo": sum(1 for r in results if r.get("provider") == "yahoo"),
            "unsupported": max(0, unsupported),
            "delisted": delisted,
        },
        "results": results,
    }
