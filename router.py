#!/usr/bin/env python3
"""router.py — pre-extraction document triage (the schema SELECTOR).

The pipeline is schema-agnostic: extract.py applies whatever schema it's given.
But nothing decided WHICH schema applies to an inbound PDF — workflow.py used a
single active.schema.json for all of inbox/. This stage fills that gap: it reads
a PDF, classifies its document_type (grounded in the text), and selects the
matching config/<DocType>.schema.json so a MIXED inbox (COIs + FNOLs + binders,
as different insurers send) is each extracted against the right schema with no
manual config swap.

It is a thin STAGE, not an agent: one grounded model call reusing
extract.call_model + the extraction-envelope shape, so the routing decision is
itself gradeable (grounding/confidence) and accuracy-checked against
answer-key.json's `routing_set`. Builder-side; it never queries the index.

  python router.py --doc COI-1002_Sierra      # show the routing decision
  python router.py --grade                     # accuracy gate over routing_set (exits 0 on pass)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, Optional, Tuple

import extract
import pdftext
import profiles
import schema_util as S
import verifier as V

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config")
INBOX = os.path.join(ROOT, "inbox")
CONF_THRESHOLD = V.CONF_THRESHOLD

SYSTEM_ROUTER = (
    "You are a non-interactive insurance document-classification function. You identify what TYPE "
    "of insurance document a PDF is so the right extraction schema can be selected. Do NOT use tools, "
    "do NOT explain. Respond with ONLY a single JSON object."
)


def schema_registry() -> Dict[str, dict]:
    """Map each known document_type const -> {title, path} from config/*.schema.json
    (excluding the active copy). This is the set of types the router can select."""
    reg: Dict[str, dict] = {}
    for p in sorted(glob.glob(os.path.join(CONFIG, "*.schema.json"))):
        if os.path.basename(p) == "active.schema.json":
            continue
        try:
            s = S.load_schema(p)
        except Exception:
            continue
        dt = s.get("properties", {}).get("document_type", {}).get("const")
        if dt:
            reg[dt] = {"title": s.get("title"), "path": p}
    return reg


def classify_doc(pdf_path: str) -> dict:
    """Return a grounded routing envelope:
    {document_type:{value,confidence,source,needs_review}, line_of_business:{...}}.
    document_type.value is one of the known schema consts (or null if unknown)."""
    reg = schema_registry()
    known = sorted(reg.keys())
    doc_text = pdftext.full_text(pdf_path)
    user = "\n".join([
        "Classify this insurance document so the correct extraction schema can be selected.",
        "",
        f"KNOWN document_type values (choose EXACTLY one, or null if none clearly fit): {known}",
        "",
        "Return ONE JSON object with this shape (the extraction-envelope shape):",
        json.dumps({
            "document_type": {"value": "<one of the known values | null>", "confidence": 0.0,
                              "source": {"page": 1, "text_span": "<verbatim title/marker proving the type>"},
                              "needs_review": False},
            "line_of_business": {"value": "<e.g. general_liability, professional_liability, commercial_auto, "
                                 "workers_comp, property, or null>", "confidence": 0.0,
                                 "source": {"page": 1, "text_span": "<verbatim coverage/LOB text>"},
                                 "needs_review": False},
        }, indent=2),
        "Rules: document_type.value MUST be one of the known values exactly, or null if the document is "
        "not one of these types. source.text_span must be a verbatim substring of the document (e.g. "
        "'CERTIFICATE OF LIABILITY INSURANCE', 'FIRST NOTICE OF LOSS', 'INSURANCE BINDER'). Set "
        "confidence < 0.85 and needs_review=true when the type is ambiguous or the document is degraded.",
        "",
        "DOCUMENT TEXT:",
        doc_text,
        "",
        "Return ONLY the JSON object.",
    ])
    env = extract.call_model(user, SYSTEM_ROUTER)
    # enforce routing invariant locally (mirror extract._normalize_cell)
    for cell in env.values():
        if isinstance(cell, dict):
            conf = cell.get("confidence")
            if cell.get("value") is None or (isinstance(conf, (int, float)) and conf < CONF_THRESHOLD):
                cell["needs_review"] = True
    return env


def route_one(pdf_path: str, profile: Optional[dict] = "__active__") -> Tuple[Optional[dict], dict]:
    """Classify and select. Returns (selected_schema_obj | None, decision dict).
    decision = {document_type, line_of_business, confidence, schema_title, routing_envelope,
    [department, market_type, profile]}. If a per-insurer profile is active (or passed),
    the decision is enriched with the insurer's department + market type (agency_code is
    resolved post-extraction in annotate, where the producer is known)."""
    if profile == "__active__":
        profile = profiles.active_profile()
    env = classify_doc(pdf_path)
    reg = schema_registry()
    dt_cell = env.get("document_type", {})
    dt = dt_cell.get("value")
    conf = dt_cell.get("confidence")
    lob = env.get("line_of_business", {}).get("value")
    selected = None
    title = None
    # select only on a confident, grounded, known type
    if dt in reg and isinstance(conf, (int, float)) and conf >= CONF_THRESHOLD and not dt_cell.get("needs_review"):
        # grounding check: the span must be verbatim in the source
        span = (dt_cell.get("source") or {}).get("text_span", "")
        if pdftext.span_anywhere(span, pdf_path) is not None:
            selected = S.load_schema(reg[dt]["path"])
            title = selected.get("title")
    decision = {
        "document_type": dt,
        "line_of_business": lob,
        "confidence": conf,
        "schema_title": title,
        "routing_envelope": env,
    }
    if profile:
        decision["profile"] = profile.get("insurer_id")
        decision["insurer"] = profile.get("display_name")
        decision["market_type"] = profile.get("market_type")
        decision["department"] = profiles.resolve_department(lob, profile)
    return selected, decision


# --------------------------------------------------------------------------
# accuracy gate (the critic's requirement: the SELECTION must be graded)
# --------------------------------------------------------------------------
def grade(verbose: bool = True) -> bool:
    """Run classify/select over the labeled routing_set and check the selected
    document_type + schema_title match expectations. Exits 0 iff all match."""
    answer_key = V._answer_key()
    routing_set = answer_key.get("routing_set", {})
    if not routing_set:
        print("router: no routing_set in answer-key.json — nothing to grade")
        return False
    ok_all = True
    if verbose:
        print("=" * 64)
        print("ROUTER ACCURACY (answer-key.json routing_set)")
        print("=" * 64)
    for fname, exp in sorted(routing_set.items()):
        if fname.startswith("_"):
            continue  # skip _comment and other metadata keys
        pdf = os.path.join(INBOX, fname)
        if not os.path.exists(pdf):
            ok_all = False
            if verbose:
                print(f"[FAIL] {fname}: not found in inbox/")
            continue
        _, dec = route_one(pdf, profile=None)  # grade the model classification, profile-independent
        dt_ok = dec["document_type"] == exp.get("document_type")
        title_ok = dec["schema_title"] == exp.get("schema_title")
        ok = dt_ok and title_ok
        ok_all &= ok
        if verbose:
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {fname:<32} -> type={dec['document_type']!r} "
                  f"schema={dec['schema_title']!r} (conf={dec['confidence']})")
            if not ok:
                print(f"        expected type={exp.get('document_type')!r} schema={exp.get('schema_title')!r}")
    if verbose:
        print("-" * 64)
        print(f"ROUTING: {'PASS — exits 0' if ok_all else 'FAIL — exits 1'}")
        print("=" * 64)
    return ok_all


# --------------------------------------------------------------------------
# per-insurer annotation (the viewer hook — deterministic, no re-extraction)
# --------------------------------------------------------------------------
def _record_lob_and_producer(record: dict):
    """Derive a representative line_of_business + producer name from a record's
    already-extracted values (no model call), so a profile can enrich it."""
    reg = V._schemas_by_title()
    schema = reg.get(record.get("schema_title"))
    if not schema:
        return None, None
    vals = S.value_layer(record.get("extraction", {}), schema)
    lob = None
    cov = vals.get("coverages")
    if isinstance(cov, list) and cov:
        lob = cov[0].get("coverage_type")          # COI: primary coverage
    elif vals.get("coverage_type"):
        lob = vals.get("coverage_type")             # binder
    elif vals.get("loss_type"):
        lob = vals.get("loss_type")                 # FNOL (resolve_department maps it)
    producer = vals.get("producer") or vals.get("producing_agency")
    return lob, producer


def annotate(profile_id: Optional[str] = None, verbose: bool = True) -> bool:
    """Write a per-insurer `routing` block onto every indexed/queued record using
    the active (or named) profile — deterministically from already-extracted
    values, so extraction records and the verifier are untouched."""
    profile = profiles.load_profile(profiles.profile_path(profile_id)) if profile_id else profiles.active_profile()
    if not profile:
        print("router: no active profile to annotate with (config/profiles/active.json)")
        return False
    reg = V._schemas_by_title()
    paths = sorted(glob.glob(os.path.join(ROOT, "index", "*.json"))
                   + glob.glob(os.path.join(ROOT, "review-queue", "*.json")))
    if verbose:
        print(f"annotating {len(paths)} record(s) with profile '{profile['display_name']}':")
    for p in paths:
        rec = json.load(open(p))
        lob, producer = _record_lob_and_producer(rec)
        dt = (reg.get(rec.get("schema_title"), {}).get("properties", {})
              .get("document_type", {}).get("const"))
        rec["routing"] = {"document_type": dt, "line_of_business": lob, **profiles.enrich(lob, producer, profile)}
        json.dump(rec, open(p, "w"), indent=2)
        if verbose:
            r = rec["routing"]
            print(f"  {rec['doc_id']:<30} {r['document_type']} → dept {r['department']} "
                  f"· agency {r['agency_code']} · {r['insurer']}")
    return True


def main():
    ap = argparse.ArgumentParser(description="Pre-extraction document router (schema selector)")
    ap.add_argument("--doc", help="show the routing decision for one inbox PDF (stem or filename)")
    ap.add_argument("--grade", action="store_true", help="accuracy gate over answer-key routing_set")
    ap.add_argument("--annotate", action="store_true",
                    help="write per-insurer routing metadata onto indexed records (for the viewer)")
    ap.add_argument("--profile", help="insurer profile id (default: the active profile)")
    args = ap.parse_args()
    if args.grade:
        sys.exit(0 if grade() else 1)
    if args.annotate:
        sys.exit(0 if annotate(args.profile) else 1)
    if args.doc:
        stem = os.path.splitext(args.doc)[0]
        pdf = os.path.join(INBOX, stem + ".pdf")
        if not os.path.exists(pdf):
            raise SystemExit(f"no such PDF in inbox/: {args.doc}")
        prof = profiles.load_profile(profiles.profile_path(args.profile)) if args.profile else "__active__"
        selected, dec = route_one(pdf, profile=prof)
        print(json.dumps({k: v for k, v in dec.items() if k != "routing_envelope"}, indent=2))
        print(f"selected schema: {dec['schema_title'] or '(none — would route to review-queue)'}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
