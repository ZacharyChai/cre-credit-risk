"""Risk tier segmentation, ported from src/segment.sql.

Kept as a plain pandas function (not a SQLite dependency) so the app can run
against an uploaded loan tape without a database step. The tiering rule is
identical to the SQL version -- same thresholds, same escalation logic -- so
results match the static analysis exactly for the sample pool.
"""

import pandas as pd

REQUIRED_COLUMNS = [
    "loan_id",
    "property_type",
    "current_balance",
    "dscr",
    "coupon_pct",
    "takeout_rate_pct",
    "ltv",
    "is_pari_passu",
    "loan_status",
    "is_defeased",
]

TIER_ORDER = ["Acute", "Elevated", "Watch", "Low"]

TIER_LABELS = {3: "Acute", 2: "Elevated", 1: "Watch", 0: "Low"}


class SchemaError(ValueError):
    """Raised when an uploaded loan tape is missing required columns."""


def validate_schema(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(
            "This file is missing required columns: " + ", ".join(missing) + ". "
            "Expected the same schema as the parsed loan-level data "
            "(see data/processed/loans.csv in the repository)."
        )


def compute_risk_tiers(df: pd.DataFrame) -> pd.DataFrame:
    """Score every active, non-defeased loan into a Low/Watch/Elevated/Acute tier.

    Base tier comes from a pro-forma refinance DSCR (reported DSCR rescaled by the
    ratio of current coupon to estimated takeout rate). One-step escalation for
    high leverage (LTV > 80%, excluding pari-passu note pieces where per-slice LTV
    understates true leverage) or Office/Lodging property type.
    """
    validate_schema(df)

    active = df[(df["loan_status"] == "active") & (~df["is_defeased"].astype(bool))].copy()

    active["pro_forma_dscr"] = active["dscr"] * (active["coupon_pct"] / active["takeout_rate_pct"])

    def base_tier_idx(row):
        if pd.isna(row["dscr"]) or pd.isna(row["takeout_rate_pct"]):
            return None
        pfd = row["pro_forma_dscr"]
        if pfd < 1.00:
            return 3
        if pfd < 1.10:
            return 2
        if pfd < 1.25:
            return 1
        return 0

    active["base_tier_idx"] = active.apply(base_tier_idx, axis=1)

    def escalate(row):
        high_leverage = (
            not bool(row.get("is_pari_passu", False))
            and pd.notna(row["ltv"])
            and row["ltv"] > 0.80
        )
        risky_type = row["property_type"] in ("Office", "Lodging")
        return 1 if (high_leverage or risky_type) else 0

    active["escalate"] = active.apply(escalate, axis=1)

    active["risk_score"] = (
        active["base_tier_idx"].fillna(1) + active["escalate"]
    ).clip(upper=3).astype(int)
    active["risk_tier"] = active["risk_score"].map(TIER_LABELS)
    active["risk_tier"] = pd.Categorical(active["risk_tier"], categories=TIER_ORDER, ordered=True)

    return active


def tier_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """Loans, balance, and % of pool by tier -- the headline table."""
    total = scored["current_balance"].sum()
    summary = (
        scored.groupby("risk_tier", observed=True)
        .agg(loans=("loan_id", "count"), balance=("current_balance", "sum"))
        .reindex(TIER_ORDER)
        .fillna(0)
    )
    summary["pct_of_pool"] = 100 * summary["balance"] / total if total else 0
    return summary.reset_index()
