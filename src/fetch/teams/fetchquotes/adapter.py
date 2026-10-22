"""Lambda 1x H100 SXM native JSON island table. Offer, not a trade."""
import json
import re

from fetch.core.html import candidate, parse_html, timed
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchquotes"
    adapter_id = "lambda_1x_h100"

    def extract(self, data, source, original_path, retrieved_at):
        text = data.decode("utf-8")
        found = []
        for match in re.finditer(r"var newIslands\s*=\s*", text):
            islands, _ = json.JSONDecoder().raw_decode(text[match.end():])
            for island in islands:
                for tab in island.get("props", {}).get("tabs", []):
                    if tab.get("label") != "1x":
                        continue
                    page = parse_html(tab["contentHtml"].encode())
                    self.require("PRICE/GPU/HR*" in page.text
                                 and "plus applicable sales tax/VAT/GST" in page.text,
                                 "pricing_header_changed")
                    for row in page.rows:
                        if len(row) == 6 and row[0] == "NVIDIA H100 SXM":
                            self.require(bool(re.fullmatch(r"\$\d+\.\d{2}", row[5])),
                                         "price_format_changed")
                            result = candidate(
                                "product", "Lambda 1x NVIDIA H100 SXM instance",
                                {"provider": "Lambda", "model": row[0], "gpu_count": 1, "vram": row[1],
                                 "vcpus": row[2], "ram": row[3], "storage": row[4],
                                 "market": None, "currency": None},
                                "quote.price", float(row[5][1:]), "$/GPU-hour",
                                "Public list offer; 1 GPU instance; " + " | ".join(row[:5])
                                + "; regional availability unspecified; currency symbol $ only "
                                "(currency code not confirmed); plus sales tax/VAT/GST; "
                                "no inventory or transaction guarantee",
                                "offer",
                                "script var newIslands native JSON / props/tabs[label=1x]/contentHtml; "
                                "NVIDIA H100 SXM row",
                                row[5], page.text,
                                timed(retrieved_at, "datetime",
                                      "offer sampled by live acquisition; not publisher effective date")
                                if retrieved_at else None)
                            found.append(result)
        self.require(len(found) == 1, "h100_quote_ambiguous")
        return found
