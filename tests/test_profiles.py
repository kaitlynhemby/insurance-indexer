#!/usr/bin/env python3
"""Deterministic checks for the per-insurer profiles (no model, no network).

The router's document_type classification is accuracy-graded separately
(router.py --grade); the profile layer on top is a deterministic config lookup,
so it's unit-tested here: both shipped profiles lint clean, and the SAME line of
business routes to the right department per insurer (the per-company-adaptation
guarantee).  Run: `python tests/test_profiles.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profiles as P  # noqa: E402


def main() -> int:
    failures = []

    def check(label, cond):
        print(f"  [{'ok' if cond else 'FAIL'}] {label}")
        if not cond:
            failures.append(label)

    h = P.load_profile(P.profile_path("harborview-mga"))
    s = P.load_profile(P.profile_path("sierra-surplus"))

    print("profiles lint clean:")
    check("harborview-mga", P.lint_profile(h) == [])
    check("sierra-surplus", P.lint_profile(s) == [])

    print("LOB → department per insurer:")
    # admitted MGA keeps everything in CL; the E&S wholesaler splits to CAS/SPEC
    expect = {
        "general_liability":     ("CL", "CAS"),
        "professional_liability":("CL", "SPEC"),
        "umbrella":              ("CL", "SPEC"),
        "property":              ("PROP", "PROP"),
        "workers_comp":          ("WC", "CAS"),
    }
    for lob, (eh, es) in expect.items():
        check(f"{lob}: Harborview={eh}", P.resolve_department(lob, h) == eh)
        check(f"{lob}: Sierra={es}", P.resolve_department(lob, s) == es)

    print("the same doc routes differently per insurer:")
    check("professional_liability differs (CL vs SPEC)",
          P.resolve_department("professional_liability", h) != P.resolve_department("professional_liability", s))

    print("FNOL loss_type maps via representative LOB:")
    check("auto loss → CL (Harborview)", P.resolve_department("auto", h) == "CL")
    check("auto loss → CAS (Sierra)", P.resolve_department("auto", s) == "CAS")

    print("mock agency-code resolution (case-insensitive containment):")
    check("Brightline → BRT-114 (Harborview)", P.resolve_agency("Brightline Insurance Brokers", h) == "BRT-114")
    check("Brightline → BRI-7781 (Sierra)", P.resolve_agency("Brightline Insurance Brokers", s) == "BRI-7781")
    check("unknown producer → None", P.resolve_agency("Nonexistent Agency", h) is None)

    print("enrich() shape:")
    e = P.enrich("professional_liability", "Anchor Risk Partners", s)
    check("enrich keys", set(e) == {"profile", "insurer", "market_type", "department", "agency_code"})
    check("enrich values", e["department"] == "SPEC" and e["agency_code"] == "ANC-3390" and e["market_type"] == "surplus")

    print("-" * 50)
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("all profile checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
