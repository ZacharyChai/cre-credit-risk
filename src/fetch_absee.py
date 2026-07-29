"""Fetch ABS-EE EX-102 loan-level XML from EDGAR into data/raw/.

Pulls the EX-102 exhibit for every deal in config.DEALS (pinned accessions, so this
reproduces the same data each run) using the SEC-required descriptive User-Agent.
Validates each download is genuine loan-level asset data before trusting it.

Usage:
    python src/fetch_absee.py            # fetch missing deals
    python src/fetch_absee.py --force    # re-download even if present
"""

import argparse
import os
import sys
import time

import requests

# Allow `python src/fetch_absee.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    DEALS,
    HEADERS,
    RAW_DIR,
    REQUEST_DELAY_SECONDS,
    ex102_url,
    raw_path,
)


def fetch_one(deal: dict, force: bool) -> int:
    """Download one deal's EX-102 XML. Returns the loan (asset) count found."""
    dest = raw_path(deal)
    url = ex102_url(deal)

    if os.path.exists(dest) and not force:
        data = open(dest, "rb").read()
        print(f"  [skip] {deal['deal_id']}: already present ({len(data):,} bytes)")
        return validate(deal, data, dest)

    print(f"  [get ] {deal['deal_id']} <- {url}")
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(resp.content)
    print(f"         saved {len(resp.content):,} bytes -> {dest}")
    time.sleep(REQUEST_DELAY_SECONDS)  # be polite to EDGAR
    return validate(deal, resp.content, dest)


def validate(deal: dict, data: bytes, dest: str) -> int:
    """Sanity-check the file is real ABS-EE loan-level data, not an error page."""
    text = data.decode("utf-8", errors="replace")
    if "<assetData" not in text:
        raise ValueError(
            f"{deal['deal_id']}: {dest} is not an ABS-EE asset-data XML "
            f"(no <assetData> root). Got {len(data)} bytes — check the URL/accession."
        )
    loans = text.count("<assets>")
    expected = deal.get("expected_loans")
    flag = "" if expected is None or loans == expected else f"  (expected {expected}!)"
    print(f"         validated: {loans} loans{flag}")
    return loans


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ABS-EE EX-102 XML from EDGAR.")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()

    print(f"Fetching {len(DEALS)} deal(s) into {RAW_DIR}/ ...")
    total = 0
    for deal in DEALS:
        total += fetch_one(deal, args.force)
    print(f"Done. {len(DEALS)} deal(s), {total} loans total on disk.")


if __name__ == "__main__":
    main()
