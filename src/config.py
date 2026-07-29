"""Shared configuration.

SEC EDGAR REQUIRES a descriptive User-Agent on every request or it will block you
with a 403. Set a real contact string here once; every fetch imports it.
See: https://www.sec.gov/os/webmaster-faq#developers
"""

# EDGAR asks for "Sample Company Name AdminContact@example.com" style identification.
USER_AGENT = "cre-credit-risk research project zachchainy@gmail.com"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}

# Be a polite citizen: EDGAR fair-access limit is ~10 requests/sec. We stay well under.
REQUEST_DELAY_SECONDS = 0.3

# Paths (relative to repo root)
RAW_DIR = "data/raw"
PROCESSED_DIR = "data/processed"
DB_PATH = "data/processed/loans.db"


# --- Deal registry -----------------------------------------------------------
# Pinned to specific ABS-EE accessions (June 2026 filings) so `make all` reproduces
# the SAME loan-level data every run. EDGAR filings are permanent, so a pinned
# accession is the reproducible choice. To add a deal (e.g. GS 2017-GS5/GS8), append
# a row here — the rest of the pipeline is deal-agnostic.
#
# accession is the dashless form used in EDGAR archive paths.
DEALS = [
    {
        "deal_id": "GS_2017-GS6",
        "name": "GS Mortgage Securities Trust 2017-GS6",
        "cik": "1704459",
        "accession": "000188852426010803",
        "exhibit": "exh_102.xml",
        "filing_date": "2026-06-23",
        "expected_loans": 33,
    },
    {
        "deal_id": "GS_2017-GS7",
        "name": "GS Mortgage Securities Trust 2017-GS7",
        "cik": "1710765",
        "accession": "000188852426010863",
        "exhibit": "exh_102.xml",
        "filing_date": "2026-06-23",
        "expected_loans": 38,
    },
]


def ex102_url(deal: dict) -> str:
    """Build the EDGAR archive URL for a deal's EX-102 loan-level XML exhibit."""
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{deal['cik']}/{deal['accession']}/{deal['exhibit']}"
    )


def raw_path(deal: dict) -> str:
    """Local path where a deal's raw EX-102 XML is saved."""
    return f"{RAW_DIR}/{deal['deal_id']}_exh102.xml"


# --- Rate-gap benchmark -------------------------------------------------------
# Fed H.15 "Selected Interest Rates" daily CSV (constant-maturity Treasury yields).
# Cached to data/raw/ on first fetch so the benchmark date is pinned and reproducible,
# same rationale as pinning the deal accessions above.
H15_URL = (
    "https://www.federalreserve.gov/datadownload/Output.aspx"
    "?rel=H15&series=bf17364827e38702b42a58cf8eaa3f78"
    "&lastobs=15&from=&to=&filetype=csv&label=include&layout=seriescolumn"
)
H15_RAW_PATH = f"{RAW_DIR}/h15_treasury.csv"

# All loans in this pool are 10-year fixed-rate conduit originations; a same-term
# take-out is the standard refinance assumption, so the 10-year CMT column is the
# relevant benchmark.
H15_TENOR_COLUMN = "10-year"

# ASSUMPTION, not a live market feed: current CMBS conduit spread over the 10-year
# UST, by property type, in basis points. Live spread data (e.g. Trepp, CMA) sits
# behind paid subscriptions not accessed for this project. These values are directional
# estimates consistent with the office/industrial-multifamily bifurcation documented in
# public CMBS commentary as of mid-2026 (office wide and stressed; industrial and
# multifamily comparatively tight). State this plainly in the writeup's Method & Limits.
SPREAD_BPS_BY_PROPERTY_TYPE = {
    "Multifamily": 160,
    "Industrial": 170,
    "Warehouse": 170,
    "Self Storage": 180,
    "Retail": 200,
    "Mixed Use": 210,
    "Health Care": 220,
    "Lodging": 230,
    "Office": 275,
    "Manufactured Housing": 190,
    "Other": 220,
    "Unknown": 220,  # fallback: overall conduit-average estimate
}
