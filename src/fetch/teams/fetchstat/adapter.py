"""EIA table 5.6.B: Texas industrial YTD. Not datacenter contract prices."""
from datetime import datetime
import re

from fetch.core.html import candidate, parse_html, timed
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchstat"
    adapter_id = "eia_epm_5_6_b"

    def extract(self, data, source, original_path, retrieved_at):
        page = parse_html(data)
        title = re.search(r"Year-to-Date through ([A-Za-z]+) (20\d\d) and (20\d\d)", page.text)
        release = re.search(r"Release Date: ([A-Za-z]+ \d{1,2}, 20\d\d)", page.text)
        self.require(title and release and "Industrial" in page.text
                     and "Cents per Kilowatthour" in page.text, "eia_schema_changed")
        month = datetime.strptime(title[1], "%B").month
        row = next((r for r in page.rows if len(r) == 11 and r[0] == "Texas"), None)
        self.require(row is not None, "texas_row_missing")
        period = f"{title[2]}-{month:02d}"
        scope = ("Texas industrial sector; January through " + title[1] + " " + title[2]
                 + "; sales-weighted average; all industrial customers, not data center tariff")
        result = candidate(
            "statistic_series", "EIA Texas industrial YTD electricity price",
            {"publisher": "EIA", "series": "EPM 5.6.B industrial YTD", "country": "US", "state": "Texas"},
            "electricity.industrial_price", float(row[5]), "US cents/kWh", scope, "reported",
            "HTML Table 5.6.B; Texas row; Industrial first YTD column", row[5],
            title[0] + " | Cents per Kilowatthour | Residential, Commercial, Industrial, Transportation, All Sectors | "
            + " | ".join(row),
            timed(period, "month", "end of source YTD period, not a monthly-only price"),
            timed(datetime.strptime(release[1], "%B %d, %Y").date().isoformat(), "day", release[0]))
        result.update(period_start=f"{title[2]}-01-01", period_end=period, aggregation="year_to_date")
        return [result]
