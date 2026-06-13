# CLAUDE.md — Self-Verifying Insurance Document Indexer

Turns emailed insurance PDFs (COIs, FNOL packets) into **verified** structured records:
every field traces to a verbatim source span, low-confidence fields self-route to a
review queue, updates reconcile with a field-level diff, and one config file re-targets
the pipeline to any document type. Synthetic corpus; all code original.

## Spine
- `extract.py` — one PDF → extraction envelope `{value, confidence, source span, needs_review}`, keyed to `config/active.schema.json`. **Schema-agnostic** (no field names hardcoded).
- `verifier.py` — independent, **deterministic** grader of `.claude/verifier-rubric.md` (grounding, schema via jsonschema, confidence-routing, no-fabrication, reconciliation, accuracy vs `config/answer-key.json`). Exits 0 iff the run passes.
- `workflow.py` — the **code-held loop**: per doc → load notes → extract (model) → verify → route to `index/` or `review-queue/` → on fail feed verifier reasons back and retry (≤3). Checkpoints to disk.
- `pdftext.py` / `normalize.py` / `schema_util.py` — shared: one PDF→text path for builder + grader (OCR fallback for image-only pages), ISO/integer normalization, schema walker.
- `viewer.py` → `viewer/index.html` — thin record viewer (field + source span + verifier report + diff). Not a dashboard.

## Run
```bash
pip install pdfplumber jsonschema pytesseract pdf2image   # + system tesseract, poppler (scan only)
python workflow.py [--watch|--doc NAME|--force]
python verifier.py        # exits 0 when DONE
python viewer.py --serve  # http://localhost:8000
```

## Non-obvious constraints (read before editing)
- **Model invocation:** `workflow.py`→`extract.py` calls the model **per document** via the local `claude` CLI in headless `-p` mode (no API key — same login as Claude Code). **Do NOT use the `--json-schema` flag — it hangs when `claude -p` runs nested inside a Claude Code session.** `extract.py` parses the first JSON object from the response instead. Optional faster/deterministic path: set `ANTHROPIC_API_KEY` in `.env` (loaded by `extract.py`) → uses the `anthropic` SDK. Model id `claude-opus-4-8`; on 4.8 the API rejects `temperature`/`top_p`/`top_k` (400) — don't add them.
- **Config swap = no code change:** `cp config/fnol.schema.json config/active.schema.json` re-targets extraction. `config/active.schema.json` ships as COI (documented start state).
- **Per-record schema grading:** each record stores `schema_title`; the verifier grades it against the matching `config/*.schema.json` (not just `active`), so a mixed COI+FNOL index verifies green in one run.
- **Review-queue records are NOT held to full schema conformance.** An illegible required field (the reason a degraded scan is queued) makes strict `pass` False but the record is still run-acceptable (`run_ok`) via a routing bar: grounding + no-fabrication + correct flagging. Indexed records must pass every gate.
- **On-disk memory:** `.claude/notes.md` is loaded at the start of every extraction and appended on each self-corrected failure. It is a live runtime file — paths in `extract.py` (`_read_notes`) and `workflow.py` (`NOTES`) point at `.claude/notes.md`.
- **Distractors the extractor must avoid** (also in `.claude/notes.md`): ISSUE date ≠ revision/printed/signature dates; policy_number ≠ certificate/quote/NAIC/claim/police numbers or prior-carrier policy; `limit` = PRIMARY per-occurrence only (GL/Umbrella `Each Occurrence`, Auto `Combined Single Limit`, WC `E.L. Each Accident`, Professional `Each Claim`) — never aggregates; certificate_holder/insured ≠ additional-insured names.

## Definition of done
`verifier.py` exits 0 on the labeled set (`score == 1.0`): 100% grounded, indexed records 100% schema-valid, accuracy == 100%, fabrication == 0, and every low-confidence field correctly in `review-queue/`.

## Specs / planning (moved into `.claude/`)
`.claude/goal.md` (target + done), `.claude/verifier-rubric.md` (the gates), `.claude/orchestration-brief.md` (design), `.claude/kickoff-prompt.md` (original brief), `.claude/notes.md` (learned rules). `README.md` stays in root.
