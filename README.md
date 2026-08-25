# CRE Credit Risk: Loan-Level Distress Analysis of the 2026 Maturity Wall

Segmented a live $1.6B CMBS loan pool by refinance-distress risk ahead of the
2026-2027 maturity wall. **44.6% of pool balance sits in Elevated or Acute risk** —
and it's concentrated less by property type than the market narrative would suggest:
Office is the largest dollar exposure in the pool, but proportionally the *healthiest*
of its major property types.

**[Try the live app](https://cre-credit-risk.streamlit.app/)**
— run the same segmentation against the sample pool or your own loan tape.
Full writeup: [`analysis/findings.md`](analysis/findings.md).

---

## The question

Roughly $900B+ of CRE debt matures in 2026, much of it CMBS originated 2014-2017 at
materially lower rates and now facing refinances 200-300 bps higher. CMBS distress is
elevated and unevenly distributed across property types. Maturity risk, not
operational failure, is driving new distress.

This project asks: within a real CMBS loan pool, where is refinance risk actually
concentrated, what drives it, and what should a lender or investor do about it —
answered with loan-level data, not portfolio-level commentary.

## Data

Loan-level detail comes from **SEC EDGAR ABS-EE filings** — under Regulation AB II,
CMBS issuers file loan-level asset data as a structured XML exhibit (`EX-102`),
covering current balance, coupon, maturity, property type and location, NOI, DSCR,
LTV, and occupancy for every loan in the trust.

The analysis covers two 2017-vintage conduit deals from the same issuance shelf
(GS Mortgage Securities Trust 2017-GS6 and 2017-GS7) — 71 loans, 49 of them active
real estate after excluding defeased and paid-off loans, totaling $1.61B. Parsed
values were cross-checked against each deal's original 2017 term sheet (an independent
filing) and matched to within 0.04%.

Refinance benchmarking uses the Federal Reserve's H.15 constant-maturity Treasury
series plus a property-type CMBS spread assumption, documented in
[`src/config.py`](src/config.py) and checked against the market's widely-cited
200-300bps refinancing environment for this vintage.

## Method

Every loan is scored on a **pro-forma refinance DSCR** — its reported DSCR rescaled by
the ratio of its current coupon to an estimated takeout rate — and tiered into
Low / Watch / Elevated / Acute based on whether it can still cover debt service at
today's rate, with an escalation for high leverage or Office/Lodging exposure. The
full rule is stated in [`src/segment.sql`](src/segment.sql), not buried in a model —
segmentation logic should be auditable by a credit reader, not a black box.

## Key finding

| Tier | Loans | Balance | % of pool |
|---|---|---|---|
| Acute | 18 | $507.1M | 31.4% |
| Elevated | 8 | $213.2M | 13.2% |
| Watch | 14 | $695.9M | 43.1% |
| Low | 9 | $198.5M | 12.3% |

Office carries 61.3% of pool balance but only 40.6% of its own balance sits in
Elevated/Acute — lower than Retail (53.5%), Mixed Use (58.1%), or Multifamily
(62.0%). Office is the largest dollar exposure to the wall, not the worst-behaved
property type in this pool. It's still internally bifurcated, though: pro-forma DSCR
within Office loans alone spans 0.85x to 2.56x, and no office loan clears into the
Low tier.

See [`analysis/findings.md`](analysis/findings.md) for the full memo — recommendation,
driver analysis, and named limitations.

## Interactive app

**[Live app](https://cre-credit-risk.streamlit.app/)** — the
same pro-forma DSCR segmentation, runnable live: pick the sample pool or upload a loan
tape in the same schema, and get the tier breakdown, DSCR distribution, maturity wall
chart, a sortable loan-level table, and a downloadable memo (PDF) generated from
whatever data is loaded — not a static writeup.

To run it locally instead:

```
streamlit run app/streamlit_app.py
```

`app/segmentation.py` ports the tiering logic from `src/segment.sql` into a plain
`compute_risk_tiers(df)` function, so the same rule drives both the static analysis
and the live app.

## Repository structure

```
cre-credit-risk/
  data/
    raw/                     <- downloaded ABS-EE XML and the H.15 benchmark snapshot
    processed/               <- parsed loan-level CSV / SQLite database
  src/
    config.py                <- deal registry, rate-spread assumptions, shared constants
    fetch_absee.py           <- pulls ABS-EE filings from EDGAR
    parse_absee.py           <- XML -> tidy per-loan table -> SQLite
    rate_gap.py               <- Treasury benchmark + rate-gap calculation
    segment.sql               <- risk segmentation logic
    drivers.py                <- driver analysis + chart generation
  app/
    streamlit_app.py          <- interactive app (upload/select, results, export)
    segmentation.py            <- compute_risk_tiers(df), ported from segment.sql
    charts.py                  <- Plotly chart builders
    memo.py                    <- live PDF memo generation
    data/sample_pool.csv       <- the GS 2017-GS6/GS7 sample pool
  analysis/
    findings.md               <- the writeup
    charts/                   <- exported figures
  requirements.txt
  Makefile
```

## Running it

```
make all
```

Reproduces the full analysis pipeline from a clean clone — fetch, parse, load,
benchmark, segment, and driver analysis with charts — using a local virtualenv and
SQLite. No cloud, no external services beyond the public data sources above.

## Limitations

Stated in full in `findings.md`, briefly: property valuations in this data are from
origination (2016-2017), so current leverage is likely understated; refinance spreads
are a documented assumption rather than a live market quote; and roughly 39% of loans
report DSCR from at-securitization underwriting rather than current performance. None
of these change the direction of the findings, but they bound how precisely the
numbers should be read.
