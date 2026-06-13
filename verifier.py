#!/usr/bin/env python3
"""verifier.py — independent, fresh-context grader (see verifier-rubric.md).

This NEVER trusts the builder's claimed values. It re-reads the source PDF, the
active schema, and the answer key, and re-derives every gate mechanically:

  GATE 1  span grounding        every populated field's span is verbatim in the source
  GATE 2  schema conformance    the .value layer validates against active.schema.json
  GATE 3  confidence routing    conf<0.85 => needs_review, and such records live in review-queue/
  GATE 4  no fabrication        a non-null value must be grounded; an ungrounded value must be null
  GATE 5  reconciliation        an updated doc's diff is exactly the fields whose grounded value changed
  GATE 6  accuracy vs truth     labeled-set values match config/answer-key.json after normalization

Exit 0 iff the whole run passes. Run from the repo root.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, List, Optional

import jsonschema

import normalize as N
import pdftext
import schema_util as S

ROOT = os.path.dirname(os.path.abspath(__file__))
CONF_THRESHOLD = 0.85


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _load_json(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _answer_key() -> dict:
    return _load_json(os.path.join(ROOT, "config", "answer-key.json"))


def _active_schema() -> dict:
    return S.load_schema(os.path.join(ROOT, "config", "active.schema.json"))


def _doc_key(record: dict) -> str:
    """Answer-key key, e.g. 'COI-1001_Harborview.pdf'."""
    return os.path.basename(record.get("source_pdf", record["doc_id"] + ".pdf"))


def _grounded(wrapper: dict, kind: str, pdf_path: str) -> Optional[str]:
    """Return None if grounded, else a human reason string."""
    value = wrapper.get("value")
    src = wrapper.get("source") or {}
    span = src.get("text_span") or ""
    page = src.get("page")
    if not span.strip():
        return "no source span provided"
    found_page = pdftext.span_anywhere(span, pdf_path)
    if found_page is None:
        return f"span not found verbatim in source: {span!r}"
    # provenance holds. Now value-derivability for literal kinds.
    if kind == "date":
        if N.to_iso_date(value) not in N.find_iso_dates(span):
            return f"date {value!r} not derivable from span {span!r}"
    elif kind == "number":
        if N.parse_amount(value) not in N.find_amounts(span):
            return f"amount {value!r} not derivable from span {span!r}"
    elif kind == "string":
        v = N.norm_str(value).casefold()
        s = N.norm_str(span).casefold()
        if v and v not in s and s not in v:
            return f"string {value!r} not contained in span {span!r}"
    # enum / const: provenance-only (canonical vocab); Gate 6 proves meaning.
    return None


def _compare(kind: str, got, expected) -> bool:
    if kind == "date":
        return (N.to_iso_date(got) or got) == (N.to_iso_date(expected) or expected)
    if kind == "number":
        return N.parse_amount(got) == N.parse_amount(expected)
    return N.norm_str(got) == N.norm_str(expected)


# --------------------------------------------------------------------------
# the gates
# --------------------------------------------------------------------------
def gate_grounding_and_fabrication(env, active, pdf_path, reasons):
    g1 = g4 = True
    for path, wrapper, kind in S.iter_fields(env, active):
        value = wrapper.get("value")
        if value is None:
            continue  # nothing to ground; fabrication handled by "non-null => grounded"
        reason = _grounded(wrapper, kind, pdf_path)
        if reason:
            g1 = False
            g4 = False  # a non-null, ungrounded value IS fabrication
            reasons.append(f"GATE1/4 {path}: {reason}")
    return g1, g4


def gate_schema(env, active, reasons):
    values = S.value_layer(env, active)
    # FORMAT_CHECKER makes `"format": "date"` an enforced constraint, not just an
    # annotation — so a malformed date is a real Gate 2 violation.
    validator = jsonschema.Draft7Validator(active, format_checker=jsonschema.FormatChecker())
    errs = sorted(validator.iter_errors(values), key=lambda e: list(e.path))
    for e in errs:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        reasons.append(f"GATE2 {loc}: {e.message}")
    return not errs


def gate_confidence(env, active, status, reasons):
    ok = True
    record_has_review = False
    for path, wrapper, kind in S.iter_fields(env, active):
        conf = wrapper.get("confidence")
        needs = bool(wrapper.get("needs_review"))
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            ok = False
            reasons.append(f"GATE3 {path}: confidence {conf!r} not in [0,1]")
            continue
        if conf < CONF_THRESHOLD and not needs:
            ok = False
            reasons.append(
                f"GATE3 {path}: confidence {conf} < {CONF_THRESHOLD} but needs_review=false"
            )
        if wrapper.get("value") is None and not needs:
            ok = False
            reasons.append(f"GATE3 {path}: null value not marked needs_review")
        if needs or conf < CONF_THRESHOLD or wrapper.get("value") is None:
            record_has_review = True
    # record-level routing
    if record_has_review and status != "review":
        ok = False
        reasons.append(
            "GATE3 (record): has low-confidence/null fields but is in index/, not review-queue/"
        )
    if not record_has_review and status == "review":
        ok = False
        reasons.append(
            "GATE3 (record): in review-queue/ but every field is confident & populated"
        )
    return ok


def gate_accuracy(env, active, doc_key, answer_key, reasons):
    """Returns (applicable, passed)."""
    truth = answer_key.get("accuracy_set", {}).get(doc_key)
    if truth is None:
        return False, True  # not a labeled doc
    values = S.value_layer(env, active)
    passed = True
    props = active.get("properties", {})
    for field, exp in truth.items():
        prop = props.get(field, {})
        if prop.get("type") == "array":
            passed &= _compare_coverages(values.get(field, []), exp, field, prop, reasons)
        else:
            kind = S.classify(prop)
            got = values.get(field)
            if not _compare(kind, got, exp):
                passed = False
                reasons.append(f"GATE6 {field}: got {got!r}, expected {exp!r}")
    return True, passed


def _compare_coverages(got_list, exp_list, field, prop, reasons):
    passed = True
    sub_props = prop.get("items", {}).get("properties", {})
    by_type = {}
    for cov in got_list:
        by_type[cov.get("coverage_type")] = cov
    seen = set()
    for exp in exp_list:
        ctype = exp.get("coverage_type")
        seen.add(ctype)
        got = by_type.get(ctype)
        if got is None:
            passed = False
            reasons.append(f"GATE6 {field}[{ctype}]: coverage missing")
            continue
        for sub, expval in exp.items():
            kind = S.classify(sub_props.get(sub, {}))
            if not _compare(kind, got.get(sub), expval):
                passed = False
                reasons.append(
                    f"GATE6 {field}[{ctype}].{sub}: got {got.get(sub)!r}, expected {expval!r}"
                )
    extra = set(by_type) - seen
    if extra:
        passed = False
        reasons.append(f"GATE6 {field}: unexpected coverages {sorted(extra)}")
    return passed


def gate_reconciliation(record, active, answer_key, reasons):
    """(applicable, passed). Update path only: a 'prior' value-layer + 'diff' on the record."""
    prior = record.get("prior")
    diff = record.get("diff")
    if prior is None and diff is None:
        return False, True
    env = record["extraction"]
    current = S.value_layer(env, active)
    computed = _field_diff(prior or {}, current)
    # 1) the recorded diff must equal what we recompute from prior vs current
    if _normalize_diff(diff or []) != _normalize_diff(computed):
        reasons.append(
            f"GATE5: recorded diff {_normalize_diff(diff or [])} != recomputed {_normalize_diff(computed)}"
        )
        return True, False
    # 2) against the answer key's expected diff, if labeled
    doc_key = _doc_key(record)
    exp = answer_key.get("update_expectations", {}).get(doc_key, {}).get("expected_diff")
    if exp is not None and _normalize_diff(exp) != _normalize_diff(computed):
        reasons.append(
            f"GATE5: diff {_normalize_diff(computed)} != expected {_normalize_diff(exp)}"
        )
        return True, False
    return True, True


def _field_diff(prior: dict, current: dict) -> List[dict]:
    """Field-level diff between two value layers. Flattens coverages by type."""
    out = []
    flat_prior = _flatten(prior)
    flat_cur = _flatten(current)
    for key in sorted(set(flat_prior) | set(flat_cur)):
        a, b = flat_prior.get(key), flat_cur.get(key)
        if a != b:
            out.append({"field": key, "from": a, "to": b})
    return out


def _flatten(values: dict) -> dict:
    flat = {}
    for k, v in values.items():
        if isinstance(v, list):
            for cov in v:
                ctype = cov.get("coverage_type")
                for sk, sv in cov.items():
                    if sk == "coverage_type":
                        continue
                    flat[f"{k}[{ctype}].{sk}"] = sv
        else:
            flat[k] = v
    return flat


def _normalize_diff(diff: List[dict]):
    return sorted((d["field"], d.get("from"), d.get("to")) for d in diff)


# --------------------------------------------------------------------------
# per-record + run
# --------------------------------------------------------------------------
def grade_record(record_path: str, answer_key: dict, active: dict) -> dict:
    record = _load_json(record_path)
    status = "review" if os.sep + "review-queue" + os.sep in os.path.abspath(record_path) else "indexed"
    env = record["extraction"]
    pdf_path = os.path.join(ROOT, record["source_pdf"])
    reasons: List[str] = []
    gates: Dict[str, str] = {}

    g1, g4 = gate_grounding_and_fabrication(env, active, pdf_path, reasons)
    g2 = gate_schema(env, active, reasons)
    g3 = gate_confidence(env, active, status, reasons)
    applic5, g5 = gate_reconciliation(record, active, answer_key, reasons)
    applic6, g6 = gate_accuracy(env, active, _doc_key(record), answer_key, reasons)

    gates["1_grounding"] = "pass" if g1 else "fail"
    gates["2_schema"] = "pass" if g2 else "fail"
    gates["3_confidence"] = "pass" if g3 else "fail"
    gates["4_no_fabrication"] = "pass" if g4 else "fail"
    gates["5_reconciliation"] = ("pass" if g5 else "fail") if applic5 else "n/a"
    gates["6_accuracy"] = ("pass" if g6 else "fail") if applic6 else "n/a"

    passed = g1 and g2 and g3 and g4 and (g5 or not applic5) and (g6 or not applic6)
    return {
        "doc_id": record["doc_id"],
        "status": status,
        "gates": gates,
        "pass": passed,
        "reasons": reasons,
    }


def run(verbose: bool = True) -> dict:
    answer_key = _answer_key()
    active = _active_schema()
    records = sorted(
        glob.glob(os.path.join(ROOT, "index", "*.json"))
        + glob.glob(os.path.join(ROOT, "review-queue", "*.json"))
    )
    reports = [grade_record(p, answer_key, active) for p in records]

    # Completeness: every labeled accuracy-set doc must have a passing record.
    indexed_keys = {
        os.path.basename(_load_json(p).get("source_pdf", ""))
        for p in glob.glob(os.path.join(ROOT, "index", "*.json"))
    }
    missing = [k for k in answer_key.get("accuracy_set", {}) if k not in indexed_keys]

    run_pass = all(r["pass"] for r in reports) and not missing and bool(reports)

    if verbose:
        _print_report(reports, missing, run_pass)
    return {"reports": reports, "missing_labeled": missing, "pass": run_pass}


def _print_report(reports, missing, run_pass):
    print("=" * 72)
    print("VERIFIER REPORT  (verifier-rubric.md)")
    print("=" * 72)
    for r in reports:
        mark = "PASS" if r["pass"] else "FAIL"
        gates = "  ".join(f"{k.split('_')[0]}:{v}" for k, v in r["gates"].items())
        print(f"[{mark}] {r['doc_id']:<28} ({r['status']})  {gates}")
        for reason in r["reasons"]:
            print(f"        - {reason}")
    if missing:
        print(f"\nMISSING labeled records (not in index/): {missing}")
    print("-" * 72)
    print(f"RUN: {'PASS — verifier exits 0' if run_pass else 'FAIL — verifier exits 1'}")
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser(description="Independent verifier (verifier-rubric.md)")
    ap.add_argument("--record", help="grade a single record file")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args()

    if args.record:
        result = grade_record(args.record, _answer_key(), _active_schema())
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["pass"] else 1)

    result = run(verbose=not args.json)
    if args.json:
        print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
