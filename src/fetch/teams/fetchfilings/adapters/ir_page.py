"""Official IR landing page identity for listed companies.

Provides one unresolved observation that an investor-relations URL was retrieved.
Provides no line-item extraction.
"""
from fetch.core.html import candidate
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchfilings"
    adapter_id = "ir_page"

    def extract(self, data, source, original_path, retrieved_at):
        self.require(isinstance(data, (bytes, bytearray)) and len(data) >= 32,
                     "registered_field_not_found")
        url = source.get("url")
        self.require(url and str(url).startswith("https://"), "registered_field_not_found")
        name = source.get("title") or source.get("company_id") or url
        identifiers = {}
        if source.get("company_id"):
            identifiers["company_id"] = source["company_id"]
        row = candidate(
            "company", name, identifiers,
            "disclosure.ir.landing", "IR", "page",
            "Official investor relations landing page; identity only",
            "reported",
            "IR URL",
            url, f"ir_url={url}")
        row["links"] = {"document_url": url, "index_url": url}
        return [row]
