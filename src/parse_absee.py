"""Parse ABS-EE EX-102 XML into a tidy per-loan table, then load to SQLite.

Notes on the EX-102 schema:
  * Root <assetData>, one <assets> block per record, in a namespace we match with {*}.
  * A REAL LOAN is an <assets> block whose <assetNumber> has no hyphen (e.g. "12").
    Multi-property loans split into sibling <assets> with composite numbers
    ("2-001", "2-002"): the parent holds loan-level financials + AGGREGATE property
    metrics (with a blank propertyTypeCode); the children hold per-property detail.
    We keep one row per real loan and derive its property type from children when blank.
  * NOI / DSCR / occupancy / valuation live inside the loan's <property> block.
  * "Most recent" fields can be blank (esp. GS6); we fall back to at-securitization
    values and RECORD which basis we used (dscr_basis) so the writeup stays honest.
  * propertyTypeCode "SE" (Securities) == a DEFEASED loan: collateral is Treasuries,
    not real estate. Zero refinance risk. Flagged via is_defeased.

Usage:
    python src/parse_absee.py            # write data/processed/loans.csv
    python src/parse_absee.py --load     # also load into SQLite (loans table)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

import pandas as pd
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, DEALS, PROCESSED_DIR, raw_path  # noqa: E402

CSV_PATH = f"{PROCESSED_DIR}/loans.csv"

# RegAB II CMBS property-type codes -> readable labels.
PROPERTY_TYPE = {
    "MF": "Multifamily",
    "RT": "Retail",
    "OF": "Office",
    "IN": "Industrial",
    "WH": "Warehouse",
    "MU": "Mixed Use",
    "LO": "Lodging",
    "SS": "Self Storage",
    "MH": "Manufactured Housing",
    "HC": "Health Care",
    "SE": "Defeased (Securities)",
    "98": "Other",
    "OT": "Other",
    "NA": "Unknown",
    "": "Unknown",
}


# --- small extraction helpers ------------------------------------------------
def _txt(el, tag):
    """Text of the first child named `tag` (namespace-agnostic), else ''."""
    if el is None:
        return ""
    e = el.find(f"{{*}}{tag}")
    return (e.text or "").strip() if e is not None and e.text else ""


def _num(el, tag):
    """Float value of a tag, or None if blank/unparseable."""
    v = _txt(el, tag)
    try:
        return float(v) if v != "" else None
    except ValueError:
        return None


def _first_num(el, tags):
    """First non-None numeric among tags — implements a fallback chain."""
    for t in tags:
        v = _num(el, t)
        if v is not None:
            return v, t
    return None, None


def _date(el, tag):
    """Convert EDGAR's MM-DD-YYYY to ISO YYYY-MM-DD, else '' ."""
    v = _txt(el, tag)
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%m-%d-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return v


def _is_real_loan(a):
    return "-" not in _txt(a, "assetNumber")


# --- per-loan parse ----------------------------------------------------------
def parse_loan(deal, asset, all_assets):
    """Build one tidy loan record from a parent <assets> element."""
    loan_id = _txt(asset, "assetNumber")
    prop = asset.find("{*}property")

    # Defeasance is flagged inconsistently across deals: GS6 uses propertyTypeCode "SE"
    # (Securities); GS7 uses DefeasedStatusCode "F"/"P" and propertyName "Defeased".
    # Detect all three so Treasury-backed, zero-refi-risk loans aren't mistaken for
    # missing-data real estate.
    ptc = _txt(prop, "propertyTypeCode")
    defeased_code = _txt(prop, "DefeasedStatusCode")
    is_defeased = (
        ptc == "SE"
        or defeased_code in ("F", "P")
        or _txt(prop, "propertyName").strip().lower() == "defeased"
    )

    # Property type: parent code, or derive from child sub-records if blank.
    if not ptc and not is_defeased:
        kids = [c for c in all_assets if _txt(c, "assetNumber").startswith(loan_id + "-")]
        kcodes = {
            _txt(k.find("{*}property"), "propertyTypeCode")
            for k in kids
            if k.find("{*}property") is not None
        }
        kcodes.discard("")
        if len(kcodes) == 1:
            ptc = next(iter(kcodes))          # uniform portfolio (e.g. all office)
        elif len(kcodes) > 1:
            ptc = "MU"                        # genuinely mixed portfolio
    if is_defeased and ptc in ("", "SE"):
        ptc = "SE"                            # normalize all defeased to the SE label

    # Current balance: prefer report-period actual, fall back to scheduled / securitization.
    cur_bal, _ = _first_num(
        asset,
        [
            "reportPeriodEndActualBalanceAmount",
            "reportPeriodEndScheduledLoanBalanceAmount",
            "scheduledPrincipalBalanceSecuritizationAmount",
        ],
    )
    # Current coupon: report-period rate, else at-securitization.
    coupon, _ = _first_num(
        asset, ["reportPeriodInterestRatePercentage", "interestRateSecuritizationPercentage"]
    )

    # DSCR — most-recent NCF preferred, then securitization NCF, then NOI variants.
    dscr, dscr_src = _first_num(
        prop,
        [
            "mostRecentDebtServiceCoverageNetCashFlowpercentage",
            "debtServiceCoverageNetCashFlowSecuritizationPercentage",
            "mostRecentDebtServiceCoverageNetOperatingIncomePercentage",
            "debtServiceCoverageNetOperatingIncomeSecuritizationPercentage",
        ],
    )
    dscr_basis = {
        "mostRecentDebtServiceCoverageNetCashFlowpercentage": "most_recent_ncf",
        "debtServiceCoverageNetCashFlowSecuritizationPercentage": "securitization_ncf",
        "mostRecentDebtServiceCoverageNetOperatingIncomePercentage": "most_recent_noi",
        "debtServiceCoverageNetOperatingIncomeSecuritizationPercentage": "securitization_noi",
    }.get(dscr_src, "none")

    noi, _ = _first_num(
        prop, ["mostRecentNetOperatingIncomeAmount", "netOperatingIncomeSecuritizationAmount"]
    )
    occ, _ = _first_num(
        prop,
        ["mostRecentPhysicalOccupancyPercentage", "physicalOccupancySecuritizationPercentage"],
    )
    valuation = _num(prop, "valuationSecuritizationAmount")

    ltv = (cur_bal / valuation) if (cur_bal and valuation) else None
    debt_yield = (noi / cur_bal) if (noi and cur_bal) else None

    # A loan with no current balance has paid off / left the pool — not part of the
    # active maturity-wall analysis.
    loan_status = "paid_off" if not cur_bal else "active"
    # Pari-passu / A-note pieces: the trust holds only a SLICE of the balance, but the
    # valuation and NOI are the WHOLE property -> per-slice LTV and debt yield are
    # distorted (DSCR is whole-loan and stays reliable). Flag so analysis can caveat.
    loan_structure = _txt(asset, "loanStructureCode")
    is_pari_passu = loan_structure in ("PP", "A1")

    return {
        "deal_id": deal["deal_id"],
        "loan_id": loan_id,
        "property_name": _txt(prop, "propertyName"),
        "originator": _txt(asset, "originatorName"),
        "origination_date": _date(asset, "originationDate"),
        "maturity_date": _date(asset, "maturityDate"),
        "original_balance": _num(asset, "originalLoanAmount"),
        "current_balance": cur_bal,
        "coupon_pct": round(coupon * 100, 4) if coupon is not None else None,
        "io_flag": _txt(asset, "interestOnlyIndicator") == "true",
        "balloon_flag": _txt(asset, "balloonIndicator") == "true",
        "loan_structure": loan_structure,
        "is_pari_passu": is_pari_passu,
        "loan_status": loan_status,
        "payment_status_code": _txt(asset, "paymentStatusLoanCode"),
        "num_properties": int(_txt(asset, "NumberProperties") or 1),
        "property_type_code": ptc,
        "property_type": PROPERTY_TYPE.get(ptc, ptc or "Unknown"),
        "state": _txt(prop, "propertyState"),
        "city": _txt(prop, "propertyCity"),
        "sqft": _num(prop, "netRentableSquareFeetNumber"),
        "occupancy": occ,
        "noi": noi,
        "dscr": dscr,
        "dscr_basis": dscr_basis,
        "valuation": valuation,
        "valuation_date": _date(prop, "valuationSecuritizationDate"),
        "ltv": round(ltv, 4) if ltv is not None else None,
        "debt_yield": round(debt_yield, 4) if debt_yield is not None else None,
        "is_defeased": is_defeased,
    }


def parse_deal(deal):
    root = etree.parse(raw_path(deal)).getroot()
    assets = root.findall(".//{*}assets")
    real = [a for a in assets if _is_real_loan(a)]
    return [parse_loan(deal, a, assets) for a in real]


def build_dataframe():
    rows = []
    for deal in DEALS:
        rows.extend(parse_deal(deal))
    return pd.DataFrame(rows)


def load_sqlite(df):
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("loans", conn, if_exists="replace", index=False)
    return DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Parse ABS-EE EX-102 XML into tidy loans.")
    parser.add_argument("--load", action="store_true", help="also load into SQLite")
    args = parser.parse_args()

    df = build_dataframe()
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)

    active = df[df["loan_status"] == "active"]
    active_re = active[~active["is_defeased"]]  # active real-estate loans (the wall)
    print(f"Parsed {len(df)} loan records across {df['deal_id'].nunique()} deal(s) -> {CSV_PATH}")
    print(f"  paid off / left pool : {(df['loan_status'] == 'paid_off').sum()}")
    print(f"  active loans         : {len(active)}  (${active['current_balance'].sum():,.0f})")
    print(f"    of which defeased  : {int(active['is_defeased'].sum())}  (no refi risk)")
    print(f"    active real estate : {len(active_re)}  (${active_re['current_balance'].sum():,.0f})  <- the maturity wall")
    print(f"  pari-passu / A-note  : {int(df['is_pari_passu'].sum())}  (per-slice LTV caveated)")
    print(f"  DSCR coverage (active RE): {active_re['dscr'].notna().sum()}/{len(active_re)}")

    if args.load:
        path = load_sqlite(df)
        print(f"Loaded 'loans' table into {path}")


if __name__ == "__main__":
    main()
