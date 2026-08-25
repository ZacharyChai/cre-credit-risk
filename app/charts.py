"""Plotly chart builders for the results screen.

Same color logic as the static analysis charts (analysis/charts/): status colors
(good/warning/serious/critical) are reserved for risk tiers and never reused for a
plain series; magnitude elsewhere uses a single sequential blue hue.
"""

import plotly.graph_objects as go

from segmentation import TIER_ORDER

STATUS_COLOR = {"Low": "#0ca30c", "Watch": "#fab219", "Elevated": "#ec835a", "Acute": "#d03b3b"}
SEQ_BLUE = "#2a78d6"
INK_PRIMARY = "#0b0b0b"
GRIDLINE = "#e1e0d9"

LAYOUT_DEFAULTS = dict(
    plot_bgcolor="#fcfcfb",
    paper_bgcolor="#fcfcfb",
    font=dict(family="sans-serif", color=INK_PRIMARY, size=13),
    margin=dict(l=10, r=10, t=50, b=10),
)


def tier_bar_chart(summary) -> go.Figure:
    ordered = summary.set_index("risk_tier").reindex(TIER_ORDER).reset_index()
    fig = go.Figure(
        go.Bar(
            y=ordered["risk_tier"],
            x=ordered["balance"] / 1e6,
            orientation="h",
            marker_color=[STATUS_COLOR[t] for t in ordered["risk_tier"]],
            text=[
                f"${b/1e6:,.1f}M ({p:.1f}%)"
                for b, p in zip(ordered["balance"], ordered["pct_of_pool"])
            ],
            textposition="outside",
            hovertemplate="%{y}: $%{x:,.1f}M<extra></extra>",
        )
    )
    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title="Pool balance by risk tier",
        xaxis=dict(title="Balance ($M)", gridcolor=GRIDLINE, zeroline=False),
        yaxis=dict(autorange="reversed"),
        height=320,
    )
    return fig


def dscr_histogram(scored) -> go.Figure:
    fig = go.Figure(
        go.Histogram(
            x=scored["pro_forma_dscr"],
            nbinsx=20,
            marker_color=SEQ_BLUE,
            marker_line=dict(color="#fcfcfb", width=1.5),
            hovertemplate="Pro-forma DSCR: %{x:.2f}x<br>Loans: %{y}<extra></extra>",
        )
    )
    fig.add_vline(
        x=1.0, line_dash="dash", line_color="#898781",
        annotation_text="1.00x break-even", annotation_position="top",
    )
    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title="Pro-forma refinance DSCR distribution",
        xaxis=dict(title="Pro-forma DSCR at estimated takeout rate", gridcolor=GRIDLINE),
        yaxis=dict(title="Loans", gridcolor=GRIDLINE),
        height=360,
        bargap=0.05,
    )
    return fig


def maturity_wall_chart(scored) -> go.Figure:
    dates = scored["maturity_date"].dropna()
    if dates.empty:
        return go.Figure()
    quarter = dates.str[:4] + "-Q" + ((dates.str[5:7].astype(int) + 2) // 3).astype(str)
    by_q = scored.assign(_q=quarter).groupby("_q")["current_balance"].sum().sort_index()
    total = by_q.sum()

    fig = go.Figure(
        go.Bar(
            x=by_q.index,
            y=by_q.values / 1e6,
            marker_color=SEQ_BLUE,
            text=[f"${v/1e6:,.0f}M ({100*v/total:.0f}%)" for v in by_q.values],
            textposition="outside",
            hovertemplate="%{x}: $%{y:,.1f}M<extra></extra>",
        )
    )
    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title="Maturity wall: balance by quarter",
        xaxis=dict(title=""),
        yaxis=dict(title="Balance ($M)", gridcolor=GRIDLINE, zeroline=False),
        height=360,
    )
    return fig
