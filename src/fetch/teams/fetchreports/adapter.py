"""LBNL publication metadata/method. Does not pretend to read the PDF."""
import re

from fetch.core.html import candidate, parse_html, timed
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchreports"
    adapter_id = "lbnl_publication_page"

    def extract(self, data, source, original_path, retrieved_at):
        page = parse_html(data)
        sentence = re.search(r"This report, designed.*?historical shipment data\.", page.text)
        published = re.search(r"Date Published (\d{2})/(\d{2})/(\d{4})", page.text)
        self.require(sentence and published and "10.71468/P1WC7Q" in page.text,
                     "report_metadata_missing")
        return [candidate(
            "study", source["title"],
            {"DOI": "10.71468/P1WC7Q", "publisher": "LBNL", "edition": "2024"},
            "study.method", sentence[0], None,
            "US national historical datacenter electricity consumption method, publication abstract only; "
            "no per-campus allocation or quantitative PDF extraction",
            "reported", "publication page / Abstract; method sentence", sentence[0], sentence[0],
            published=timed(f"{published[3]}-{published[1]}-{published[2]}", "day",
                            "Date Published on native publication page"))]
