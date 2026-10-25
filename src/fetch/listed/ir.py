"""Fetch official investor-relations landing pages for listed companies.

Stores HTML originals under the listed data root. Provides no accounting
extraction and skips companies without an https IR URL.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from fetch import USER_AGENT
from fetch.collect import collect
from fetch.core.failures import classify
from fetch.core.http import now
from fetch.teams.fetchfilings.listed import load_listed


def ir_companies(path=None):
    rows = []
    for company in load_listed(path)["records"]:
        url = (company.get("ir_url") or "").strip()
        if not url.startswith("https://"):
            continue
        host = urlsplit(url).hostname
        if not host:
            continue
        rows.append({**company, "ir_url": url, "ir_host": host})
    return rows


def source_for_ir(company):
    host = company["ir_host"]
    cid = company["company_id"]
    return {
        "team": "fetchfilings",
        "id": f"fetchfilings-ir-{cid}",
        "publisher": company.get("name") or cid,
        "title": f"{company.get('name') or cid} investor relations",
        "url": company["ir_url"],
        "hosts": [host],
        "native_id": f"ir:{cid}",
        "extension": "html",
        "content_type": "text/html",
        "adapter": "ir_page",
        "adapter_version": "v1",
        "cadence": "weekly",
        "execution_host": "macmini",
        "scheduled": False,
        "company_id": cid,
    }


def refresh_ir(*, data_root=None, listed_path=None, company_id=None, respect_robots=True,
               revision=None, collect_pages=True):
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/listed"
    companies = ir_companies(listed_path)
    if company_id:
        companies = [c for c in companies if c["company_id"] == company_id]
    started = now()
    results = []
    if collect_pages:
        for company in companies:
            source = source_for_ir(company)
            try:
                # IR pages are stored under listed/ir originals via collect data_root
                result = collect(source, root / "ir", respect_robots=respect_robots, revision=revision)
                results.append({
                    "company_id": company["company_id"],
                    "url": company["ir_url"],
                    "outcome": "success",
                    "delivery_id": result.get("delivery_id"),
                    "replayed": bool(result.get("replayed")),
                    "package": result.get("package"),
                })
            except Exception as error:  # noqa: BLE001 — classified below
                results.append({
                    "company_id": company["company_id"],
                    "url": company["ir_url"],
                    "outcome": "failure",
                    "failure": classify(error, "listed-ir"),
                })
    ledger = {
        "lane": "investor_relations",
        "started_at": started,
        "finished_at": now(),
        "counts": {
            "companies_with_ir": len(companies),
            "attempted": len(results),
            "success": sum(1 for r in results if r["outcome"] == "success"),
            "failure": sum(1 for r in results if r["outcome"] == "failure"),
        },
        "results": results,
    }
    path = root / "ir" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger["path"] = str(path)
    return ledger
