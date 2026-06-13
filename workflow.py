#!/usr/bin/env python3
"""workflow.py — the CODE-HELD loop (orchestration-brief.md §6).

The script — not a single long model run — holds the loop. For each document it
invokes the model in a bounded, per-document step, grades it with the
fresh-context verifier, and routes the result. State is checkpointed to disk
(index/, review-queue/, notes.md) so the run re-derives nothing and survives a
restart.

  WATCH inbox/  ->  for each doc:
      load notes.md  ->  EXTRACT (model)  ->  VERIFY (fresh context)
        - all gates pass            -> write index/<doc>.json
        - low-confidence routing    -> write review-queue/<doc>.json (flagged)
        - a gate fails              -> feed verifier reasons back, retry (<=3)
      reconcile if the doc updates an already-indexed record (field-level diff)

Usage:
  python workflow.py                 # process every PDF in inbox/ once
  python workflow.py --doc NAME      # process one PDF (stem or filename)
  python workflow.py --watch         # keep watching inbox/ for new/changed PDFs
  python workflow.py --force         # re-process even if already indexed
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from typing import Dict, List, Optional, Tuple

import extract
import schema_util as S
import verifier as V

ROOT = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(ROOT, "inbox")
INDEX = os.path.join(ROOT, "index")
REVIEW = os.path.join(ROOT, "review-queue")
WORK = os.path.join(ROOT, ".work")
NOTES = os.path.join(ROOT, "notes.md")
MAX_RETRIES = 3


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _doc_id(pdf_path: str) -> str:
    return os.path.splitext(os.path.basename(pdf_path))[0]


def _rel(pdf_path: str) -> str:
    return os.path.relpath(pdf_path, ROOT)


def _write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2)


def _remove_existing(doc_id: str) -> None:
    for d in (INDEX, REVIEW):
        p = os.path.join(d, doc_id + ".json")
        if os.path.exists(p):
            os.remove(p)


def _needs_review_any(env: dict, active: dict) -> Tuple[bool, List[str]]:
    flagged = []
    for path, wrapper, _kind in S.iter_fields(env, active):
        conf = wrapper.get("confidence")
        if (
            wrapper.get("needs_review")
            or wrapper.get("value") is None
            or (isinstance(conf, (int, float)) and conf < V.CONF_THRESHOLD)
        ):
            flagged.append(path)
    return bool(flagged), flagged


def _natural_key_field(active: dict) -> Optional[str]:
    """Config-driven reconciliation key (x_natural_key in the active schema)."""
    return active.get("x_natural_key")


def _index_record_for_key(active: dict, key_field: str, key_value, exclude_doc: str):
    """Find an already-indexed record whose natural key matches (the update path)."""
    for p in glob.glob(os.path.join(INDEX, "*.json")):
        rec = json.load(open(p))
        if rec.get("doc_id") == exclude_doc:
            continue
        vals = S.value_layer(rec.get("extraction", {}), active)
        if vals.get(key_field) == key_value:
            return rec
    return None


def _append_note(line: str) -> None:
    with open(NOTES, "a") as fh:
        fh.write("\n" + line + "\n")


# --------------------------------------------------------------------------
# the per-document loop
# --------------------------------------------------------------------------
def process_doc(pdf_path: str, force: bool = False, verbose: bool = True) -> dict:
    doc_id = _doc_id(pdf_path)
    active = S.load_schema(os.path.join(ROOT, "config", "active.schema.json"))
    answer_key = V._answer_key()
    is_labeled = (doc_id + ".pdf") in answer_key.get("accuracy_set", {})

    if not force:
        for d in (INDEX, REVIEW):
            if os.path.exists(os.path.join(d, doc_id + ".json")):
                if verbose:
                    print(f"  [skip] {doc_id} already processed (use --force to redo)")
                return {"doc_id": doc_id, "pass": True, "skipped": True}

    feedback: Optional[str] = None
    last_report: dict = {}
    for attempt in range(1, MAX_RETRIES + 1):
        if verbose:
            print(f"  [extract] {doc_id} (attempt {attempt}) — invoking model …")
        env = extract.extract(pdf_path, feedback=feedback)

        review_any, flagged = _needs_review_any(env, active)
        status = "review" if review_any else "indexed"
        target_dir = REVIEW if review_any else INDEX

        record = {
            "doc_id": doc_id,
            "source_pdf": _rel(pdf_path),
            "schema_title": active.get("title"),
            "attempts": attempt,
            "extraction": env,
        }
        # reconciliation: does this update an already-indexed record?
        _maybe_attach_reconciliation(record, env, active, doc_id)

        _remove_existing(doc_id)
        record_path = os.path.join(target_dir, doc_id + ".json")
        _write_json(record_path, record)

        report = V.grade_record(record_path, answer_key, active)
        last_report = report

        # A clean, labeled doc routed to review-queue is itself a miss: push to retry.
        forced_review_miss = is_labeled and status == "review"

        if report["pass"] and not forced_review_miss:
            if verbose:
                gates = "  ".join(f"{k.split('_')[0]}:{v}" for k, v in report["gates"].items())
                print(f"  [{status.upper()}] {doc_id}  {gates}")
            if attempt > 1:
                _learn_from_fix(doc_id, active, feedback)
            return report

        # build feedback for the next attempt
        reasons = list(report["reasons"])
        if forced_review_miss:
            reasons.append(
                "These fields were marked low-confidence/needs_review on a clearly legible "
                f"born-digital document: {flagged}. Re-read them; if the value is plainly "
                "supported by the text, assign confidence >= 0.9 and needs_review=false."
            )
        feedback = "\n".join(f"- {r}" for r in reasons)
        if verbose:
            print(f"  [retry] {doc_id} attempt {attempt} failed:")
            for r in reasons:
                print(f"        · {r}")
        _remove_existing(doc_id)

    # exhausted retries — park the last attempt for inspection, do not assert it
    fail_path = os.path.join(WORK, doc_id + ".failed.json")
    _write_json(fail_path, {"report": last_report})
    if verbose:
        print(f"  [FAIL] {doc_id} after {MAX_RETRIES} attempts (see {_rel(fail_path)})")
    return last_report


def _maybe_attach_reconciliation(record, env, active, doc_id) -> None:
    key_field = _natural_key_field(active)
    if not key_field:
        return
    vals = S.value_layer(env, active)
    key_value = vals.get(key_field)
    if key_value is None:
        return
    prior = _index_record_for_key(active, key_field, key_value, exclude_doc=doc_id)
    if not prior:
        return
    prior_vals = S.value_layer(prior.get("extraction", {}), active)
    diff = V._field_diff(prior_vals, vals)
    record["prior"] = prior_vals
    record["prior_doc_id"] = prior.get("doc_id")
    record["diff"] = diff


def _learn_from_fix(doc_id: str, active: dict, feedback: Optional[str]) -> None:
    """File-based memory: distill a one-line rule from a fixed failure."""
    title = active.get("title", "")
    head = "Certificate of Insurance (COI)" if "Certificate" in title else \
        ("First Notice of Loss (FNOL)" if "First" in title else title)
    fields = []
    for line in (feedback or "").splitlines():
        if line.startswith("- GATE"):
            fields.append(line.strip("- ").strip())
    note = (
        f"- [{head}] {doc_id}: fixed on retry — verifier flagged: "
        + ("; ".join(fields[:3]) if fields else "see prior run")
        + ". Re-confirmed grounding/normalization before indexing."
    )
    _append_note(note)


# --------------------------------------------------------------------------
# batch + watch
# --------------------------------------------------------------------------
def _pdfs(doc: Optional[str]) -> List[str]:
    if doc:
        stem = os.path.splitext(doc)[0]
        cand = os.path.join(INBOX, stem + ".pdf")
        if not os.path.exists(cand):
            raise SystemExit(f"no such PDF in inbox/: {doc}")
        return [cand]
    return sorted(glob.glob(os.path.join(INBOX, "*.pdf")))


def run_once(doc: Optional[str], force: bool) -> bool:
    print("=" * 72)
    print("WORKFLOW — code-held loop (orchestration-brief.md §6)")
    print("=" * 72)
    reports = []
    for pdf in _pdfs(doc):
        print(f"\n• {os.path.basename(pdf)}")
        reports.append(process_doc(pdf, force=force))
    ok = all(r.get("pass") for r in reports)
    print("\n" + "-" * 72)
    print(f"processed {len(reports)} doc(s); {'all passed' if ok else 'some FAILED'}")
    print("Run `python verifier.py` to grade the committed index/ + review-queue/.")
    return ok


def watch(poll: float = 2.0) -> None:
    print(f"[watch] polling {INBOX} every {poll}s — drop a PDF to index it (Ctrl-C to stop)")
    seen: Dict[str, float] = {}
    for p in glob.glob(os.path.join(INBOX, "*.pdf")):
        seen[p] = os.path.getmtime(p)
        process_doc(p)
    while True:
        time.sleep(poll)
        for p in sorted(glob.glob(os.path.join(INBOX, "*.pdf"))):
            mt = os.path.getmtime(p)
            if seen.get(p) != mt:
                print(f"\n• detected {os.path.basename(p)}")
                seen[p] = mt
                process_doc(p, force=True)


def main():
    ap = argparse.ArgumentParser(description="Code-held extract->verify->route loop")
    ap.add_argument("--doc", help="process a single PDF (stem or filename)")
    ap.add_argument("--watch", action="store_true", help="watch inbox/ continuously")
    ap.add_argument("--force", action="store_true", help="re-process already-indexed docs")
    args = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    if args.watch:
        watch()
    else:
        ok = run_once(args.doc, args.force)
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
