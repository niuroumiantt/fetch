"""Astera Labs product-detail attributes → product identity and parameter table.

Thin first fetchspec adapter. Provides candidate product rows for packaging;
provides no field-mapping review, target binding, or adoption.
"""
import hashlib
import html as html_lib
import json
import re
from urllib.parse import urlsplit

from fetch import ROOT
from fetch.core.failures import FlowError
from fetch.teams.base import Adapter as Base

PRODUCT = re.compile(r"^/product-details/([A-Za-z0-9][A-Za-z0-9-]*)/$")
FAMILY = re.compile(r"^/products/([a-z0-9][a-z0-9-]*)/$")
BRIEF = re.compile(r"^/wp-content/uploads/\d{4}/\d{2}/[A-Za-z0-9._-]+\.pdf$")
ATTRIBUTE = re.compile(
    r'<li\b[^>]*>\s*<span class="[^"]*\bfw-medium\b[^"]*">(.*?)</span>(.*?)</li>', re.S | re.I)
TAG = re.compile(r"<[^>]+>")
HEADING = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
HREF = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def _text(fragment):
    return " ".join(html_lib.unescape(TAG.sub(" ", fragment)).replace("\xa0", " ").split())


def _profile():
    path = ROOT / "profiles" / "asteralabs.json"
    return json.loads(path.read_text(encoding="utf-8"))


class Adapter(Base):
    team = "fetchspec"
    adapter_id = "asteralabs_product_attributes"

    def __init__(self):
        self.profile = _profile()

    def page_allowed(self, url):
        parts = urlsplit(url)
        return (parts.hostname in self.profile["allowed_hosts"] and not parts.query
                and bool(PRODUCT.match(parts.path) or FAMILY.match(parts.path)))

    def extract(self, data, source, original_path, retrieved_at):
        """Return observation-shaped product attribute rows for the observation envelope.

        Full fetchspec receiver packages with product_evidence are built by
        `fetch.teams.fetchspec.package` when target bindings are supplied.
        """
        url = source["url"]
        if not self.page_allowed(url):
            raise FlowError("page_outside_company_scope", "configuration")
        body = data.decode("utf-8", "replace")
        path = urlsplit(url).path
        heading = _text(HEADING.search(body).group(1)) if HEADING.search(body) else ""
        self.require(bool(heading), "product_heading_missing")
        if FAMILY.match(path):
            # Family pages contribute ordering tables; attribute extraction is part-page only.
            return []
        rows = []
        for label, value in ATTRIBUTE.findall(body):
            label, value = _text(label).rstrip(":").strip(), _text(value)
            if label and value and label.casefold() != "ordering":
                rows.append([label, value])
        self.require(len(rows) >= 2, "product_attributes_missing")
        part = PRODUCT.match(path).group(1)
        product_id = "asteralabs-" + hashlib.sha256(part.casefold().encode()).hexdigest()[:20]
        from fetch.core.html import candidate
        results = []
        for label, value in rows:
            results.append(candidate(
                "product", heading,
                {"company_id": "asteralabs", "product_id": product_id, "part_number": part,
                 "parameter": label},
                "product.attribute." + re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_"),
                value, None,
                "Astera Labs product-details attribute list; original label/value text; not a reviewed parameter observation",
                "reported",
                "product-details attribute list; label " + label,
                value, label + ": " + value))
        briefs = []
        for href, label in HREF.findall(body):
            target = href if href.startswith("http") else "https://www.asteralabs.com" + href
            if BRIEF.match(urlsplit(target).path) and "brief" in (label + target).casefold():
                briefs.append(target)
        if briefs:
            results[0]["object"]["identifiers"]["product_brief_urls"] = briefs
        return results
