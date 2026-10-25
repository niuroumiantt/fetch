# fetchfilings seeds

`listed_companies.json` is a frozen copy of inresearch `data/fetchfilings_listed_companies.json`
(50 listed companies from the 257-company registry). Refresh only from a reviewed inresearch commit.

- `channel=sec_edgar`: crawl via CIK / data.sec.gov
- `channel=local_ir`: official IR / local exchange only (no invented CIK)

## Weekly continuous refresh (listed-50 multi-lane)

```text
./fetch refresh --team listed
./fetch refresh --team fetchfilings
./fetch discover --team fetchfilings
./fetch run --team fetchfilings --discovered --company-id microsoft
```

Cadence is **weekly** (Sunday local, `deploy/m5/listed-weekly.plist`).

| Lane | What |
|---|---|
| filings | SEC discover+collect for 40 `sec_edgar`; disclosures projection |
| equity_quotes | Warm Nasdaq/NYSE quotes for US tickers; mirror into inresearch quote cache |
| investor_relations | Fetch official `ir_url` landing pages |
| product_specs | Status only for catalog-overlap vendors (amd/nvidia/supermicro/cambricon) |

`local_ir` keeps official IR URLs only — no invented CIK. fetchstat / fetchreports /
GPU fetchquotes stay on their own non-company calendars.

Discovery ledger: `discoveries/current.json`. Annual forms: 10-K / 20-F / 40-F.
Quarterly: 10-Q when present.
