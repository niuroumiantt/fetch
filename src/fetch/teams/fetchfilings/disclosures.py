"""Build a company-page disclosures projection from discoveries.

Provides original-link rows for inresearch company windows. Provides no
adoption and does not invent SEC filings for local_ir companies.
"""
from __future__ import annotations

import json
from pathlib import Path

from fetch.core.http import now
from fetch.teams.fetchfilings.discover import load_discoveries
from fetch.teams.fetchfilings.listed import load_listed, local_ir_companies


def disclosures_path(data_root):
    return Path(data_root).expanduser() / "disclosures" / "current.json"


def _period_label(filing):
    rd = filing.get("report_date") or ""
    form = filing.get("form") or ""
    klass = filing.get("class") or ""
    if not rd or len(rd) < 7:
        return form or "unknown"
    year, month = int(rd[:4]), int(rd[5:7])
    if klass == "annual":
        return str(year) if form in ("20-F", "40-F") else f"FY{year}"
    return f"{year} Q{(month - 1) // 3 + 1}"


def _from_filing(filing):
    return {
        "period": _period_label(filing),
        "kind": "annual" if filing.get("class") == "annual" else "quarterly",
        "period_end": filing.get("report_date") or filing.get("filing_date"),
        "form": filing["form"],
        "url": filing["document_url"],
        "source": "SEC EDGAR",
        "summary_status": "original_link_only",
    }


def build_disclosures(data_root, *, listed_path=None, prior_path=None):
    """Merge SEC discoveries with listed local_ir IR shortcuts and optional prior history."""
    listed = load_listed(listed_path)
    discoveries = load_discoveries(data_root)
    by_disc = {row["company_id"]: row for row in discoveries.get("records") or []}
    prior = {}
    if prior_path and Path(prior_path).is_file():
        prior_doc = json.loads(Path(prior_path).read_text(encoding="utf-8"))
        prior = {row["company_id"]: row for row in prior_doc.get("records") or []}
    elif disclosures_path(data_root).is_file():
        prior_doc = json.loads(disclosures_path(data_root).read_text(encoding="utf-8"))
        prior = {row["company_id"]: row for row in prior_doc.get("records") or []}

    checked = (discoveries.get("finished_at") or now())[:10]
    records = []
    for company in listed["records"]:
        cid = company["company_id"]
        prev = prior.get(cid, {})
        financials = []
        status = "pending"
        if company.get("channel") == "sec_edgar":
            disc = by_disc.get(cid)
            if disc and disc.get("status") == "ok":
                financials = [_from_filing(f) for f in disc.get("filings") or []]
                status = "ok"
                seen = {(f["kind"], f.get("period_end")) for f in financials}
                seen_urls = {f["url"] for f in financials}
                for row in prev.get("financials") or []:
                    url = row.get("url") or ""
                    key = (row.get("kind"), row.get("period_end"))
                    if url in seen_urls or ("sec.gov" in url and key in seen):
                        continue
                    financials.append({k: row[k] for k in (
                        "period", "kind", "period_end", "form", "url", "source", "summary_status"
                    ) if k in row})
                    seen.add(key)
                    seen_urls.add(url)
            elif disc:
                status = disc.get("status") or "fetch_failed"
                financials = list(prev.get("financials") or [])
            else:
                financials = list(prev.get("financials") or [])
        else:
            status = "local_ir"
            ir = (company.get("ir_url") or "").strip()
            if ir.startswith("https://"):
                financials = [{
                    "period": "IR",
                    "kind": "annual",
                    "period_end": None,
                    "form": "IR",
                    "url": ir,
                    "source": "official IR",
                    "summary_status": "original_link_only",
                }]
            else:
                financials = list(prev.get("financials") or [])
                if not financials:
                    status = "local_ir_no_url"
        if not financials and not prev.get("product_lines"):
            if status in ("local_ir_no_url", "no_periodic_filing", "fetch_failed"):
                records.append({
                    "company_id": cid,
                    "checked_at": checked,
                    "product_lines": prev.get("product_lines") or [],
                    "financials": [],
                    "channel": company.get("channel"),
                    "discovery_status": status,
                })
            continue
        records.append({
            "company_id": cid,
            "checked_at": checked if status in ("ok", "local_ir") else prev.get("checked_at", checked),
            "product_lines": prev.get("product_lines") or [],
            "financials": financials,
            "channel": company.get("channel"),
            "discovery_status": status,
        })

    # Ensure every local_ir company appears even when skipped above
    have = {r["company_id"] for r in records}
    for company in local_ir_companies(listed_path):
        if company["company_id"] in have:
            continue
        records.append({
            "company_id": company["company_id"],
            "checked_at": checked,
            "product_lines": [],
            "financials": [],
            "channel": "local_ir",
            "discovery_status": "local_ir_no_url",
        })

    return {
        "version": 1,
        "team": "fetchfilings",
        "cadence": "weekly",
        "built_at": now(),
        "universe": "listed_companies",
        "counts": {
            "companies": len(records),
            "with_financials": sum(1 for r in records if r.get("financials")),
            "sec_ok": sum(1 for r in records if r.get("discovery_status") == "ok"),
            "local_ir": sum(1 for r in records if r.get("channel") == "local_ir"),
        },
        "records": records,
    }


def write_disclosures(data_root, payload=None, **kwargs):
    root = Path(data_root).expanduser()
    payload = payload or build_disclosures(root, **kwargs)
    path = disclosures_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), **payload}
