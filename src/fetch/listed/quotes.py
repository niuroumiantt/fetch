"""Warm Nasdaq equity quotes for listed companies with US tickers.

Writes quote snapshots under the listed data root and optionally mirrors them
into an inresearch company-quotes cache directory. Provides no investment advice
and does not cover non-US exchanges.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fetch import USER_AGENT
from fetch.core.http import now
from fetch.teams.fetchfilings.listed import load_listed

US_TICKER = re.compile(r"(NASDAQ|NYSE):([A-Z][A-Z0-9.\-]{0,14})\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value):
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


def us_listed(path=None):
    rows = []
    for company in load_listed(path)["records"]:
        ticker = company.get("ticker") or ""
        match = US_TICKER.fullmatch(ticker)
        if not match:
            continue
        rows.append({**company, "exchange": match.group(1), "symbol": match.group(2)})
    return rows


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
                   reader=read_nasdaq, mirror=True):
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/listed"
    out = quotes_root(root)
    out.mkdir(parents=True, exist_ok=True)
    companies = us_listed(listed_path)
    if company_id:
        companies = [c for c in companies if c["company_id"] == company_id]
    results = []
    started = now()
    for company in companies:
        symbol = company["symbol"]
        cid = company["company_id"]
        try:
            info = reader(symbol, "info")
            try:
                summary = reader(symbol, "summary")
            except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError):
                summary = None
            value = normalize(symbol, info, summary)
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
            results.append({"company_id": cid, "symbol": symbol, "outcome": "success",
                            "path": str(path), "mirrored": mirrored, "price": value["price"]})
        except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError) as error:
            results.append({"company_id": cid, "symbol": symbol, "outcome": "failure",
                            "error_type": type(error).__name__})
        sleep(0.35)
    return {
        "lane": "equity_quotes",
        "started_at": started,
        "finished_at": now(),
        "path": str(out),
        "counts": {
            "attempted": len(results),
            "success": sum(1 for r in results if r["outcome"] == "success"),
            "failure": sum(1 for r in results if r["outcome"] == "failure"),
            "unsupported_non_us": len(load_listed(listed_path)["records"]) - len(us_listed(listed_path)),
        },
        "results": results,
    }
