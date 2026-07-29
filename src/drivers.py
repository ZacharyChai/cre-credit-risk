"""Driver analysis: what concentrates the Elevated/Acute risk tiers?

Cross-tabs the risk tiers (from segment.sql's loan_risk_tiers view) by property type,
geography, and loan size, and renders the charts that carry the memo's argument.

Usage:
    python src/drivers.py            # print cross-tabs, write charts to analysis/charts/
"""

import os
import sqlite3
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH  # noqa: E402

TIER_ORDER = ["Acute", "Elevated", "Watch", "Low"]
CHARTS_DIR = "analysis/charts"

# Status colors carry the risk tier (a fixed, reserved 4-step scale -- never reused
# for a plain series); one sequential blue hue carries plain magnitude elsewhere.
STATUS_COLOR = {"Low": "#0ca30c", "Watch": "#fab219", "Elevated": "#ec835a", "Acute": "#d03b3b"}
SEQ_BLUE = "#2a78d6"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "font.family": "sans-serif",
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": GRIDLINE,
    "axes.labelcolor": INK_SECONDARY,
    "text.color": INK_PRIMARY,
    "xtick.color": INK_MUTED,
    "ytick.color": INK_MUTED,
    "axes.grid": False,
    "savefig.facecolor": SURFACE,
})


def load_data(conn):
    tiers = pd.read_sql("SELECT * FROM loan_risk_tiers", conn)
    loans = pd.read_sql(
        "SELECT deal_id, loan_id, origination_date FROM loans "
        "WHERE loan_status='active' AND NOT is_defeased",
        conn,
    )
    return tiers.merge(loans, on=["deal_id", "loan_id"], how="left")


def pct_elevated_acute(balance_by_tier: dict, total: float) -> float:
    return 100.0 * (balance_by_tier.get("Acute", 0) + balance_by_tier.get("Elevated", 0)) / total


def crosstab_by(df: pd.DataFrame, col: str, min_loans: int = 1) -> pd.DataFrame:
    """Balance and loan count by category x tier, plus % of that category's balance
    in Elevated/Acute -- the concentration signal, not just raw tier counts.
    dropna=False so NaN categories (e.g. the blank-state multi-property loans) show
    up as their own row instead of silently vanishing from the cross-tab."""
    rows = []
    for val, g in df.groupby(col, dropna=False):
        if len(g) < min_loans:
            continue
        bal_by_tier = g.groupby("risk_tier")["current_balance"].sum().to_dict()
        total = g["current_balance"].sum()
        rows.append({
            col: val,
            "loans": len(g),
            "balance_m": total / 1e6,
            "pct_pool": 100.0 * total / df["current_balance"].sum(),
            "pct_elevated_acute": pct_elevated_acute(bal_by_tier, total),
        })
    return pd.DataFrame(rows).sort_values("balance_m", ascending=False)


def _clean_axes(ax):
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRIDLINE)
    ax.tick_params(length=0)


def chart_tier_distribution(df: pd.DataFrame):
    """Chart 1 (the headline): pool balance by risk tier."""
    by_tier = df.groupby("risk_tier")["current_balance"].sum().reindex(TIER_ORDER) / 1e6
    total = by_tier.sum()

    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.barh(
        by_tier.index[::-1], by_tier.values[::-1],
        color=[STATUS_COLOR[t] for t in by_tier.index[::-1]], height=0.6,
    )
    for bar, val in zip(bars, by_tier.values[::-1]):
        ax.text(
            bar.get_width() + total * 0.015, bar.get_y() + bar.get_height() / 2,
            f"${val:,.0f}M  ({100*val/total:.1f}%)",
            va="center", ha="left", color=INK_PRIMARY, fontsize=10,
        )
    ax.set_xlim(0, total * 1.32)
    ax.set_xticks([])
    ax.set_title(
        "Where the risk sits: 44.6% of pool balance is Elevated or Acute",
        loc="left", fontsize=12, color=INK_PRIMARY, pad=14,
    )
    ax.set_xlabel("")
    _clean_axes(ax)
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/01_tier_distribution.png", dpi=150)
    plt.close(fig)


def chart_property_type_risk(df: pd.DataFrame):
    """Chart 2: % of each property type's own balance sitting in Elevated/Acute."""
    rows = []
    for ptype, g in df.groupby("property_type"):
        bal_by_tier = g.groupby("risk_tier")["current_balance"].sum().to_dict()
        total = g["current_balance"].sum()
        rows.append({
            "property_type": ptype,
            "loans": len(g),
            "balance_m": total / 1e6,
            "pct_ea": pct_elevated_acute(bal_by_tier, total),
        })
    d = pd.DataFrame(rows).sort_values("pct_ea")
    # n=1 categories (Warehouse, Industrial, Lodging) render a deterministic 0%/100% --
    # a single loan, not a rate. Label them plainly rather than let a one-loan bar sit
    # at equal visual weight beside categories with real sample size.
    ylabels = [
        f"{r['property_type']}" + (" (n=1)" if r["loans"] == 1 else "")
        for _, r in d.iterrows()
    ]

    fig, ax = plt.subplots(figsize=(7, 3.6))
    bars = ax.barh(ylabels, d["pct_ea"], color=SEQ_BLUE, height=0.6)
    for bar, (_, r) in zip(bars, d.iterrows()):
        ax.text(
            bar.get_width() + 1.5, bar.get_y() + bar.get_height() / 2,
            f"{r['pct_ea']:.0f}%  ({r['loans']} loan{'s' if r['loans'] != 1 else ''}, "
            f"${r['balance_m']:,.0f}M)",
            va="center", ha="left", color=INK_PRIMARY, fontsize=9.5,
        )
    ax.set_xlim(0, 122)
    ax.set_xticks([])
    ax.set_title(
        "Office carries the most dollars, not the highest risk rate",
        loc="left", fontsize=12, color=INK_PRIMARY, pad=14,
    )
    ax.set_xlabel("% of property type's own balance in Elevated/Acute  ·  (n=1) = single loan, not a rate")
    ax.xaxis.label.set_fontsize(9)
    _clean_axes(ax)
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/02_property_type_risk.png", dpi=150)
    plt.close(fig)


def chart_office_bifurcation(df: pd.DataFrame):
    """Chart 3: pro-forma DSCR spread within Office loans alone -- the bifurcation.
    This is a 1-D strip plot -- the y-axis carries no meaning, only x does. A small
    fixed stagger (not sort order) keeps close points from overlapping without
    creating a false diagonal "trend" that sort-order-as-y would otherwise imply."""
    office = df[df["property_type"] == "Office"].sort_values("pro_forma_dscr").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(7, 2.8))
    y = [[0.2, -0.2, 0.0][i % 3] for i in range(len(office))]
    ax.scatter(
        office["pro_forma_dscr"], y,
        c=[STATUS_COLOR[t] for t in office["risk_tier"]],
        s=90, zorder=3, edgecolors=SURFACE, linewidths=1.5,
    )
    ax.set_ylim(-1.0, 1.0)
    ax.axvline(1.00, color=INK_MUTED, linewidth=1, linestyle=(0, (3, 2)))
    ax.text(1.00, 0.75, " 1.00x break-even", color=INK_SECONDARY, fontsize=9)
    ax.set_yticks([])
    ax.set_xlabel("Pro-forma DSCR at estimated takeout rate")
    ax.xaxis.label.set_fontsize(9)
    ax.set_title(
        "Office is internally bifurcated: no loan is safely above the line",
        loc="left", fontsize=12, color=INK_PRIMARY, pad=14,
    )
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRIDLINE)
    ax.tick_params(length=0, labelsize=9)
    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", color=STATUS_COLOR[t], label=t, markersize=8)
        for t in TIER_ORDER if t in office["risk_tier"].unique()
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -0.25), ncol=4,
              frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/03_office_bifurcation.png", dpi=150)
    plt.close(fig)


def chart_rate_gap_histogram(df: pd.DataFrame):
    """Chart 4: pool-wide rate-gap distribution -- the payment-shock magnitude."""
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.hist(df["rate_gap_pct"], bins=12, color=SEQ_BLUE, edgecolor=SURFACE, linewidth=1.5)
    median = df["rate_gap_pct"].median()
    ax.axvline(median, color=INK_PRIMARY, linewidth=1.5)
    ax.text(median + 0.05, ax.get_ylim()[1] * 0.92, f"median +{median:.2f} pts",
            color=INK_PRIMARY, fontsize=9.5)
    ax.set_xlabel("Estimated rate gap at refinance (percentage points)")
    ax.set_ylabel("Loans")
    ax.xaxis.label.set_fontsize(9)
    ax.yaxis.label.set_fontsize(9)
    ax.set_title(
        "Every loan faces a payment shock -- the only question is size",
        loc="left", fontsize=12, color=INK_PRIMARY, pad=14,
    )
    ax.grid(axis="y", color=GRIDLINE, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    _clean_axes(ax)
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/04_rate_gap_histogram.png", dpi=150)
    plt.close(fig)


def chart_maturity_wall(df: pd.DataFrame):
    """Chart 5: balance maturing by quarter -- the wall in one picture."""
    q = (
        df["maturity_date"].str[:4] + "-Q" +
        ((df["maturity_date"].str[5:7].astype(int) + 2) // 3).astype(str)
    )
    by_q = df.groupby(q)["current_balance"].sum().sort_index() / 1e6
    total = by_q.sum()

    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.bar(by_q.index, by_q.values, color=SEQ_BLUE, width=0.55)
    for bar, val in zip(bars, by_q.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + total * 0.02,
                f"${val:,.0f}M\n({100*val/total:.0f}%)", ha="center", va="bottom",
                color=INK_PRIMARY, fontsize=9.5)
    ax.set_ylim(0, by_q.values.max() * 1.28)
    ax.set_yticks([])
    ax.set_title(
        "100% of the active pool matures in 2027 -- there is no later cohort",
        loc="left", fontsize=12, color=INK_PRIMARY, pad=14,
    )
    _clean_axes(ax)
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/05_maturity_wall.png", dpi=150)
    plt.close(fig)


def make_charts(df: pd.DataFrame):
    os.makedirs(CHARTS_DIR, exist_ok=True)
    chart_tier_distribution(df)
    chart_property_type_risk(df)
    chart_office_bifurcation(df)
    chart_rate_gap_histogram(df)
    chart_maturity_wall(df)
    print(f"Wrote 5 charts to {CHARTS_DIR}/")


def main():
    with sqlite3.connect(DB_PATH) as conn:
        df = load_data(conn)

    total_balance = df["current_balance"].sum()
    print(f"Driver analysis on {len(df)} active real-estate loans, ${total_balance/1e6:,.1f}M\n")

    # --- Property type: the primary driver ----------------------------------
    by_type = crosstab_by(df, "property_type")
    print("=== Concentration by property type ===")
    print(by_type.to_string(index=False, formatters={
        "balance_m": "${:,.1f}M".format,
        "pct_pool": "{:.1f}%".format,
        "pct_elevated_acute": "{:.1f}%".format,
    }))
    print()

    # --- Office bifurcation: does Office split into healthy vs. impaired? ---
    office = df[df["property_type"] == "Office"]
    print("=== Office bifurcation (pro-forma DSCR spread within Office alone) ===")
    print(f"  {len(office)} office loans, ${office['current_balance'].sum()/1e6:,.1f}M")
    print(f"  pro_forma_dscr: min={office['pro_forma_dscr'].min():.2f}x  "
          f"median={office['pro_forma_dscr'].median():.2f}x  "
          f"max={office['pro_forma_dscr'].max():.2f}x")
    office_tier_counts = {
        tier: int(n)
        for tier, n in office["risk_tier"].value_counts().reindex(TIER_ORDER, fill_value=0).items()
    }
    print(f"  tier split (loans): {office_tier_counts}")
    print()

    # --- Geography ------------------------------------------------------------
    by_state = crosstab_by(df, "state", min_loans=1)
    print("=== Concentration by state (top 8 by balance) ===")
    print(by_state.head(8).to_string(index=False, formatters={
        "balance_m": "${:,.1f}M".format,
        "pct_pool": "{:.1f}%".format,
        "pct_elevated_acute": "{:.1f}%".format,
    }))
    blank_state_n = df["state"].isna().sum()
    print(f"  ({blank_state_n} multi-property loans carry a blank state field -- "
          f"parent record doesn't aggregate state the way it does property type)")
    print()

    # --- Loan size --------------------------------------------------------
    bins = [0, 10e6, 25e6, 50e6, 100e6, float("inf")]
    labels = ["<$10M", "$10-25M", "$25-50M", "$50-100M", "$100M+"]
    df["size_bucket"] = pd.cut(df["current_balance"], bins=bins, labels=labels)
    by_size = crosstab_by(df, "size_bucket")
    print("=== Concentration by loan size ===")
    print(by_size.to_string(index=False, formatters={
        "balance_m": "${:,.1f}M".format,
        "pct_pool": "{:.1f}%".format,
        "pct_elevated_acute": "{:.1f}%".format,
    }))
    print()

    # --- Vintage (sanity check only -- expected to show little variation) ---
    df["vintage"] = df["origination_date"].str[:4]
    vintage_counts = df["vintage"].value_counts()
    print("=== Vintage (sanity check) ===")
    print(f"  {vintage_counts.to_dict()} -- effectively single-vintage (2017 conduit "
          f"shelf), consistent with the pool's uniform 2027 maturity. Not a driver here.")

    make_charts(df)


if __name__ == "__main__":
    main()
