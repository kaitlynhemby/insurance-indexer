# CLAUDE.md — Self-Verifying Insurance Document Indexer

Turns emailed insurance PDFs (COIs, FNOL packets) into **verified** structured records:
every field traces to a verbatim source span, low-confidence fields self-route to a
review queue, updates reconcile with a field-level diff, and one config file re-targets
the pipeline to any document type. Synthetic corpus; all code original.

**Live viewer:** https://viewer-puce-phi.vercel.app (Vercel, static — see Deploy below).

## Spine
- `extract.py` — one PDF → extraction envelope `{value, confidence, source span, needs_review}`, keyed to `config/active.schema.json`. **Schema-agnostic** (no field names hardcoded).
- `verifier.py` — independent, **deterministic** grader of `.claude/verifier-rubric.md` (grounding, schema via jsonschema, confidence-routing, no-fabrication, reconciliation, accuracy vs `config/answer-key.json`). Exits 0 iff the run passes.
- `workflow.py` — the **code-held loop**: per doc → load notes → extract (model) → verify → route to `index/` or `review-queue/` → on fail feed verifier reasons back and retry (≤3). Checkpoints to disk.
- `pdftext.py` / `normalize.py` / `schema_util.py` — shared: one PDF→text path for builder + grader (OCR fallback for image-only pages), ISO/integer normalization, schema walker.
- `viewer.py` → `viewer/index.html` — thin record viewer (field + source span + verifier report + diff). Not a dashboard.
- `router.py` — pre-extraction **schema selector**: classifies an inbound PDF's `document_type` (grounded) and picks the matching `config/*.schema.json` so a MIXED inbox is each doc extracted against the right schema with no manual config swap. A thin stage reusing `extract.call_model` + the envelope shape — not an agent. `workflow.py --route` uses it; `router.py --grade` accuracy-checks the selection against `answer-key.json` `routing_set`. Unknown/low-confidence types park in `review-queue/` (never auto-onboard).
- `profiles.py` + `config/profiles/` — **per-insurer process profiles** (department codes, line-of-business→department taxonomy, admitted/surplus, a MOCK agency-code lookup). The active profile (`config/profiles/active.json`) makes the SAME doc route to different departments per insurer — config-only, no code change. `router.py --annotate` writes a deterministic `routing` block onto records (no re-extraction); `schema_agent.py profile <id>` authors a profile over the channel. Two synthetic insurers ship: `harborview-mga` (admitted) and `sierra-surplus` (E&S). Unit-tested in `tests/test_profiles.py`.
- `schema_agent.py` + `channels/` — the **config-authoring agent**: designs/edits `config/<DocType>.schema.json` for what an insurer needs to collect, asks the insurer about gaps over a pluggable channel (console default; `discord` via REST+polling; `whatsapp` stretch stub), validates, activates, and re-runs the pipeline to self-verify. Builder-side only — never queries the index.

## Run
```bash
pip install pdfplumber jsonschema requests pytesseract pdf2image   # + system tesseract, poppler (scan only)
python workflow.py [--watch|--doc NAME|--force]
python verifier.py        # exits 0 when DONE
python viewer.py --serve  # http://localhost:8000
python schema_agent.py onboard "<doc-type desc>" --samples <dir> [--channel discord] [--keep]
python schema_agent.py review --samples <dir>        # data-driven gap pass on the active schema
python schema_agent.py profile <id> "<desc>" [--activate]   # author a per-insurer routing profile
python workflow.py --route                           # classify each inbox doc + auto-select its schema (mixed inbox)
python router.py --grade                             # routing accuracy gate (exits 0 on pass)
python router.py --annotate --profile <id>           # write per-insurer routing metadata onto records (for the viewer)
python tests/test_schema_lint.py && python tests/test_profiles.py   # guard + profile unit checks
```

## Deploy
The viewer is a self-contained static `viewer/index.html` (records embedded at generation time — no build, no server). Deployed to Vercel: `python viewer.py` then `vercel deploy ./viewer --prod --yes --scope <scope> --token=$VERCEL_TOKEN`. New Vercel projects enable Deployment Protection (Vercel Authentication) by default → the URL 401s for the public; disable it via `PATCH /v9/projects/<id>` with `{"ssoProtection": null}` (done for the live project). `.vercel/` is gitignored.

## Non-obvious constraints (read before editing)
- **Model invocation:** `workflow.py`→`extract.py` calls the model **per document** via the local `claude` CLI in headless `-p` mode (no API key — same login as Claude Code). **Do NOT use the `--json-schema` flag — it hangs when `claude -p` runs nested inside a Claude Code session.** `extract.py` parses the first JSON object from the response instead. Optional faster/deterministic path: set `ANTHROPIC_API_KEY` in `.env` (loaded by `extract.py`) → uses the `anthropic` SDK. Model id `claude-opus-4-8`; on 4.8 the API rejects `temperature`/`top_p`/`top_k` (400) — don't add them.
- **Config swap = no code change:** `cp config/fnol.schema.json config/active.schema.json` re-targets extraction. `config/active.schema.json` ships as COI (documented start state).
- **Per-record schema grading:** each record stores `schema_title`; the verifier grades it against the matching `config/*.schema.json` (not just `active`), so a mixed COI+FNOL index verifies green in one run.
- **Review-queue records are NOT held to full schema conformance.** An illegible required field (the reason a degraded scan is queued) makes strict `pass` False but the record is still run-acceptable (`run_ok`) via a routing bar: grounding + no-fabrication + correct flagging. Indexed records must pass every gate.
- **On-disk memory:** `.claude/notes.md` is loaded at the start of every extraction and appended on each self-corrected failure. It is a live runtime file — paths in `extract.py` (`_read_notes`) and `workflow.py` (`NOTES`) point at `.claude/notes.md`.
- **Distractors the extractor must avoid** (also in `.claude/notes.md`): ISSUE date ≠ revision/printed/signature dates; policy_number ≠ certificate/quote/NAIC/claim/police numbers or prior-carrier policy; `limit` = PRIMARY per-occurrence only (GL/Umbrella `Each Occurrence`, Auto `Combined Single Limit`, WC `E.L. Each Accident`, Professional `Each Claim`) — never aggregates; certificate_holder/insured ≠ additional-insured names.
- **Authored schemas must stay in the supported shape** (draft-07 object of scalar leaves + at most one array-of-objects + `x_natural_key`; NO `$ref`/`oneOf`/nested objects/array-of-scalars). `schema_util.lint_authored_schema` + `roundtrip_ok` + `title_collision` enforce this; `schema_agent.py` writes/activates nothing unless they pass (with a model-retry-on-invalid loop). Titles must be unique (the verifier keys schemas by title). `onboard` defaults to restoring `active=COI` + removing sample records (use `--keep` for a live demo); `review` adds fields as OPTIONAL so existing records of an edited type still validate.

## Definition of done
`verifier.py` exits 0 on the labeled set (`score == 1.0`): 100% grounded, indexed records 100% schema-valid, accuracy == 100%, fabrication == 0, and every low-confidence field correctly in `review-queue/`.

## Specs / planning (moved into `.claude/`)
`.claude/goal.md` (target + done), `.claude/verifier-rubric.md` (the gates), `.claude/orchestration-brief.md` (design), `.claude/kickoff-prompt.md` (original brief), `.claude/notes.md` (learned rules). `README.md` stays in root.
