#!/usr/bin/env python3
"""Generate born-digital sample 'insurance binder' PDFs — synthetic/fictional.

Dense, realistic ACORD-binder-style layout: producer + insured blocks, carrier
with NAIC/AM Best, a full limits schedule (per-occurrence + aggregate + sub-limits
+ deductible), premium & terms, prior-to-bind conditions, and a signature line.
The schema-captured values are unchanged from the answer key; the extra detail is
DISTRACTORS the extractor must avoid (prior policy #, date-bound vs effective,
aggregate vs per-occurrence, sub-limits, taxes vs premium). Run:
  python samples_binder/make_samples.py
"""
import os

from fpdf import FPDF

HERE = os.path.dirname(os.path.abspath(__file__))
INK = (33, 30, 24)
MUTE = (120, 110, 92)

BINDERS = [
    {
        "file": "BINDER-3001_Harborview.pdf",
        "binder_no": "BND-2026-3001", "quote_ref": "Q-558210", "revision": "0",
        "eff": "06/15/2026", "eff_time": "12:01 AM", "exp": "07/15/2026", "date_bound": "06/15/2026",
        "producer": ["Brightline Insurance Brokers", "1200 Market Center Dr, Suite 400",
                     "Seattle, WA 98101", "Contact: Renee Alvarado  (206) 555-0142"],
        "insured": ["Harborview Logistics LLC", "4490 Industrial Pkwy", "Kent, WA 98032",
                    "Entity: LLC    FEIN: **-***4821"],
        "carrier": "Pacific Crest Mutual Ins Co", "naic": "27812", "ambest": "A (Excellent)",
        "policy": "GL-88421", "prior_policy": "EI-99001 (expired 12/31/2025)",
        "lob": "Commercial General Liability", "form": "Occurrence",
        "limits": [
            ("Each Occurrence", "$2,000,000"),
            ("General Aggregate", "$4,000,000"),
            ("Products / Completed Ops Aggregate", "$4,000,000"),
            ("Personal & Advertising Injury", "$2,000,000"),
            ("Damage to Rented Premises", "$100,000"),
            ("Medical Expense (any one person)", "$5,000"),
            ("Deductible (per occurrence)", "$2,500"),
        ],
        "premium": "$4,250", "taxes": "$187", "min_earned": "25%", "pay_plan": "Annual",
        "conditions": [
            "Signed ACORD application required within 10 days of bind.",
            "Subject to satisfactory 5-year loss runs.",
            "Additional Insured: Cascade Property Group (per written contract).",
            "Waiver of Subrogation applies where required by written contract.",
        ],
        "rep": "Renee Alvarado",
    },
    {
        "file": "BINDER-3002_Lumen.pdf",
        "binder_no": "BND-2026-3002", "quote_ref": "Q-601774", "revision": "0",
        "eff": "06/20/2026", "eff_time": "12:01 AM", "exp": "07/20/2026", "date_bound": "06/20/2026",
        "producer": ["Anchor Risk Partners", "900 Pacific Ave, Suite 310",
                     "Tacoma, WA 98402", "Contact: David Okafor  (206) 555-0177"],
        "insured": ["Lumen Tech Services", "77 Lakeview Center", "Bellevue, WA 98004",
                    "Entity: Inc.    FEIN: **-***1190"],
        "carrier": "Beacon Professional Indemnity", "naic": "41209", "ambest": "A- (Excellent)",
        "policy": "PL-11920", "prior_policy": "BP-44021 (expired 03/14/2026)",
        "lob": "Professional Liability (E&O)", "form": "Claims-Made",
        "limits": [
            ("Each Claim", "$3,000,000"),
            ("Aggregate", "$6,000,000"),
            ("Defense Costs", "Inside Limits"),
            ("Deductible (each claim)", "$10,000"),
            ("Retroactive Date", "03/15/2022"),
        ],
        "premium": "$7,900", "taxes": "$340", "min_earned": "100% (claims-made)", "pay_plan": "Annual",
        "conditions": [
            "Claims-made form; prior acts covered to the retroactive date shown.",
            "Signed application and prior-acts warranty required within 10 days.",
            "No knowledge of prior acts, errors, or circumstances likely to give rise to a claim.",
            "Subject to underwriting review of the last 3 years of revenue.",
        ],
        "rep": "David Okafor",
    },
]


def render(b, path):
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(14, 12, 14)
    pdf.add_page()
    W = pdf.epw
    LX, RX = 14, 112  # left / right column x

    def rule(gap_before=1.5, gap_after=2.0, color=(210, 200, 180)):
        pdf.ln(gap_before)
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.3)
        pdf.line(14, pdf.get_y(), 14 + W, pdf.get_y())
        pdf.ln(gap_after)

    def section(title):
        rule(2.5, 2.2)
        pdf.set_text_color(*MUTE)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 4, title.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)
        pdf.ln(1)

    def line(txt, size=9, style="", h=4.4):
        pdf.set_font("Helvetica", style, size)
        pdf.cell(0, h, txt, new_x="LMARGIN", new_y="NEXT")

    # ---- title bar ----
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(120, 9, "INSURANCE BINDER", new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(14 + W - 86, y0 + 1)
    pdf.cell(86, 7, f"BINDER NO: {b['binder_no']}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(14, y0 + 9)
    pdf.set_text_color(*MUTE)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(0, 4, "SYNTHETIC - FICTIONAL DATA - NOT A REAL ACORD FORM", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(W, 3.8, "This binder is a temporary contract of insurance, effective only as indicated "
                   "below, and is subject to all terms of the policy/policies in current use by the company.")
    rule(2, 2)

    # ---- dates line ----
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 4.6, f"BINDER EFFECTIVE (MM/DD/YYYY): {b['eff']}    EFFECTIVE TIME: {b['eff_time']}    "
             f"BINDER EXPIRATION (MM/DD/YYYY): {b['exp']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*MUTE)
    pdf.cell(0, 4.4, f"Date Bound: {b['date_bound']}    Revision: {b['revision']}    Quote Ref: {b['quote_ref']}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)

    # ---- producer + insured (stacked, labeled — keeps each value on one clean
    #      line so it grounds verbatim; side-by-side columns interleave in the
    #      PDF text layer and break the source-span check) ----
    section("Producer / Insured")
    line(f"PRODUCER: {b['producer'][0]}", 9, "B")
    pdf.set_text_color(*MUTE)
    for extra in b["producer"][1:]:
        line("    " + extra, 8, h=4.0)
    pdf.set_text_color(*INK)
    pdf.ln(0.8)
    line(f"INSURED: {b['insured'][0]}", 9, "B")
    pdf.set_text_color(*MUTE)
    for extra in b["insured"][1:]:
        line("    " + extra, 8, h=4.0)
    pdf.set_text_color(*INK)

    # ---- carrier ----
    section("Insurer Affording Coverage")
    line(f"Insurer / Carrier: {b['carrier']}", 9, "B")
    line(f"NAIC #: {b['naic']}    AM Best Rating: {b['ambest']}", 8.5)
    line(f"Bound Policy Number: {b['policy']}", 9, "B")
    line(f"Prior Policy: {b['prior_policy']}", 8.5)
    pdf.set_text_color(*INK)

    # ---- coverage bound + limits schedule ----
    section("Coverage Bound")
    line(f"Line of Business: {b['lob']}    Coverage Form: {b['form']}", 9, "B")
    pdf.ln(0.5)
    for label, amount in b["limits"]:
        yy = pdf.get_y()
        pdf.set_font("Helvetica", "", 9)
        pdf.set_xy(LX + 4, yy); pdf.cell(120, 4.4, label)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(LX + 4, yy); pdf.cell(W - 8, 4.4, amount, align="R", new_x="LMARGIN", new_y="NEXT")

    # ---- premium & terms ----
    section("Premium & Terms")
    line(f"Estimated Annual Premium: {b['premium']}    Taxes & Fees: {b['taxes']}    "
         f"Minimum Earned: {b['min_earned']}", 9)
    line(f"Payment Plan: {b['pay_plan']}    Premium Financed: No", 8.5)

    # ---- conditions ----
    section("Conditions / Prior to Bind")
    pdf.set_font("Helvetica", "", 8.6)
    for c in b["conditions"]:
        pdf.set_x(LX)
        pdf.multi_cell(W, 4.0, f"-  {c}")
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTE)
    pdf.multi_cell(W, 3.8, "This binder may be cancelled in accordance with the policy provisions. 30-day "
                   "notice of cancellation applies except 10 days for non-payment of premium.")
    pdf.set_text_color(*INK)

    # ---- signature + footer ----
    rule(3, 2.5)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, f"AUTHORIZED REPRESENTATIVE: {b['rep']}        Title: Authorized Representative        "
             f"Date: {b['date_bound']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTE)
    pdf.cell(0, 4, "INSURANCE BINDER (SYN) - SYNTHETIC / FICTIONAL DATA - NOT A REAL ACORD FORM - Page 1 of 1",
             new_x="LMARGIN", new_y="NEXT")

    pdf.output(path)


for b in BINDERS:
    render(b, os.path.join(HERE, b["file"]))
print("wrote", ", ".join(b["file"] for b in BINDERS))
