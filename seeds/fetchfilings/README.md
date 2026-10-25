# fetchfilings seeds

`listed_companies.json` is a frozen copy of inresearch `data/fetchfilings_listed_companies.json`
(50 listed companies from the 257-company registry). Refresh only from a reviewed inresearch commit.

- `channel=sec_edgar`: crawl via CIK / data.sec.gov
- `channel=local_ir`: official IR / local exchange only (no invented CIK)
