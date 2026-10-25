"""Discover latest SEC periodic filings for the listed-company universe.

Writes a discoveries ledger under the team data root. Provides pointers and
runnable source dicts; provides no adoption and does not crawl local_ir here.
"""
from __future__ import annotations

import json
from pathlib import Path

from fetch import USER_AGENT
from fetch.core.failures import FlowError, classify
from fetch.core.http import Fetcher, now
from fetch.teams.fetchfilings.listed import sec_edgar_companies
from fetch.teams.fetchfilings.sec import (
    SUBMISSIONS_HOST,
    pick_latest_periodic,
    source_for_filing,
    submissions_url,
)


def discoveries_path(data_root):
    return Path(data_root).expanduser() / "discoveries" / "current.json"


def load_discoveries(data_root):
    path = discoveries_path(data_root)
    if not path.is_file():
        raise ValueError("discoveries ledger missing; run discover first")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError("discoveries ledger malformed")
    return value


def discovered_sources(data_root, *, company_id=None):
    """Flatten ok discovery rows into collect()-ready sources."""
    sources = []
    for row in load_discoveries(data_root)["records"]:
        if company_id and row.get("company_id") != company_id:
            continue
        if row.get("status") != "ok":
            continue
        for filing in row.get("filings") or []:
            source = filing.get("source")
            if source:
                sources.append(source)
    return sources


def _write_ledger(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def discover(*, data_root=None, company_id=None, listed_path=None, fetcher=None,
             respect_robots=True):
    """Fetch SEC submissions for each sec_edgar company; write discoveries/current.json."""
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/fetchfilings"
    companies = sec_edgar_companies(listed_path)
    if company_id:
        companies = [c for c in companies if c["company_id"] == company_id]
        if not companies:
            raise ValueError("company_id not in sec_edgar listed universe")

    client = fetcher or Fetcher(
        [SUBMISSIONS_HOST], delay_seconds=0.2, respect_robots=respect_robots, user_agent=USER_AGENT)

    records = []
    started = now()
    for company in companies:
        cik = company["cik"]
        url = submissions_url(cik)
        try:
            result = client.get(url)
            payload = json.loads(result["bytes"].decode("utf-8"))
            filings = pick_latest_periodic(payload, cik=cik)
            if not filings:
                records.append({
                    "company_id": company["company_id"],
                    "name": company.get("name"),
                    "ticker": company.get("ticker"),
                    "cik": cik,
                    "channel": "sec_edgar",
                    "status": "no_periodic_filing",
                    "submissions_url": url,
                    "filings": [],
                })
                continue
            enriched = []
            for filing in filings:
                source = source_for_filing(company, filing)
                enriched.append({**filing, "source": source})
            records.append({
                "company_id": company["company_id"],
                "name": company.get("name"),
                "ticker": company.get("ticker"),
                "cik": cik,
                "channel": "sec_edgar",
                "status": "ok",
                "submissions_url": url,
                "issuer_name": payload.get("name"),
                "filings": enriched,
            })
        except (FlowError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            failure = classify(error, "discover")
            records.append({
                "company_id": company["company_id"],
                "name": company.get("name"),
                "ticker": company.get("ticker"),
                "cik": cik,
                "channel": "sec_edgar",
                "status": "fetch_failed",
                "submissions_url": url,
                "failure": failure,
                "filings": [],
            })

    ok = sum(1 for r in records if r["status"] == "ok")
    filing_count = sum(len(r["filings"]) for r in records)
    ledger = {
        "version": 1,
        "team": "fetchfilings",
        "discovered_at": started,
        "finished_at": now(),
        "universe": "listed_companies",
        "channel": "sec_edgar",
        "counts": {
            "companies": len(records),
            "ok": ok,
            "no_periodic_filing": sum(1 for r in records if r["status"] == "no_periodic_filing"),
            "fetch_failed": sum(1 for r in records if r["status"] == "fetch_failed"),
            "filings": filing_count,
        },
        "records": records,
    }
    path = _write_ledger(discoveries_path(root), ledger)
    return {"path": str(path), **ledger}
