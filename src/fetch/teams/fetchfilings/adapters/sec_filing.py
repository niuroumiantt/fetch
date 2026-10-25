"""SEC primary-document identity for fetchfilings.

Provides one unresolved observation that the listed company filed a named
periodic form, with original-document and index URLs as evidence. Provides no
line-item accounting facts; inresearch decides adoption.
"""
from fetch.core.html import candidate, timed
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchfilings"
    adapter_id = "sec_filing"

    def extract(self, data, source, original_path, retrieved_at):
        filing = source.get("filing") or {}
        form = filing.get("form")
        accession = filing.get("accession")
        cik = filing.get("cik")
        self.require(form and accession and cik, "registered_field_not_found")
        self.require(isinstance(data, (bytes, bytearray)) and len(data) >= 32,
                     "registered_field_not_found")

        name = filing.get("company_name") or source.get("title") or source.get("company_id")
        identifiers = {"CIK": cik}
        if source.get("company_id"):
            identifiers["company_id"] = source["company_id"]
        ticker = source.get("ticker")
        if ticker:
            identifiers["ticker"] = ticker

        document_url = filing.get("document_url") or source.get("url")
        index_url = filing.get("index_url")
        report_date = filing.get("report_date")
        filing_date = filing.get("filing_date")
        effective = timed(report_date, "day", "SEC reportDate") if report_date else None
        published = timed(filing_date, "day", "SEC filingDate") if filing_date else None

        quote = f"{form} {accession}"
        context = (
            f"form={form}; accession={accession}; primary={filing.get('primary_document')}; "
            f"document_url={document_url}; index_url={index_url}"
        )
        row = candidate(
            "company", name, identifiers,
            "disclosure.sec.periodic_form", form, "form",
            "SEC EDGAR periodic filing primary document; identity only, not line items",
            "reported",
            f"SEC submissions → {form} → {filing.get('primary_document')}",
            quote, context,
            effective=effective, published=published)
        row["links"] = {
            "document_url": document_url,
            "index_url": index_url,
        }
        return [row]
