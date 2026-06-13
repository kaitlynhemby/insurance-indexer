#!/usr/bin/env python3
"""extract.py — one PDF -> one extraction envelope, keyed to the active schema.

The builder step of the loop. It is schema-AGNOSTIC: it reads
config/active.schema.json, asks the model to fill the matching extraction
envelope (value / confidence / source span / needs_review per field), then
re-normalizes every value in Python so dates/limits are canonical regardless
of what the model returned.

Model invocation (bounded, per-document, fresh context each call):
  * primary : the local `claude` CLI in headless `-p` mode (uses the same login
              as Claude Code — no API key needed)
  * fallback: the Anthropic API via the `anthropic` SDK, if ANTHROPIC_API_KEY is set

The verifier (fresh context) grades the result; on failure the workflow feeds
the verifier's reasons back here as `feedback` and we retry.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

import normalize as N
import pdftext
import schema_util as S

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("INDEXER_MODEL", "claude-opus-4-8")
CLI_TIMEOUT = int(os.environ.get("INDEXER_CLI_TIMEOUT", "300"))

SYSTEM_PROMPT = (
    "You are a non-interactive insurance-document extraction function. "
    "Do NOT use any tools, do NOT read files, do NOT ask questions, do NOT explain. "
    "You are given the full text of one document and a target schema. "
    "Respond with ONLY a single JSON object — the extraction envelope — and nothing else."
)


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------
def _read_notes() -> str:
    path = os.path.join(ROOT, "notes.md")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read()
    return ""


def build_user_prompt(active: dict, doc_text: str, feedback: Optional[str]) -> str:
    schema_json = json.dumps(active, indent=2)
    notes = _read_notes()
    envelope_help = json.dumps(
        {
            "<field>": {
                "value": "<normalized value, or null if absent/illegible>",
                "confidence": 0.0,
                "source": {"page": 1, "text_span": "<verbatim substring copied from the text>"},
                "needs_review": False,
            }
        },
        indent=2,
    )
    parts = [
        "Extract the fields defined by this TARGET SCHEMA from the DOCUMENT TEXT below.",
        "",
        "TARGET SCHEMA (config/active.schema.json):",
        schema_json,
        "",
        "OUTPUT — an extraction ENVELOPE. Mirror the schema's structure, but replace every",
        "leaf value with this wrapper object:",
        envelope_help,
        "Rules for the envelope:",
        "- For an array field (e.g. `coverages`), output a JSON array of objects; wrap each",
        "  leaf inside each element the same way.",
        "- `value`: the normalized value. DATES -> ISO `YYYY-MM-DD` (the document prints",
        "  MM/DD/YYYY). MONEY LIMITS -> plain integer (no $, no commas). Enums/const ->",
        "  exactly one of the allowed schema values. If a field is absent or illegible, set",
        "  value to null.",
        "- `source.text_span`: copy the MINIMAL verbatim substring from the text that proves",
        "  the value (e.g. `POLICY EXP (MM/DD/YYYY): 01/01/2027`). It must appear character-for-",
        "  character in the page you cite. Keep it tight so it proves exactly this field.",
        "- `source.page`: the 1-indexed page the span is on.",
        "- `confidence` in [0,1]: how clearly legible, unambiguous source text supports the",
        "  value. If the text is garbled/ambiguous, or you had to guess, use < 0.85.",
        "- `needs_review`: true whenever confidence < 0.85 or value is null.",
        "",
        "CRITICAL — DISTRACTORS you must NOT pick:",
        "- ISSUE date = the `DATE ISSUED` only — NOT revision date, NOT form-printed, NOT the",
        "  signature date.",
        "- policy_number = the coverage row's POLICY NUMBER — NOT certificate number, NOT",
        "  master/quote ref, NOT NAIC #, NOT prior-carrier policy, NOT a claim/police-report #.",
        "- insured / certificate_holder = the named insured and the certificate-holder block —",
        "  NOT additional-insured or project-owner names.",
        "- limit = the PRIMARY per-occurrence limit ONLY: General Liability=`Each Occurrence`,",
        "  Auto=`Combined Single Limit`, Umbrella=`Each Occurrence`, Workers Comp=`E.L. Each",
        "  Accident`, Professional=`Each Claim`. NEVER an aggregate, disease, or sub-limit.",
        "- effective/expiration dates come from the coverage's POLICY EFF / POLICY EXP row.",
        "",
        "LEARNED RULES (notes.md — persistent memory from prior runs):",
        notes,
    ]
    if feedback:
        parts += [
            "",
            "A PRIOR ATTEMPT FAILED VERIFICATION. Fix exactly these problems and keep",
            "everything else grounded:",
            feedback,
        ]
    parts += ["", "DOCUMENT TEXT:", doc_text, "", "Return ONLY the JSON envelope."]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# model invocation
# --------------------------------------------------------------------------
def _extract_json_object(text: str) -> dict:
    """Pull the first complete JSON object out of a model response (tolerates
    ```json fences and surrounding prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("`").strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON object in model output")


def _call_cli(user: str, system: str) -> dict:
    cmd = [
        "claude", "-p", user,
        "--append-system-prompt", system,
        "--output-format", "json",
        "--model", MODEL,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT,
        stdin=subprocess.DEVNULL, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed rc={proc.returncode}: {proc.stderr[-400:]}")
    raw = proc.stdout.strip()
    try:
        wrapper = json.loads(raw)
    except json.JSONDecodeError:
        return _extract_json_object(raw)
    if isinstance(wrapper, dict) and "result" in wrapper:
        payload = wrapper["result"]
        return payload if isinstance(payload, dict) else _extract_json_object(str(payload))
    return wrapper


def _call_api(user: str, system: str) -> dict:
    import anthropic  # type: ignore

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _extract_json_object(text)


def call_model(user: str, system: str = SYSTEM_PROMPT) -> dict:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return _call_api(user, system)
        except ImportError:
            pass
    return _call_cli(user, system)


# --------------------------------------------------------------------------
# post-normalization (defense in depth; the verifier re-derives the same way)
# --------------------------------------------------------------------------
def _normalize_envelope(env: dict, active: dict) -> dict:
    for name, prop in active.get("properties", {}).items():
        if name not in env or env[name] is None:
            continue
        if prop.get("type") == "array" and prop.get("items", {}).get("type") == "object":
            sub_props = prop["items"].get("properties", {})
            for item in env[name]:
                if not isinstance(item, dict):
                    continue
                for sub, sub_schema in sub_props.items():
                    if sub in item and isinstance(item[sub], dict):
                        _normalize_cell(item[sub], S.classify(sub_schema))
        elif isinstance(env[name], dict):
            _normalize_cell(env[name], S.classify(prop))
    return env


def _normalize_cell(cell: dict, kind: str) -> None:
    if cell.get("value") is not None:
        cell["value"] = N.normalize_value(cell["value"], kind)
    # enforce the routing invariant locally too
    conf = cell.get("confidence")
    if cell.get("value") is None:
        cell["needs_review"] = True
    if isinstance(conf, (int, float)) and conf < 0.85:
        cell["needs_review"] = True


# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------
def extract(pdf_path: str, feedback: Optional[str] = None) -> dict:
    active = S.load_schema(os.path.join(ROOT, "config", "active.schema.json"))
    doc_text = pdftext.full_text(pdf_path)
    user = build_user_prompt(active, doc_text, feedback)
    env = call_model(user)
    return _normalize_envelope(env, active)


def main():
    ap = argparse.ArgumentParser(description="Extract one PDF to an envelope")
    ap.add_argument("pdf")
    ap.add_argument("--feedback", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    env = extract(args.pdf, feedback=args.feedback)
    text = json.dumps(env, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
