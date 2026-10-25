"""Weekly multi-lane refresh for the listed-company universe.

Runs company-scoped lanes together: SEC filings, US equity quotes, IR pages,
and a status pass for fetchspec catalog overlap. Public-stats / research-pub /
GPU-cloud quote bootstraps stay on their own calendars.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fetch import ROOT
from fetch.core.http import now
from fetch.listed.ir import refresh_ir
from fetch.listed.quotes import refresh_quotes
from fetch.teams.fetchfilings.listed import load_listed
from fetch.teams.fetchfilings.refresh import refresh as refresh_filings

# Product-catalog companies that also sit in the listed-50 freeze.
SPEC_OVERLAP = frozenset({"amd", "cambricon", "nvidia", "supermicro"})


def _head_revision():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def specs_status(listed_path=None):
    rows = []
    for company in load_listed(listed_path)["records"]:
        cid = company["company_id"]
        if cid not in SPEC_OVERLAP:
            continue
        rows.append({
            "company_id": cid,
            "team": "fetchspec",
            "status": "catalog_registered",
            "note": "product catalog company; deep spec crawl stays on fetchspec adapters",
        })
    return {
        "lane": "product_specs",
        "team": "fetchspec",
        "counts": {"overlap": len(rows)},
        "records": rows,
    }


def refresh_listed(*, data_root=None, company_id=None, listed_path=None, respect_robots=True,
                   prior_disclosures=None, lanes=None):
    """Run selected listed lanes. Default = filings + quotes + ir + specs status."""
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/listed"
    root.mkdir(parents=True, exist_ok=True)
    wanted = set(lanes or ("filings", "quotes", "ir", "specs"))
    started = now()
    revision = _head_revision()
    listed = load_listed(listed_path)
    report = {
        "universe": "listed_companies",
        "cadence": (listed.get("policy") or {}).get("scheduled_phase") or "weekly",
        "started_at": started,
        "lanes_requested": sorted(wanted),
        "companies": len(listed["records"]),
    }

    if "filings" in wanted:
        filings_root = root / "fetchfilings"
        report["filings"] = refresh_filings(
            data_root=filings_root,
            company_id=company_id,
            listed_path=listed_path,
            respect_robots=respect_robots,
            prior_disclosures=prior_disclosures,
        )

    if "quotes" in wanted:
        report["quotes"] = refresh_quotes(
            data_root=root, listed_path=listed_path, company_id=company_id)

    if "ir" in wanted:
        report["ir"] = refresh_ir(
            data_root=root, listed_path=listed_path, company_id=company_id,
            respect_robots=respect_robots, revision=revision)

    if "specs" in wanted:
        report["specs"] = specs_status(listed_path)

    report["finished_at"] = now()
    path = root / "refresh" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["path"] = str(path)
    return report
