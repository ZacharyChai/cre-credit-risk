"""Generates a findings-memo-style PDF from whatever pool is currently loaded.

Unlike analysis/findings.md (a fixed writeup for the GS 2017-GS6/GS7 pool), this
renders live from the segmented dataframe, so the memo matches whatever loan tape
the user uploaded or selected.
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from segmentation import TIER_ORDER, tier_summary

STATUS_COLOR = {
    "Low": colors.HexColor("#0ca30c"),
    "Watch": colors.HexColor("#fab219"),
    "Elevated": colors.HexColor("#ec835a"),
    "Acute": colors.HexColor("#d03b3b"),
}


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("MemoTitle", parent=ss["Title"], fontSize=16, spaceAfter=6))
    ss.add(ParagraphStyle("MemoBody", parent=ss["BodyText"], fontSize=10, leading=14))
    ss.add(ParagraphStyle("MemoH2", parent=ss["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=6))
    return ss


def generate_memo_pdf(scored, pool_name: str = "Uploaded pool") -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story = []

    total_balance = scored["current_balance"].sum()
    summary = tier_summary(scored)
    ea = summary[summary["risk_tier"].isin(["Elevated", "Acute"])]
    ea_balance = ea["balance"].sum()
    ea_pct = 100 * ea_balance / total_balance if total_balance else 0

    story.append(Paragraph("CRE Credit Risk: Loan-Level Distress Analysis", styles["MemoTitle"]))
    story.append(Paragraph(
        f"{pool_name} — {len(scored)} active real-estate loans, "
        f"${total_balance/1e6:,.1f}M.",
        styles["MemoBody"],
    ))

    story.append(Paragraph("Where the risk sits", styles["MemoH2"]))
    story.append(Paragraph(
        f"{ea_pct:.1f}% of pool balance (${ea_balance/1e6:,.1f}M) sits in the "
        "Elevated or Acute risk tier, based on pro-forma refinance DSCR — each "
        "loan's reported DSCR rescaled to an estimated takeout rate, escalated "
        "for high leverage or Office/Lodging exposure.",
        styles["MemoBody"],
    ))
    story.append(Spacer(1, 8))

    tier_rows = [["Tier", "Loans", "Balance", "% of pool"]]
    for _, r in summary.iterrows():
        tier_rows.append([
            r["risk_tier"], int(r["loans"]),
            f"${r['balance']/1e6:,.1f}M", f"{r['pct_of_pool']:.1f}%",
        ])
    tier_table = Table(tier_rows, colWidths=[1.3 * inch, 1 * inch, 1.5 * inch, 1.3 * inch])
    tier_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e0d9")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, tier in enumerate(summary["risk_tier"], start=1):
        tier_style.append(("TEXTCOLOR", (0, i), (0, i), STATUS_COLOR.get(tier, colors.black)))
        tier_style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
    tier_table.setStyle(TableStyle(tier_style))
    story.append(tier_table)

    acute = scored[scored["risk_tier"] == "Acute"].sort_values("pro_forma_dscr")
    if not acute.empty:
        story.append(Paragraph("Acute loans, weakest first", styles["MemoH2"]))
        acute_rows = [["Loan", "Property type", "Balance", "DSCR today", "Pro-forma DSCR"]]
        for _, r in acute.head(15).iterrows():
            name = str(r.get("property_name") or r.get("loan_id"))
            if len(name) > 22:
                name = name[:21].rstrip() + "…"
            acute_rows.append([
                name, r["property_type"], f"${r['current_balance']/1e6:,.1f}M",
                f"{r['dscr']:.2f}x", f"{r['pro_forma_dscr']:.2f}x",
            ])
        acute_table = Table(
            acute_rows,
            colWidths=[1.9 * inch, 1.1 * inch, 1 * inch, 0.9 * inch, 1.1 * inch],
        )
        acute_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e0d9")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(acute_table)
        if len(acute) > 15:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"({len(acute) - 15} additional Acute loans not shown — see the "
                "loan-level table in the app for the full list.)",
                styles["MemoBody"],
            ))

    story.append(Paragraph("Property type", styles["MemoH2"]))
    by_type_rows = [["Property type", "Loans", "Balance", "% Elevated/Acute"]]
    for ptype, g in scored.groupby("property_type", observed=True):
        bal = g["current_balance"].sum()
        ea_bal = g[g["risk_tier"].isin(["Elevated", "Acute"])]["current_balance"].sum()
        pct = 100 * ea_bal / bal if bal else 0
        by_type_rows.append([ptype, len(g), f"${bal/1e6:,.1f}M", f"{pct:.0f}%"])
    by_type_table = Table(by_type_rows, colWidths=[1.6 * inch, 0.9 * inch, 1.3 * inch, 1.4 * inch])
    by_type_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e0d9")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(by_type_table)

    story.append(Paragraph("Method", styles["MemoH2"]))
    story.append(Paragraph(
        "Pro-forma DSCR = reported DSCR × (current coupon ÷ estimated takeout rate). "
        "Escalated one tier for LTV above 80% (excluding pari-passu note pieces, where "
        "per-slice LTV understates true leverage) or Office/Lodging property type. "
        "Generated from live input data; verify source data quality before acting on "
        "these results.",
        styles["MemoBody"],
    ))

    doc.build(story)
    return buf.getvalue()
