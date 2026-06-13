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
import re
import sys
from typing import Dict, List, Optional, Tuple

import extract            # reused model invocation (loads .env on import)
import pdftext            # reused PDF -> text
import profiles           # per-insurer process profiles
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
SYSTEM_AUTHOR_INTERPRET = (
    "You interpret an insurer's free-text replies to yes/no field-capture questions for a document "
    "schema. A reply may confirm, decline, rename the field, and/or change its type. Do not use "
    "tools, do not explain. Respond with ONLY a single JSON object."
)
SYSTEM_AUTHOR_PROFILE = (
    "You author a per-insurer ROUTING PROFILE for an insurance document indexer: the department "
    "codes, line-of-business -> department taxonomy, admitted/surplus market type, and a (mock) "
    "agency-code map an insurer uses to triage inbound documents. Do not use tools, do not explain. "
    "Respond with ONLY a single JSON object."
)
PROFILE_LOBS = ["general_liability", "auto_liability", "umbrella", "professional_liability",
                "property", "workers_comp"]

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
    "nesting beyond one array-of-objects level.\n"
    "- If the document has SEVERAL repeating sub-records (e.g. property locations AND a claims list), "
    "model only the SINGLE most-repeating one as the array-of-objects and flatten the rest to scalars — "
    "the schema allows exactly ONE array."
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
def _sanitize_field(name: str) -> str:
    """A label like 'Effective Date' -> snake_case key 'effective_date'."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "field"


_RENAME_RE = re.compile(
    r"(?:call it|label(?:ed| it)?|name(?:d| it)?|rename(?:d)?(?: to| it)?|as)\s+"
    r"['\"]?([a-zA-Z][a-zA-Z0-9 _-]{0,40})['\"]?",
    re.IGNORECASE,
)


def _extract_rename(reply: str) -> Optional[str]:
    """Best-effort fallback rename extraction (used only if model interpretation
    is unavailable). e.g. 'yes, call it effective date' -> 'effective date'."""
    m = _RENAME_RE.search(reply or "")
    if not m:
        return None
    return m.group(1).strip(" .,:;!?")


def _ask_gaps(channel, questions: List[dict]) -> List[dict]:
    """Ask each gap question and collect the raw free-text reply."""
    replies = []
    for q in questions:
        fn = q.get("field_name", "?")
        prompt = q.get("question") or f"Should I also collect '{fn}'? {q.get('reason', '')}"
        tag = "[noticed in your sample documents] " if q.get("source") == "data-driven" else ""
        reply = channel.ask(tag + prompt, timeout=CHANNEL_TIMEOUT)
        print(f"  [reply] {fn}: {reply!r}")
        replies.append({**q, "reply": reply})
    return replies


def _resolve_decisions(replies: List[dict]) -> List[dict]:
    """Turn free-text replies into structured decisions, honoring rename/retype.
    Returns [{original, confirmed, name, leaf}]. Uses the model to interpret each
    reply (so 'yes, call it effective date' renames the field); falls back to a
    yes/no + regex-rename heuristic if the model is unavailable."""
    if not replies:
        return []
    items = [
        {
            "field_name": r.get("field_name"),
            "question": r.get("question"),
            "proposed": r.get("proposed") or {"type": "string"},
            "reply": r.get("reply", ""),
        }
        for r in replies
    ]
    user = "\n".join([
        "For each item, the insurer was asked whether to capture a field and replied freely. "
        "Decide what to do with each:",
        json.dumps(items, indent=2),
        "",
        SUPPORTED_SHAPE_RULES,
        "",
        'Return ONE JSON object {"decisions": [ {"field_name": <original>, "confirmed": <bool>, '
        '"name": <snake_case field name to use>, "leaf": <final scalar leaf schema>, '
        '"extra": [ {"name": <snake_case>, "leaf": <scalar leaf schema>} ] } ]} — one per item, in '
        "the same order.",
        "Rules: confirmed=true only if the reply affirms capturing the asked field (yes/sure/please/etc.); "
        "false for no/skip/unclear/empty. If the insurer asked to RENAME or RELABEL it (e.g. "
        "'yes, call it effective date'), set name to a snake_case version of the requested label "
        "('effective_date'); otherwise name = field_name. If they asked for a different TYPE/FORMAT "
        "(e.g. 'make it a date', 'as a number'), adjust leaf (scalar only); otherwise leaf = proposed.",
        "ALSO: if the reply asks to ALSO capture a SEPARATE NEW field beyond the one asked about "
        "(e.g. 'yes, and also add a workflow tag'), put each such new field in `extra` with a "
        "snake_case name and a scalar leaf schema. `extra` is [] when none are requested. Do NOT put "
        "the asked field itself in extra.",
    ])
    decs = None
    try:
        obj = extract.call_model(user, SYSTEM_AUTHOR_INTERPRET)
        if isinstance(obj, dict) and isinstance(obj.get("decisions"), list):
            decs = obj["decisions"]
    except Exception as exc:
        print(f"  [interpret] model interpretation unavailable ({exc}); using yes/no fallback")

    def _clean_extras(raw) -> List[dict]:
        extras = []
        for e in raw or []:
            if not isinstance(e, dict):
                continue
            leaf = e.get("leaf") if _leaf_supported(e.get("leaf")) else {"type": "string"}
            name = _sanitize_field(e.get("name") or "")
            if name:
                extras.append({"name": name, "leaf": leaf})
        return extras

    out: List[dict] = []
    by_orig = {r.get("field_name"): r for r in replies}
    if decs:
        for d in decs:
            orig = d.get("field_name")
            r = by_orig.get(orig, {})
            leaf = d.get("leaf")
            if not _leaf_supported(leaf):
                leaf = r.get("proposed") or {"type": "string"}
            out.append({
                "original": orig,
                "confirmed": bool(d.get("confirmed")),
                "name": _sanitize_field(d.get("name") or orig or "field"),
                "leaf": leaf,
                "extra": _clean_extras(d.get("extra")),
            })
    else:  # deterministic fallback (no new-field extraction without the model)
        for r in replies:
            reply = r.get("reply", "")
            renamed = _extract_rename(reply) if _affirmative(reply) else None
            leaf = r.get("proposed") or {"type": "string"}
            out.append({
                "original": r.get("field_name"),
                "confirmed": _affirmative(reply),
                "name": _sanitize_field(renamed or r.get("field_name") or "field"),
                "leaf": leaf if _leaf_supported(leaf) else {"type": "string"},
                "extra": [],
            })

    for d in out:
        rename = f" → {d['name']}" if d["name"] != d["original"] else ""
        extras = ("  + " + ", ".join(e["name"] for e in d["extra"])) if d["extra"] else ""
        print(f"  [{'add ' if d['confirmed'] else 'skip'}] {d['original']}{rename}{extras}")
    return out


def _apply(base_schema: dict, decisions: List[dict]) -> dict:
    """Fold resolved decisions into the schema. Confirmed fields are added under
    their (possibly renamed) name as OPTIONAL — so existing records of an edited
    type still validate; declined fields are dropped if speculatively present."""
    final = copy.deepcopy(base_schema)
    props = final.setdefault("properties", {})
    required = final.setdefault("required", [])
    for d in decisions:
        orig, name, leaf = d["original"], d["name"], d["leaf"]
        if d["confirmed"]:
            if _leaf_supported(leaf):
                props.setdefault(name, leaf)
                if name != orig:
                    props.pop(orig, None)  # avoid leaving a speculative original
            else:
                print(f"  [skip] confirmed field '{name}': leaf unsupported ({leaf})")
        else:
            props.pop(orig, None)
            if orig in required:
                required.remove(orig)
        # new fields the insurer requested in this reply (added as OPTIONAL)
        for e in d.get("extra", []):
            if _leaf_supported(e["leaf"]) and e["name"] not in props:
                props[e["name"]] = e["leaf"]
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
    replies = _ask_gaps(channel, questions) if questions else []
    decisions = _resolve_decisions(replies)

    final = _apply(draft["schema"], decisions)
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

    replies = _ask_gaps(channel, gaps)
    decisions = _resolve_decisions(replies)
    updated = _apply(active, decisions)
    added = [d["name"] for d in decisions if d["confirmed"] and d["name"] in updated["properties"]]
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


def _draft_profile(insurer_id: str, description: str, sample_texts, feedback=None) -> dict:
    user = "\n".join([
        f"Author a routing profile for insurer_id '{insurer_id}'.",
        f"DESCRIPTION: {description}",
        "",
        "Return ONE JSON object with EXACTLY these keys:",
        '{"insurer_id": "<id>", "display_name": "...", "market_type": "admitted"|"surplus", '
        '"departments": ["CODE", ...], "lob_taxonomy": {<lob>: "<dept code from departments>"}, '
        '"default_department": "<one of departments>", "agency_codes": {"<producer name>": "<code>"}}',
        f"lob_taxonomy keys MUST be drawn from: {PROFILE_LOBS} (map every one to a department code). "
        "departments are the insurer's internal desk codes (e.g. CL, PROP, SPEC, CAS, WC). "
        "agency_codes is a SYNTHETIC/MOCK lookup from producer/agency names seen in the samples to "
        "made-up internal codes.",
        "",
        "SAMPLE DOCUMENT TEXT (for producer names + line-of-business cues), if any:",
        _samples_block(sample_texts),
    ])
    if feedback:
        user += "\n\nThe previous attempt was INVALID. Fix exactly these and resend the full object:\n" + feedback
    return extract.call_model(user, SYSTEM_AUTHOR_PROFILE)


def profile_cmd(insurer_id: str, description: str, samples_dir: Optional[str],
                channel_name: str, activate: bool) -> int:
    channel = get_channel(channel_name)
    samples = _list_pdfs(samples_dir)
    sample_texts = _sample_texts(samples)
    channel.send(f"Setting up a routing profile for {insurer_id}. I'll propose how your inbound "
                 "documents should be triaged and confirm the details with you.")

    print("• drafting profile (invoking model) …")
    feedback, prof = None, None
    for attempt in range(1, MAX_RETRIES + 1):
        draft = _draft_profile(insurer_id, description, sample_texts, feedback)
        draft["insurer_id"] = insurer_id  # authoritative
        violations = profiles.lint_profile(draft)
        if not violations:
            prof = draft
            break
        print(f"  [profile retry {attempt}] invalid: {violations}")
        feedback = "\n".join(f"- {v}" for v in violations)
    if not prof:
        channel.send("I couldn't produce a valid profile; nothing was changed.")
        return 1

    # confirm the key axes over the channel
    summary = (f"Proposed profile for {prof['display_name']} ({prof['market_type']} market): "
               f"departments {prof['departments']}; routing e.g. "
               + ", ".join(f"{k}→{v}" for k, v in list(prof['lob_taxonomy'].items())[:4])
               + f"; default {prof.get('default_department')}.")
    reply = channel.ask(summary + " Does this match your setup? (yes, or describe corrections)",
                        timeout=CHANNEL_TIMEOUT)
    if reply and not _affirmative(reply):
        print("  [profile] applying correction …")
        prof2 = _draft_profile(insurer_id, description + "\nINSURER CORRECTION: " + reply, sample_texts)
        prof2["insurer_id"] = insurer_id
        if not profiles.lint_profile(prof2):
            prof = prof2

    path = profiles.profile_path(insurer_id)
    os.makedirs(profiles.PROFILES_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(prof, fh, indent=2)
    os.replace(tmp, path)
    print(f"• wrote {os.path.relpath(path, ROOT)}")
    channel.send(f"Saved the {prof['display_name']} profile (departments {prof['departments']}).")

    if activate:
        profiles.activate(insurer_id)
        import router
        router.annotate(insurer_id, verbose=False)
        channel.send(f"Activated {prof['display_name']} — inbound documents now route to its desks.")
        print(f"• activated + annotated records with {insurer_id}")
    return 0


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

    pf = sub.add_parser("profile", help="author a per-insurer routing profile (departments, LOB→dept, agency codes)")
    pf.add_argument("insurer_id", help="short id, e.g. acme-mga")
    pf.add_argument("description", help="description of the insurer's process (market, departments, lines)")
    pf.add_argument("--samples", help="dir (or single .pdf) of their documents, to seed producer/agency codes")
    pf.add_argument("--channel", default="console", help="console | discord | whatsapp")
    pf.add_argument("--activate", action="store_true", help="activate the profile + annotate records after authoring")

    args = ap.parse_args()
    if args.cmd == "onboard":
        sys.exit(onboard(args.description, args.samples, args.channel, args.keep))
    elif args.cmd == "review":
        sys.exit(review(args.samples, args.channel))
    else:
        sys.exit(profile_cmd(args.insurer_id, args.description, args.samples, args.channel, args.activate))


if __name__ == "__main__":
    main()
