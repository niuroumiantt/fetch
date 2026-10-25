# fetchfilings seeds

`listed_companies.json` is a frozen copy of inresearch `data/fetchfilings_listed_companies.json`
(50 listed companies from the 257-company registry). Refresh only from a reviewed inresearch commit.

- `channel=sec_edgar`: crawl via CIK / data.sec.gov
- `channel=local_ir`: official IR / local exchange only (no invented CIK)

## Discover latest periodic filings

```text
./fetch discover --team fetchfilings
./fetch run --team fetchfilings --discovered
./fetch run --team fetchfilings --discovered --company-id microsoft
```

Discovery writes `~/.local/share/fetch/fetchfilings/discoveries/current.json` (pointers only).
Annual forms: 10-K / 20-F / 40-F. Quarterly: 10-Q when present. No invented filings.
