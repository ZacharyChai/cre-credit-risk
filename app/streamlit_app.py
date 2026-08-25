"""CRE Credit Risk — interactive risk segmentation.

Runs the same pro-forma DSCR segmentation logic as src/segment.sql against a
selected sample pool or an uploaded loan tape, live in the browser.

Run locally:
    streamlit run app/streamlit_app.py
"""

import os

import pandas as pd
import streamlit as st

from charts import dscr_histogram, maturity_wall_chart, tier_bar_chart
from memo import generate_memo_pdf
from segmentation import SchemaError, TIER_ORDER, compute_risk_tiers, tier_summary

SAMPLE_POOL_PATH = os.path.join(os.path.dirname(__file__), "data", "sample_pool.csv")

STATUS_COLOR = {"Low": "#0ca30c", "Watch": "#fab219", "Elevated": "#ec835a", "Acute": "#d03b3b"}

st.set_page_config(page_title="CRE Credit Risk", page_icon="\U0001F3E2", layout="wide")


def load_sample_pool() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_POOL_PATH)


def reset():
    for key in ("scored", "pool_name", "raw_df"):
        st.session_state.pop(key, None)


def screen_select():
    st.title("CRE Credit Risk")
    st.caption(
        "Runs the same pro-forma DSCR risk segmentation as the underlying analysis "
        "repository — live, against any loan tape in the same schema."
    )

    choice = st.radio(
        "Choose a pool",
        ["Use the sample pool (GS 2017-GS6 / GS7)", "Upload a loan tape"],
        label_visibility="collapsed",
    )

    if choice.startswith("Use the sample"):
        st.write(
            "Two 2017-vintage conduit CMBS deals, parsed from SEC EDGAR ABS-EE "
            "filings — 49 active real-estate loans, $1.61B."
        )
        if st.button("Run analysis", type="primary"):
            df = load_sample_pool()
            try:
                st.session_state["scored"] = compute_risk_tiers(df)
                st.session_state["raw_df"] = df
                st.session_state["pool_name"] = "GS 2017-GS6 / GS7 sample pool"
                st.rerun()
            except SchemaError as e:
                st.error(str(e))
    else:
        st.write(
            "Expects the same columns as the parsed loan-level data — see "
            "`data/processed/loans.csv` in the repository for the exact schema."
        )
        upload = st.file_uploader("Loan tape (CSV)", type=["csv"])
        if upload is not None and st.button("Run analysis", type="primary"):
            try:
                df = pd.read_csv(upload)
                st.session_state["scored"] = compute_risk_tiers(df)
                st.session_state["raw_df"] = df
                st.session_state["pool_name"] = upload.name
                st.rerun()
            except SchemaError as e:
                st.error(str(e))
            except Exception as e:  # malformed CSV, etc.
                st.error(f"Couldn't parse this file: {e}")


def screen_results(scored: pd.DataFrame):
    total_balance = scored["current_balance"].sum()
    summary = tier_summary(scored)
    ea_balance = summary[summary["risk_tier"].isin(["Elevated", "Acute"])]["balance"].sum()
    ea_pct = 100 * ea_balance / total_balance if total_balance else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Active loans", len(scored))
    c2.metric("Pool balance", f"${total_balance/1e6:,.1f}M")
    c3.metric("Elevated + Acute", f"{ea_pct:.1f}%", f"${ea_balance/1e6:,.1f}M")

    st.plotly_chart(tier_bar_chart(summary), use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(dscr_histogram(scored), use_container_width=True)
    with col_b:
        st.plotly_chart(maturity_wall_chart(scored), use_container_width=True)


def screen_detail(scored: pd.DataFrame, pool_name: str):
    st.subheader("Loan-level detail")

    tiers = st.multiselect("Filter by tier", TIER_ORDER, default=TIER_ORDER)
    view = scored[scored["risk_tier"].isin(tiers)].sort_values("risk_score", ascending=False)

    display_cols = [
        "deal_id", "loan_id", "property_name", "property_type", "state",
        "current_balance", "dscr", "pro_forma_dscr", "ltv", "risk_tier",
    ]
    display_cols = [c for c in display_cols if c in view.columns]

    st.dataframe(
        view[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "current_balance": st.column_config.NumberColumn("Balance", format="dollar"),
            "dscr": st.column_config.NumberColumn("DSCR (today)", format="%.2fx"),
            "pro_forma_dscr": st.column_config.NumberColumn("Pro-forma DSCR", format="%.2fx"),
            "ltv": st.column_config.NumberColumn("LTV", format="percent"),
            "risk_tier": st.column_config.TextColumn("Tier"),
        },
    )

    st.divider()
    st.subheader("Export")
    st.write("Generates a findings memo from the current pool — recommendation, tier table, and the weakest Acute loans.")
    if st.button("Generate memo (PDF)"):
        pdf_bytes = generate_memo_pdf(scored, pool_name=pool_name)
        st.download_button(
            "Download memo.pdf", data=pdf_bytes,
            file_name="cre_credit_risk_memo.pdf", mime="application/pdf",
        )


def main():
    if "scored" not in st.session_state:
        screen_select()
        return

    scored = st.session_state["scored"]
    pool_name = st.session_state.get("pool_name", "Uploaded pool")

    st.title("CRE Credit Risk")
    st.caption(pool_name)
    if st.button("← Choose a different pool"):
        reset()
        st.rerun()

    tab_results, tab_detail = st.tabs(["Results", "Loan detail & export"])
    with tab_results:
        screen_results(scored)
    with tab_detail:
        screen_detail(scored, pool_name)


if __name__ == "__main__":
    main()
