#!/usr/bin/env python3
"""Generate born-digital sample 'insurance binder' PDFs — a NEW doc type the
config agent has never seen. Synthetic/fictional. Run: `python samples_binder/make_samples.py`."""
import os

from fpdf import FPDF

HERE = os.path.dirname(os.path.abspath(__file__))


def binder(path, lines):
    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    w = pdf.epw  # effective page width (avoids fpdf2's w=0 quirk)
    for txt, size, bold in lines:
        pdf.set_font("Helvetica", style="B" if bold else "", size=size)
        if txt == "":
            pdf.ln(4)
        else:
            pdf.cell(w, 6, txt, new_x="LMARGIN", new_y="NEXT")
    pdf.output(path)


BANNER = [
    ("INSURANCE BINDER", 15, True),
    ("SYNTHETIC - FICTIONAL DATA - NOT A REAL FORM", 8, False),
    ("", 11, False),
    ("This binder confirms coverage is bound pending issuance of the policy.", 10, False),
    ("", 11, False),
]

binder(os.path.join(HERE, "BINDER-3001_Harborview.pdf"), BANNER + [
    ("Binder Number: BND-2026-3001     Effective Time: 12:01 AM", 11, False),
    ("Producing Agency: Brightline Insurance Brokers", 11, False),
    ("Insured (Named): Harborview Logistics LLC", 11, False),
    ("Insurer / Carrier: Pacific Crest Mutual Ins Co (NAIC# 27812)", 11, False),
    ("Policy Number: GL-88421", 11, False),
    ("Binder Effective Date (MM/DD/YYYY): 06/15/2026", 11, False),
    ("Binder Expiration Date (MM/DD/YYYY): 07/15/2026", 11, False),
    ("Coverage Type: Commercial General Liability", 11, False),
    ("Each Occurrence Limit: $2,000,000", 11, False),
    ("General Aggregate: $4,000,000", 11, False),
    ("Premium (estimated): $4,250", 11, False),
    ("", 11, False),
    ("Authorized Representative: Renee Alvarado     Date: 06/15/2026", 10, False),
])

binder(os.path.join(HERE, "BINDER-3002_Lumen.pdf"), BANNER + [
    ("Binder Number: BND-2026-3002     Effective Time: 12:01 AM", 11, False),
    ("Producing Agency: Anchor Risk Partners", 11, False),
    ("Insured (Named): Lumen Tech Services", 11, False),
    ("Insurer / Carrier: Beacon Professional Indemnity (NAIC# 41209)", 11, False),
    ("Policy Number: PL-11920", 11, False),
    ("Binder Effective Date (MM/DD/YYYY): 06/20/2026", 11, False),
    ("Binder Expiration Date (MM/DD/YYYY): 07/20/2026", 11, False),
    ("Coverage Type: Professional Liability (E&O)", 11, False),
    ("Each Claim Limit: $3,000,000", 11, False),
    ("Aggregate: $6,000,000", 11, False),
    ("Premium (estimated): $7,900", 11, False),
    ("", 11, False),
    ("Authorized Representative: David Okafor     Date: 06/20/2026", 10, False),
])

print("wrote BINDER-3001_Harborview.pdf, BINDER-3002_Lumen.pdf")
