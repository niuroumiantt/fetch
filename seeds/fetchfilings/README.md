# fetchfilings seeds

`listed_companies.json` is a frozen copy of inresearch `data/fetchfilings_listed_companies.json`
(50 listed companies from the 257-company registry). Refresh only from a reviewed inresearch commit.

- `channel=sec_edgar`: crawl via CIK / data.sec.gov
- `channel=local_ir`: official IR / local exchange only (no invented CIK)

## Weekly continuous refresh

```text
./fetch refresh --team fetchfilings
./fetch discover --team fetchfilings
./fetch run --team fetchfilings --discovered --company-id microsoft
```

Cadence is **weekly** (Sunday local). `refresh` discovers SEC submissions for the 40
`sec_edgar` companies, collects primary documents, and writes
`~/.local/share/fetch/fetchfilings/disclosures/current.json` for company-page links.
`local_ir` (10) keeps official IR URLs only — no invented CIK.

Discovery ledger: `discoveries/current.json`. Annual forms: 10-K / 20-F / 40-F.
Quarterly: 10-Q when present.
