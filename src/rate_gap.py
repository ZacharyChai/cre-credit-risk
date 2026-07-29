"""Pull the Fed H.15 Treasury benchmark and compute the rate-gap field.

Rate gap = estimated take-out rate today minus the loan's current coupon.
  positive gap -> refinancing today would raise debt service (payment shock)
  negative gap -> refinancing today would lower debt service

Take-out rate = 10-year Treasury (matches these loans' original 10-year term) +
an assumed CMBS conduit spread by property type (config.SPREAD_BPS_BY_PROPERTY_TYPE).
The spread is a documented analyst assumption, not a live market feed — see
config.py for sourcing notes.

Reproducibility note: unlike the ABS-EE XML -- pinned by an immutable EDGAR
accession, so re-fetching always returns identical bytes -- H.15 is a live daily
series. Fetching "latest observations" on a different day returns a different
rate, which can silently shift loan tiers across the risk threshold.
data/raw/h15_treasury.csv is therefore a deliberate exception to the data/raw/
gitignore rule -- it's committed so `make all` reproduces the same benchmark every
time. Only pass --force if you actually intend to move the analysis onto a new
benchmark date.

Usage:
    python src/rate_gap.py            # use the committed H.15 snapshot (default)
    python src/rate_gap.py --force    # re-fetch today's rate and move the benchmark
"""

import argparse
import os
import sys

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    DB_PATH,
    H15_RAW_PATH,
    H15_URL,
    HEADERS,
    RAW_DIR,
    SPREAD_BPS_BY_PROPERTY_TYPE,
)
from parse_absee import CSV_PATH  # noqa: E402


def fetch_h15(force: bool = False) -> str:
    """Download (or reuse cached) Fed H.15 CSV. Returns the local path."""
    if os.path.exists(H15_RAW_PATH) and not force:
        print(f"  [skip] H.15 already cached at {H15_RAW_PATH}")
        return H15_RAW_PATH
    print(f"  [get ] H.15 <- {H15_URL}")
    resp = requests.get(H15_URL, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    resp.raise_for_status()
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(H15_RAW_PATH, "w") as fh:
        fh.write(resp.text)
    return H15_RAW_PATH


def latest_10y_treasury(path: str) -> tuple[float, str]:
    """Parse the H.15 CSV and return (latest 10-year CMT yield, as-of date)."""
    df = pd.read_csv(path, skiprows=5, header=None)
    # Column order per H.15 seriescolumn layout: date, 1mo,3mo,6mo,1y,2y,3y,5y,7y,10y,20y,30y
    df.columns = [
        "date", "1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y",
    ]
    df["10y"] = pd.to_numeric(df["10y"], errors="coerce")  # "ND" (no data, holidays) -> NaN
    df = df.dropna(subset=["10y"])
    if df.empty:
        raise ValueError(f"No usable 10-year Treasury observations found in {path}")
    row = df.iloc[-1]
    return float(row["10y"]), str(row["date"])


def compute_rate_gap(df: pd.DataFrame, treasury_10y_pct: float) -> pd.DataFrame:
    df = df.copy()
    df["treasury_10y_pct"] = treasury_10y_pct
    df["spread_bps"] = df["property_type"].map(SPREAD_BPS_BY_PROPERTY_TYPE).fillna(
        SPREAD_BPS_BY_PROPERTY_TYPE["Unknown"]
    )
    df["takeout_rate_pct"] = treasury_10y_pct + df["spread_bps"] / 100
    df["rate_gap_pct"] = df["takeout_rate_pct"] - df["coupon_pct"]
    return df


def main():
    parser = argparse.ArgumentParser(description="Compute the rate-gap field.")
    parser.add_argument(
        "--force", action="store_true",
        help="re-fetch today's H.15 rate instead of using the committed snapshot "
             "(moves the analysis onto a new benchmark date -- see module docstring)",
    )
    args = parser.parse_args()

    print("Fetching H.15 Treasury benchmark...")
    path = fetch_h15(force=args.force)
    treasury_10y, as_of = latest_10y_treasury(path)
    print(f"  10-year Treasury CMT: {treasury_10y:.2f}% (as of {as_of})")

    df = pd.read_csv(CSV_PATH)
    df = compute_rate_gap(df, treasury_10y)
    df.to_csv(CSV_PATH, index=False)

    with_gap = df[df["loan_status"] == "active"]
    print(f"Updated {len(df)} loan records with rate-gap fields -> {CSV_PATH}")
    print(f"  active loans with rate_gap_pct: {with_gap['rate_gap_pct'].notna().sum()}/{len(with_gap)}")
    print(f"  median rate gap (active, non-defeased): "
          f"{with_gap[~with_gap['is_defeased']]['rate_gap_pct'].median():.2f} pts")

    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("loans", conn, if_exists="replace", index=False)
    print(f"Reloaded 'loans' table into {DB_PATH}")


if __name__ == "__main__":
    main()
