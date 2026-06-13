#!/usr/bin/env python3
"""schema_agent.py — the config-authoring agent.

Extends the config-swap story: instead of a human hand-writing a schema, this
agent designs config/<DocType>.schema.json for what the insurer needs to
collect. It proposes a complete field set, scans sample PDFs to flag salient
data the schema doesn't yet capture, ASKS the insurer (over a messaging channel,
console by default) about the gaps, applies the confirmed fields, validates the
schema against the pipeline's supported shape, activates it, and re-runs the
existing pipeline on the samples to prove it works.

It is BUILDER-side: it authors config and re-runs the pipeline. It never queries
the index, adds a chat-with-your-index box, or a dashboard.

  python schema_agent.py onboard "<doc-type description>" --samples <dir> [--channel console|discord] [--keep]
  python schema_agent.py review  --samples <dir> [--channel console|discord]
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import extract            # reused model invocation (loads .env on import)
import pdftext            # reused PDF -> text
import schema_util as S   # reused schema walk + the authored-schema guards
import verifier as V      # reused gate grading
import workflow           # reused per-document indexing
from channels import get_channel

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config")
MAX_RETRIES = int(os.environ.get("SCHEMA_AGENT_MAX_RETRIES", "3"))
CHANNEL_TIMEOUT = float(os.environ.get("CHANNEL_TIMEOUT", "0")) or None

SYSTEM_AUTHOR_DRAFT = (
    "You are a JSON-Schema authoring function for an insurance document indexer. "
    "You design draft-07 schemas in a STRICTLY SUPPORTED shape and ask the insurer about "
    "uncertain fields. Do not use tools, do not explain. Respond with ONLY a single JSON object."
)
SYSTEM_AUTHOR_GAPS = (
    "You are a schema gap-analysis function for an insurance document indexer. Given an active "
    "schema and the text of sample documents, you find recurring data the schema fails to capture. "
    "Do not use tools, do not explain. Respond with ONLY a single JSON object."
)

SUPPORTED_SHAPE_RULES = (
    "SUPPORTED SCHEMA SHAPE (draft-07) — you MUST stay strictly within it:\n"
    "- Top-level: object with $schema='http://json-schema.org/draft-07/schema#', a unique title, "
    "type:'object', required:[...], properties:{...}, and an optional x_natural_key.\n"
    "- Each property is EITHER a scalar leaf — {\"type\":\"string\"|\"number\"|\"integer\"} optionally "
    "with \"format\":\"date\"; or {\"enum\":[...]}; or {\"const\":...} — OR a single array-of-objects: "
    "{\"type\":\"array\",\"items\":{\"type\":\"object\",\"properties\":{<scalar leaves>}}} for repeating "
    "sub-records (like a COI's coverages).\n"
    "- x_natural_key names ONE scalar property used to reconcile document updates (e.g. a policy or "
    "account number).\n"
    "- Dates: type:string + format:date (values normalize to YYYY-MM-DD). Money/limits: type:number "
    "(plain integers). A 'document_type' const field is conventional.\n"
    "- FORBIDDEN: $ref, oneOf/anyOf/allOf, if/then/else/not, nested objects, arrays of scalars, or any "
    "nesting beyond one array-of-objects level."
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _list_pdfs(samples: Optional[str]) -> List[str]:
    if not samples:
        return []
    if os.path.isfile(samples) and samples.endswith(".pdf"):
        return [samples]
    return sorted(glob.glob(os.path.join(samples, "*.pdf")))


def _sample_texts(pdfs: List[str], per_doc: int = 6000, max_docs: int = 3) -> List[Tuple[str, str]]:
    out = []
    for pdf in pdfs[:max_docs]:
        try:
            text = pdftext.full_text(pdf)
        except Exception as exc:  # pragma: no cover
            text = f"(could not read: {exc})"
        out.append((os.path.basename(pdf), text[:per_doc]))
    return out


def _samples_block(sample_texts: List[Tuple[str, str]]) -> str:
    if not sample_texts:
        return "(no sample documents provided)"
    return "\n\n".join(f"=== SAMPLE: {name} ===\n{text}" for name, text in sample_texts)


def _examples() -> str:
    coi = S.load_schema(os.path.join(CONFIG, "coi.schema.json"))
    fnol = S.load_schema(os.path.join(CONFIG, "fnol.schema.json"))
    return (
        "Example with an array-of-objects (Certificate of Insurance):\n"
        + json.dumps(coi, indent=2)
        + "\n\nExample with only scalar leaves (First Notice of Loss):\n"
        + json.dumps(fnol, indent=2)
    )


def _leaf_supported(leaf: dict) -> bool:
    if not isinstance(leaf, dict):
        return False
    if leaf.get("type") in ("object", "array") or "properties" in leaf or "items" in leaf:
        return False
    return S._leaf_violations("x", leaf) == []


def _affirmative(reply: str) -> bool:
    r = (reply or "").strip().lower()
    if not r:
        return False
    first = r.split()[0].strip(".,!?;:")
    if first in ("yes", "y", "yeah", "yep", "sure", "ok", "okay", "add", "include", "capture", "do", "please", "correct"):
        return True
    if first in ("no", "n", "nope", "skip", "don't", "dont", "exclude", "leave", "omit", "ignore"):
        return False
    return any(w in r for w in ("yes", "include", "capture", "we need", "required", "add it", "definitely"))


def _validate(schema: dict, exclude_path: Optional[str]) -> List[str]:
    """All authored-schema gates: shape lint + title uniqueness + behavioral
    round-trip + draft-07 meta-validation."""
    violations = list(S.lint_authored_schema(schema))
    clash = S.title_collision(schema, CONFIG, exclude_path=exclude_path)
    if clash:
        violations.append(
            f"title '{schema.get('title')}' collides with {os.path.basename(clash)} — choose a unique title"
        )
    ok, why = S.roundtrip_ok(schema)
    if not ok:
        violations.append(f"pipeline round-trip failed: {why}")
    try:
        import jsonschema
        jsonschema.Draft7Validator.check_schema(schema)
    except Exception as exc:
        violations.append(f"not a valid draft-07 schema: {exc}")
    return violations


# --------------------------------------------------------------------------
# model phases
# --------------------------------------------------------------------------
def _phase1_draft(description: str, sample_texts, feedback: Optional[str] = None) -> dict:
    user = "\n".join([
        "Design a draft-07 JSON Schema for this insurance document type, and ask the insurer about any uncertain fields.",
        f"DESCRIPTION: {description}",
        "",
        SUPPORTED_SHAPE_RULES,
        "",
        "WORKED EXAMPLES (match this style):",
        _examples(),
        "",
        "SAMPLE DOCUMENT TEXT (if any):",
        _samples_block(sample_texts),
        "",
        'Return ONE JSON object: {"schema": <draft schema>, "questions": [ {"field_name": "...", '
        '"question": "<yes/no question to the insurer>", "proposed": <a scalar leaf schema>, '
        '"reason": "...", "source": "domain"|"data-driven"} ]}.',
        "Put fields you are confident belong in schema.properties (set required + x_natural_key appropriately). "
        "Put fields you are UNSURE about (optional/uncommon, or that you SEE in the sample text but the "
        "description did not mention) ONLY in questions — one per uncertain field, each with a proposed scalar "
        "leaf. Use source='data-driven' for fields inferred from the sample text, 'domain' otherwise.",
    ])
    if feedback:
        user += "\n\nThe previous attempt was INVALID. Fix exactly these and resend the full object:\n" + feedback
    return extract.call_model(user, SYSTEM_AUTHOR_DRAFT)


def _draft_with_retry(description: str, sample_texts) -> dict:
    feedback = None
    for attempt in range(1, MAX_RETRIES + 1):
        obj = _phase1_draft(description, sample_texts, feedback)
        schema = obj.get("schema") if isinstance(obj, dict) else None
        if not isinstance(schema, dict):
            feedback = "Response must be an object with a 'schema' object and a 'questions' array."
            continue
        violations = _validate(schema, exclude_path=None)
        if not violations:
            obj.setdefault("questions", [])
            return obj
        print(f"  [draft retry {attempt}] schema invalid:")
        for v in violations:
            print(f"        - {v}")
        feedback = "\n".join(f"- {v}" for v in violations)
    raise SystemExit("schema_agent: could not produce a valid draft schema after retries")


def _data_driven_gaps(active: dict, sample_texts) -> List[dict]:
    user = "\n".join([
        "The insurer uses this ACTIVE schema to extract fields:",
        json.dumps(active, indent=2),
        "",
        "Text of sample documents they receive:",
        _samples_block(sample_texts),
        "",
        SUPPORTED_SHAPE_RULES,
        "",
        'Identify salient, RECURRING data present in the documents but NOT captured by the active schema. '
        'Ignore distractor data (revision/printed dates, prior-carrier or quote/cert/claim numbers, '
        'additional-insured names, aggregate sub-limits). Return ONE JSON object '
        '{"questions": [ {"field_name","question","proposed": <scalar leaf>, "reason", "source": "data-driven"} ]}. '
        'Only include fields you actually see in the sample text. If nothing is missing, return {"questions": []}.',
    ])
    obj = extract.call_model(user, SYSTEM_AUTHOR_GAPS)
    return obj.get("questions", []) if isinstance(obj, dict) else []


# --------------------------------------------------------------------------
# conversation + apply
# --------------------------------------------------------------------------
def _ask_gaps(channel, questions: List[dict]) -> Dict[str, bool]:
    decisions: Dict[str, bool] = {}
    for q in questions:
        fn = q.get("field_name", "?")
        prompt = q.get("question") or f"Should I also collect '{fn}'? {q.get('reason', '')}"
        tag = "[noticed in your sample documents] " if q.get("source") == "data-driven" else ""
        reply = channel.ask(tag + prompt, timeout=CHANNEL_TIMEOUT)
        confirmed = _affirmative(reply)
        decisions[fn] = confirmed
        print(f"  [{'add ' if confirmed else 'skip'}] {fn}  (reply: {reply!r})")
    return decisions


def _apply(base_schema: dict, questions: List[dict], decisions: Dict[str, bool]) -> dict:
    """Deterministically fold confirmed fields into the schema (added as OPTIONAL
    so existing records of an edited type still validate); drop rejected ones."""
    final = copy.deepcopy(base_schema)
    props = final.setdefault("properties", {})
    required = final.setdefault("required", [])
    by_name = {q.get("field_name"): q for q in questions}
    for fn, confirmed in decisions.items():
        if confirmed:
            proposed = (by_name.get(fn) or {}).get("proposed") or {"type": "string"}
            if _leaf_supported(proposed):
                props.setdefault(fn, proposed)
            else:
                print(f"  [skip] confirmed field '{fn}': proposed leaf unsupported ({proposed})")
        else:
            props.pop(fn, None)
            if fn in required:
                required.remove(fn)
    return final


# --------------------------------------------------------------------------
# config IO + indexing
# --------------------------------------------------------------------------
def _title_to_path(title: str) -> str:
    safe = "".join(c for c in (title or "DocType") if c.isalnum() or c in "_-") or "DocType"
    return os.path.join(CONFIG, f"{safe}.schema.json")


def _write_config(schema: dict, path: str) -> str:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(schema, fh, indent=2)
    os.replace(tmp, path)  # atomic
    return path


def _activate(path: str) -> None:
    import shutil
    shutil.copyfile(path, os.path.join(CONFIG, "active.schema.json"))


def _restore_active_coi() -> None:
    import shutil
    shutil.copyfile(os.path.join(CONFIG, "coi.schema.json"), os.path.join(CONFIG, "active.schema.json"))


def _active_source_path() -> Tuple[Optional[str], dict]:
    active = S.load_schema(os.path.join(CONFIG, "active.schema.json"))
    for p in glob.glob(os.path.join(CONFIG, "*.schema.json")):
        if os.path.basename(p) == "active.schema.json":
            continue
        try:
            if S.load_schema(p).get("title") == active.get("title"):
                return p, active
        except Exception:
            continue
    return None, active


def _reindex(samples: List[str]) -> List[Tuple[str, dict]]:
    return [(pdf, workflow.process_doc(pdf, force=True, verbose=False)) for pdf in samples]


def _cleanup_records(samples: List[str]) -> None:
    for pdf in samples:
        doc_id = os.path.splitext(os.path.basename(pdf))[0]
        for d in ("index", "review-queue"):
            p = os.path.join(ROOT, d, doc_id + ".json")
            if os.path.exists(p):
                os.remove(p)


def _gate_report(reports: List[Tuple[str, dict]]) -> Tuple[bool, str]:
    core = ["1_grounding", "2_schema", "3_confidence", "4_no_fabrication"]
    lines, all_ok = [], True
    for pdf, rep in reports:
        gates = rep.get("gates", {})
        ok = all(gates.get(g) == "pass" for g in core)
        all_ok &= ok
        chips = "  ".join(f"{k.split('_')[0]}:{v}" for k, v in gates.items())
        lines.append(f"  [{'OK  ' if ok else 'FAIL'}] {os.path.basename(pdf):<28} {chips}")
    return all_ok, "\n".join(lines)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def onboard(description: str, samples_dir: Optional[str], channel_name: str, keep: bool) -> int:
    channel = get_channel(channel_name)
    samples = _list_pdfs(samples_dir)
    channel.send(
        f"I'm setting up extraction for: {description}."
        + (f" Analyzing {len(samples)} sample document(s) too." if samples else "")
    )
    sample_texts = _sample_texts(samples)

    print("• drafting schema (invoking model) …")
    draft = _draft_with_retry(description, sample_texts)
    questions = draft.get("questions", [])
    if questions:
        channel.send(f"I drafted a schema and have {len(questions)} field(s) I'd like to confirm with you.")
    decisions = _ask_gaps(channel, questions) if questions else {}

    final = _apply(draft["schema"], questions, decisions)
    target = _title_to_path(final.get("title", "DocType"))
    violations = _validate(final, exclude_path=target)
    if violations:
        channel.send("I couldn't produce a safe schema; nothing was changed.")
        print("FINAL validation failed:\n" + "\n".join(f"  - {v}" for v in violations))
        return 1

    path = _write_config(final, target)
    print(f"• wrote {os.path.relpath(path, ROOT)} (title={final['title']})")
    channel.send(f"Created the {final['title']} schema capturing: {', '.join(final['properties'])}.")

    if not samples:
        channel.send("No sample documents were provided, so I authored the schema but did not verify it end-to-end.")
        print("authored (unverified — no samples). config:", os.path.relpath(path, ROOT))
        return 0

    _activate(path)
    print("• re-indexing samples against the new schema …")
    reports = _reindex(samples)
    ok, report_txt = _gate_report(reports)
    print(report_txt)
    channel.send(
        ("✓ Verified — " if ok else "⚠ Heads up — ")
        + f"indexed {len(samples)} sample(s); the independent verifier's core gates "
        + ("all passed (grounding, schema, confidence, no-fabrication)." if ok else "found issues; see the log.")
    )

    if keep:
        channel.send("Left the new schema active and the sample records indexed (you can open the viewer).")
        print("kept active + sample records (demo mode). config:", os.path.relpath(path, ROOT))
    else:
        _cleanup_records(samples)
        _restore_active_coi()
        print("restored active=COI and removed sample records; new schema persists at", os.path.relpath(path, ROOT))
    return 0 if ok else 1


def review(samples_dir: Optional[str], channel_name: str) -> int:
    samples = _list_pdfs(samples_dir)
    if not samples:
        print("schema_agent review: --samples must contain at least one PDF")
        return 2
    channel = get_channel(channel_name)
    src_path, active = _active_source_path()
    title = active.get("title", "active schema")
    channel.send(f"Reviewing the active '{title}' schema against {len(samples)} sample doc(s) for data you might be missing.")
    sample_texts = _sample_texts(samples)

    print("• scanning samples for uncaptured fields (invoking model) …")
    gaps = _data_driven_gaps(active, sample_texts)
    if not gaps:
        channel.send("No additional recurring fields detected — the schema looks complete.")
        print("no gaps found.")
        return 0

    decisions = _ask_gaps(channel, gaps)
    updated = _apply(active, gaps, decisions)
    added = [q.get("field_name") for q in gaps if decisions.get(q.get("field_name")) and q.get("field_name") in updated["properties"]]
    if not added:
        channel.send("Nothing confirmed — leaving the schema unchanged.")
        return 0

    violations = _validate(updated, exclude_path=src_path)
    if violations:
        channel.send("Couldn't safely apply those changes; the schema is unchanged.")
        print("validation failed:\n" + "\n".join(f"  - {v}" for v in violations))
        return 1

    if src_path:
        _write_config(updated, src_path)
        _activate(src_path)
    channel.send(f"Added optional field(s): {', '.join(added)}. Future {title} extractions will capture them.")
    print(f"• added {added} to {os.path.relpath(src_path, ROOT) if src_path else 'active schema'}")

    res = V.run(verbose=False)
    print(f"• corpus verifier after edit: {'PASS (exits 0)' if res['pass'] else 'FAIL'}")
    return 0 if res["pass"] else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Config-authoring agent for the insurance indexer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    on = sub.add_parser("onboard", help="author a NEW doc-type schema from a description (+ optional samples)")
    on.add_argument("description", help="natural-language description of what to collect")
    on.add_argument("--samples", help="dir (or single .pdf) of sample documents to ground + verify against")
    on.add_argument("--channel", default="console", help="console | discord | whatsapp")
    on.add_argument("--keep", action="store_true", help="leave the new schema active + sample records (demo mode)")

    rv = sub.add_parser("review", help="data-driven gap pass on the ACTIVE schema")
    rv.add_argument("--samples", required=True, help="dir (or single .pdf) of sample documents to analyze")
    rv.add_argument("--channel", default="console", help="console | discord | whatsapp")

    args = ap.parse_args()
    if args.cmd == "onboard":
        sys.exit(onboard(args.description, args.samples, args.channel, args.keep))
    else:
        sys.exit(review(args.samples, args.channel))


if __name__ == "__main__":
    main()
