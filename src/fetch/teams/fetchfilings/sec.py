"""SEC EDGAR submissions helpers for fetchfilings.

Provides latest periodic filing pointers (form, accession, primary document URL)
from a submissions JSON body. Provides no accounting facts and does not invent
filings when none match.
"""
from __future__ import annotations

ANNUAL_FORMS = ("10-K", "20-F", "40-F")
QUARTERLY_FORMS = ("10-Q",)
PERIODIC_FORMS = ANNUAL_FORMS + QUARTERLY_FORMS

SUBMISSIONS_HOST = "data.sec.gov"
ARCHIVE_HOST = "www.sec.gov"


def pad_cik(cik):
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError("cik required")
    return digits.zfill(10)


def submissions_url(cik):
    return f"https://{SUBMISSIONS_HOST}/submissions/CIK{pad_cik(cik)}.json"


def archive_document_url(cik, accession, primary_document):
    cik_int = str(int(pad_cik(cik)))
    acc = accession.replace("-", "")
    doc = primary_document.lstrip("/")
    return f"https://{ARCHIVE_HOST}/Archives/edgar/data/{cik_int}/{acc}/{doc}"


def archive_index_url(cik, accession):
    cik_int = str(int(pad_cik(cik)))
    acc = accession.replace("-", "")
    return f"https://{ARCHIVE_HOST}/Archives/edgar/data/{cik_int}/{acc}/"


def _recent_rows(payload):
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    if not isinstance(forms, list):
        raise ValueError("submissions recent.form missing")
    rows = []
    for i, form in enumerate(forms):
        rows.append({
            "form": form,
            "accession": (recent.get("accessionNumber") or [None] * len(forms))[i],
            "filing_date": (recent.get("filingDate") or [None] * len(forms))[i],
            "report_date": (recent.get("reportDate") or [None] * len(forms))[i],
            "primary_document": (recent.get("primaryDocument") or [None] * len(forms))[i],
            "primary_description": (recent.get("primaryDocDescription") or [None] * len(forms))[i],
        })
    return rows


def _first_matching(rows, forms):
    wanted = set(forms)
    for row in rows:
        if row["form"] in wanted and row["accession"] and row["primary_document"]:
            return row
    return None


def pick_latest_periodic(payload, *, cik=None):
    """Return annual and/or quarterly filing dicts from a submissions payload.

    Prefers clean forms (not /A amendments). Order follows SEC recent list
    (newest first). Missing class → omitted, not invented.
    """
    cik = pad_cik(cik if cik is not None else payload.get("cik"))
    rows = _recent_rows(payload)
    picked = []
    for label, forms in (("annual", ANNUAL_FORMS), ("quarterly", QUARTERLY_FORMS)):
        hit = _first_matching(rows, forms)
        if not hit:
            continue
        document_url = archive_document_url(cik, hit["accession"], hit["primary_document"])
        picked.append({
            "class": label,
            "form": hit["form"],
            "accession": hit["accession"],
            "filing_date": hit["filing_date"],
            "report_date": hit["report_date"],
            "primary_document": hit["primary_document"],
            "primary_description": hit["primary_description"],
            "document_url": document_url,
            "index_url": archive_index_url(cik, hit["accession"]),
            "cik": cik,
        })
    return picked


def extension_for(primary_document):
    """Map SEC primaryDocument suffix onto contract FORMATS (html/pdf/…)."""
    name = (primary_document or "").rsplit("/", 1)[-1].lower()
    if "." not in name:
        return "html"
    ext = name.rsplit(".", 1)[-1]
    if ext in ("html", "htm", "xhtml"):
        return "html"
    if ext in ("pdf", "txt"):
        return "pdf" if ext == "pdf" else "html"
    return "html"


def source_for_filing(company, filing):
    """Build a collect()-ready source dict for one discovered primary document."""
    company_id = company["company_id"]
    form_slug = filing["form"].lower().replace(" ", "")
    name = company.get("name") or company_id
    ticker = company.get("ticker") or ""
    title = f"{name} {filing['form']} filed {filing.get('filing_date') or 'unknown'}"
    return {
        "team": "fetchfilings",
        "id": f"fetchfilings-sec-{company_id}-{form_slug}",
        "publisher": "SEC EDGAR",
        "title": title,
        "url": filing["document_url"],
        "hosts": [ARCHIVE_HOST],
        "native_id": f"{filing['cik']}:{filing['accession']}",
        "extension": extension_for(filing["primary_document"]),
        "content_type": "text/html",
        "adapter": "sec_filing",
        "adapter_version": "v1",
        "cadence": "continuous",
        "execution_host": "macmini",
        "scheduled": False,
        "company_id": company_id,
        "ticker": ticker,
        "filing": {
            "form": filing["form"],
            "class": filing["class"],
            "accession": filing["accession"],
            "filing_date": filing["filing_date"],
            "report_date": filing["report_date"],
            "cik": filing["cik"],
            "company_name": name,
            "primary_document": filing["primary_document"],
            "document_url": filing["document_url"],
            "index_url": filing["index_url"],
        },
    }
