"""Microsoft FY2025 cash additions to PP&E, consolidated company scope."""
from fetch.core.html import candidate, parse_html, timed
from fetch.teams.base import Adapter as Base


class Adapter(Base):
    team = "fetchfilings"
    adapter_id = "microsoft_ar_ppe"

    def extract(self, data, source, original_path, retrieved_at):
        page = parse_html(data)
        self.require("Year Ended June 30, 2025 2024 2023" in page.text and "(In millions)" in page.text,
                     "financial_period_changed")
        rows = [r for r in page.rows if r and r[0] == "Additions to property and equipment"]
        self.require(len(rows) == 1, "cash_flow_row_ambiguous")
        row = rows[0]
        numbers = [c for c in row[1:] if c]
        self.require(len(numbers) == 3 and numbers[0].startswith("(") and numbers[0].endswith(")"),
                     "cash_flow_value_schema_changed")
        value = -float(numbers[0][1:-1].replace(",", ""))
        result = candidate(
            "company", "Microsoft Corporation", {"CIK": "0000789019", "ticker": "MSFT"},
            "finance.cashflow.additions_to_ppe", value, "USD million",
            "Microsoft consolidated; FY2025 ended June 30; cash flow investing outflow; "
            "excludes noncash lease additions; not individual campus capex",
            "reported",
            "Consolidated statements of cash flows; Additions to property and equipment; FY2025 column",
            numbers[0],
            "Year Ended June 30, 2025 2024 2023 | In millions USD | " + " | ".join(row),
            timed("2025-06-30", "day", "fiscal year end, not expenditure on this day"))
        result.update(period_start="2024-07-01", period_end="2025-06-30")
        return [result]
