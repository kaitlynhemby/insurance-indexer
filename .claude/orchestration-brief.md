# Orchestration Brief — Self-Verifying Insurance Document Indexer
**Live Build Day · Claude Code + Claude Opus 4.8 · ~6.5-hour single-day build · v3 (model-swap: Fable 5 → Opus 4.8)**

> **Model note (Fable 5 → Opus 4.8):** The architecture below is model-agnostic and unchanged; the scoring targets are unchanged. What changes is *tactics* for the Autonomy + Orchestration 30%: instead of leaning on one long unsteered model run, the **orchestration script holds the loop** and invokes Opus in **bounded, per-document steps**, with state checkpointed to disk and a fresh-context verifier catching breaks — arguably more robust. The rules help you here: Orchestration is judged "from the brief, rubric, and workflow scripts, **not from which features were used**," so swapping any Fable-only feature (`/goal`, the background dynamic-workflow runtime) for a plain script costs no points. Verify in advance whether `/goal` and background workflows are available with Opus in Claude Code; nothing below hard-depends on them.

---

## 0. One-line
A configurable pipeline that turns emailed insurance PDFs into structured records where every field traces back to its source, is graded for correctness against an answer key, routes low-confidence data to a human, and re-verifies as new documents arrive.

---

## 1. Problem & who it's for *(Impact, 35%)*
Indexing emailed insurance documents — certificates of insurance, claims/FNOL packets, policy declarations — is a weeks-long back-office slog done by hand, and it goes stale the moment a new document arrives. The teams that live this are claims intake, underwriting support, and policy administration. The output that matters to them is a **trustworthy, current, provable index**: a record they can act on without re-reading the source, because every field shows its work and anything uncertain is flagged rather than guessed.

This hits the named thought-starter directly: *"a claims, loan-servicing, or back-office workflow that takes weeks today."*

**Quantified opener (for the demo):** a clerk who hand-keys and double-checks a single claims packet in ~15–20 minutes does it in seconds here — with a field-level audit trail that doesn't exist in the manual process today. *(Use a real public benchmark if you can find one, or say "illustrative" — never invent a precise stat for the judges.)*

> **Eligibility note:** Clean-room build from the general process pattern only. No client name, no client data, no proprietary IP. Demo corpus is synthetic / public ACORD-style samples. This clears the "rights to data" and "own work" disqualifiers cleanly.

---

## 2. System spine (what must work)
```
PDF lands in /inbox  →  EXTRACT to canonical schema (field-level provenance + confidence)
                     →  VERIFY (fresh-context agent grades against rubric + answer key)
                          ├─ pass            → write to /index
                          ├─ low-confidence  → route to /review-queue (flagged, not asserted)
                          └─ fail            → return reasons to builder, retry (max N)
updated PDF lands    →  RECONCILE (field-level diff) → re-verify changed fields → update /index
```
- **Watched folder fakes the email layer** — no IMAP/auth on stage.
- **The canonical schema is a config file** — swapping it re-targets the pipeline to a new doc type with no code change.
- **UI is thin**: a record viewer that shows each field's verbatim source span, the verifier report, and the diff. The *pipeline, the diff, and the config swap* are the headline — not a browsable table (keeps clear of the dashboard ban).

---

## 3. The target the loop optimizes against *(`goal.md`)*
Save as `goal.md`. This is the target the build loops against and verifies itself on. If `/goal` is available with Opus in Claude Code, use it; if not, the workflow script (§6) holds this target and re-invokes Opus until the verifier passes — same hillclimb behavior, no dependency on a Fable-only primitive.

```
GOAL: Index every PDF in /inbox into a verified record in /index, and keep it current.

DONE when ALL hold on the demo corpus AND a labeled held-out set of >=5 docs
(including >=1 deliberately degraded scan):

  1. GROUNDING — 100% of populated fields carry provenance (page + verbatim text span,
     or bbox) that is locatable in the source document.
  2. CONFORMANCE — 100% of records validate against the active canonical schema
     at config/active.schema.json. Zero schema violations.
  3. CONFIDENCE — every field with confidence < 0.85 is marked needs_review=true
     and its record is routed to /review-queue. No low-confidence field is presented as final.
  4. NO FABRICATION — any field unsupported by the source is null + needs_review, never invented.
  5. RECONCILIATION — on an updated document, the diff is field-accurate (changed detected,
     unchanged preserved) and changed fields are re-verified.
  6. ACCURACY — on the labeled held-out set (config/answer-key.json), every field MATCHES
     ground truth after normalization. This proves the extraction is CORRECT, not merely grounded.
  7. SELF-PROVING — verifier exits 0 on the held-out set with zero human edits.

HILLCLIMB SIGNAL (maximize toward 1.0):
  score = field_accuracy_vs_answer_key        # correctness — the real gradient
        * pct_records_schema_valid
        * (1 - fabrication_rate)
  (grounding and confidence-routing are hard gates, not part of the score.)

LOOP: read the verifier's output each round, fix the single largest failing gate,
re-run. Do not stop until score == 1.0 on the held-out set.
```

---

## 4. The verifier rubric *(the heart of Autonomy + Orchestration, 30%)*
Save as `verifier-rubric.md`. A **fresh-context** sub-agent (or `verifier.py`) grades each record against this and emits structured pass/fail — grading happens independently of the builder, which is why it beats self-critique. "Done" is this file passing, not a human's opinion.

```
For each record, emit: { "doc_id", "gates": {...}, "pass": bool, "reasons": [...] }

GATE 1 — Span grounding   [BINARY, per field]
  For every populated field, the value (after normalization: trim, date-parse,
  currency-parse) must be locatable in the source OCR text or carry a valid page+bbox.
  PASS only if 100% of populated fields are grounded.
  NOTE: grounding proves PROVENANCE, not CORRECTNESS — a value can appear in the doc
  and still sit in the wrong field. Gate 6 closes that gap.

GATE 2 — Schema conformance   [per record]
  The .value layer validates against config/active.schema.json: required fields present,
  types correct, enums valid, date/currency formats valid. PASS if validator returns zero errors.

GATE 3 — Confidence routing   [per field]
  Every field has confidence in [0,1]. Any field < 0.85 MUST have needs_review=true and the
  record MUST be in /review-queue, not /index. FAIL if any sub-threshold field is asserted as final.

GATE 4 — No fabrication   [per field]
  Any field whose value cannot be grounded (Gate 1) must be null. FAIL if a non-null value lacks a source.

GATE 5 — Reconciliation (update path only)   [per updated doc]
  Diff lists exactly the fields whose grounded value changed vs the prior record. Unchanged fields
  are byte-identical to prior. Changed fields are re-grounded. FAIL on any spurious or missed diff entry.

GATE 6 — Accuracy vs ground truth   [labeled held-out set only]
  Each field matches config/answer-key.json after normalization. This is the ONLY gate that proves
  the extraction MEANING is right, and it's what makes "done" verifiable by the model at demo time
  without a human re-reading documents. FAIL on any mismatch.

A record PASSES only if every applicable gate passes.
The RUN passes only if every record passes or is correctly in /review-queue.
```

**Extraction envelope** (so grounding/confidence are first-class and the verifier's job is mechanical):
```json
{
  "field_name": {
    "value": "<normalized value | null>",
    "confidence": 0.0,
    "source": { "page": 1, "text_span": "<verbatim source substring>", "bbox": [x, y, w, h] },
    "needs_review": false
  }
}
```

---

## 5. Canonical schemas *(two doc types = the live config-swap proof)*
Two deliberately different shapes so swapping them on stage is visibly real, not cosmetic. The active one lives at `config/active.schema.json`; swapping = copying one over it.

**`config/coi.schema.json` — Certificate of Insurance (nested coverages array):**
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CertificateOfInsurance",
  "type": "object",
  "required": ["document_type", "insured_name", "certificate_holder", "issue_date", "coverages"],
  "properties": {
    "document_type":      { "const": "certificate_of_insurance" },
    "producer":           { "type": "string" },
    "insured_name":       { "type": "string" },
    "certificate_holder": { "type": "string" },
    "issue_date":         { "type": "string", "format": "date" },
    "coverages": {
      "type": "array", "minItems": 1,
      "items": {
        "type": "object",
        "required": ["coverage_type", "policy_number", "effective_date", "expiration_date"],
        "properties": {
          "coverage_type":   { "type": "string", "enum": ["general_liability","auto_liability","umbrella","workers_comp","property","professional_liability"] },
          "policy_number":   { "type": "string" },
          "effective_date":  { "type": "string", "format": "date" },
          "expiration_date": { "type": "string", "format": "date" },
          "limit":           { "type": "number" }
        }
      }
    }
  }
}
```

**`config/fnol.schema.json` — First Notice of Loss (flatter, different enums):**
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "FirstNoticeOfLoss",
  "type": "object",
  "required": ["document_type", "policy_number", "loss_date", "loss_description", "reported_by"],
  "properties": {
    "document_type":      { "const": "first_notice_of_loss" },
    "policy_number":      { "type": "string" },
    "policyholder_name":  { "type": "string" },
    "loss_date":          { "type": "string", "format": "date" },
    "report_date":        { "type": "string", "format": "date" },
    "loss_type":          { "type": "string", "enum": ["auto","property","liability","workers_comp","other"] },
    "loss_location":      { "type": "string" },
    "loss_description":   { "type": "string" },
    "claimant_name":      { "type": "string" },
    "reported_by":        { "type": "string" },
    "estimated_severity": { "type": "string", "enum": ["low","medium","high","unknown"] }
  }
}
```

---

## 6. The build loop / dynamic workflow *(Orchestration, 15%)*
Have Claude Code write this as a plain workflow script (`workflow.js` / `workflow.py`) that **holds the loop in code** and invokes Opus in **bounded, per-document steps** — so no single model run has to stay coherent for hours, and the context only ever holds one document's worth of work. State is checkpointed to disk (`/index`, `/review-queue`, `notes.md`) so the run survives any single step failing. Be explicit about what fans out, when verification runs, and what gates completion:

```
1. WATCH  /inbox for new or changed PDFs.
2. For each doc, FAN OUT a builder agent:
     a. extract text (pdf text layer; OCR fallback only for image-only pages)
     b. emit the extraction envelope keyed to config/active.schema.json
3. VERIFY in a FRESH context (verifier-rubric.md + answer key). Builder never grades itself.
4. GATE:
     - all gates pass            -> write /index/<doc_id>.json
     - confidence gate routes it -> write /review-queue/<doc_id>.json (flagged)
     - a gate fails              -> return reasons to builder; retry up to N=3
5. UPDATE PATH: if doc_id already indexed, RECONCILE -> diff -> re-verify changed fields.
6. COMPLETION GATE: run verifier on the labeled held-out set; the run is DONE only when it
   exits 0 (every record passed or correctly queued, zero schema violations, accuracy == 100%).
```

**File-based memory as the outer loop:** keep a persistent `notes.md` on disk (not in context). When an extraction fails and gets fixed, have the model append the fix as a reusable rule (e.g., *"on COIs, take the POLICY EXP from the coverage row — not the revision date in the header"*) and load `notes.md` at the start of each per-document step. This matters more with Opus than it would with Fable: because state lives on disk and each invocation is bounded, the loop re-derives nothing, doesn't depend on a giant context window, and survives restarts. Push it through fail → investigate → verify → distill.

---

## 7. Demo choreography *(Demo, 35% — ~3.5 min, beat by beat)*
1. **(15s) Frame it.** "Indexing emailed insurance PDFs takes teams weeks. Here it's seconds — and it proves every field." (Drop the quantified before/after from §1.)
2. **(45s) Clean COI.** Drop a clean certificate into `/inbox` live. Pipeline extracts → show the record with the **verbatim source span beside every field** (this is your reliable grounding proof). If the bbox click-to-highlight overlay is working, click a field to flash its region in the PDF — but the span text alone already proves it. Verifier report flashes green.
3. **(45s) The catch.** Drop the degraded scan. A field drops below 0.85 → it **auto-routes to the review queue, flagged, not asserted.** Say it out loud: *"It caught its own uncertainty — no human told it to."* (Your Autonomy money shot.)
4. **(45s) Stays current.** Drop an updated COI (new expiration date). Pipeline detects the change → shows a **field-level diff** → re-verifies only the changed field. *"The index keeps itself current."*
5. **(45s) Config swap.** Copy `fnol.schema.json` over `active.schema.json`, drop an FNOL packet — **no code change** — new doc type indexed. *"Another team could point this at any insurance document tomorrow."* (Orchestration, proven live.)
6. **(15s) Self-proving.** Show the session log / `verifier` exiting 0 on the labeled held-out set unattended.

**Corpus to prepare:** 3–4 clean COIs (**born-digital — real text layer, so extraction is reliable and doesn't eat your day**), 1 deliberately degraded **scan** (the only doc that exercises OCR — used purely for the confidence-catch beat), 1 updated COI, 2 FNOL packets. **Hand-label 5 of them into `config/answer-key.json`** so the verifier can grade accuracy, not just groundedness. Generate them yourself (synthetic ACORD-style) — you control the messy beat and carry zero rights risk.

---

## 8. Repeatable setup *(the section judges read for Orchestration)*
Another team reruns this on a new problem in three steps:
1. **Drop a schema.** Put your doc type's canonical schema at `config/active.schema.json`.
2. **Seed docs.** Drop sample PDFs into `/inbox` (and label a few into `config/answer-key.json` if you want accuracy grading).
3. **Run.** `make index` (or `python workflow.py`) — watcher, builder, verifier, and queue run unattended.

**"Done" is verifiable without a human:** `verifier.py` (graded against `verifier-rubric.md` + answer key) exits `0` on the held-out set, and the index viewer serves at a responding URL. No subjective judgment, no human gate.

**Anti-DQ hygiene:** start from an **empty repo** so the session log shows everything was built during the event; add a `README.md` stating that all code is original and the corpus is synthetic. This protects against the "own work / rights to data" disqualifiers.

**Artifacts to submit:** `goal.md`, `verifier-rubric.md`, `workflow.{js,py}`, `config/*.schema.json`, `config/answer-key.json`, `notes.md`, `README.md`, and the session log.

---

## 9. Run-the-day plan & scope guardrails
Land a working slice early, then layer. **Protect the demo above all — a small thing that works beats a big thing that's broken at 5pm.**

```
CHECKPOINT 1 (~by midday): spine works end-to-end on born-digital COIs —
  drop → extract → verify (gates 1,2,3,6) → /index or /review-queue. DEMOABLE.
  If you only hit this, you still have a winning-shape demo. LOCK IT.
CHECKPOINT 2: config swap COI→FNOL (cheap — it's a schema swap).
CHECKPOINT 3: update/diff path (medium).
CHECKPOINT 4 (only if ahead): bbox click-to-highlight in the viewer (expensive, optional).
```

**Must work (spine):** watched folder · extract-to-schema (COI) · provenance+confidence envelope · gates 1/2/3/6 · review-queue routing · COI→FNOL config swap · thin viewer showing the record, the verbatim source span per field, the verifier report.

**Cut first if behind:** real IMAP · handwriting OCR · >2 doc types · **bbox highlight overlay (fall back to showing the verbatim source-span TEXT beside each field — proves grounding just as well, trivial to render)** · update/diff path · styling polish.

**Don't add:** a "chat with your index" box (drifts toward banned basic-RAG) · a metrics/overview screen as a centerpiece (dashboard ban) · anything framed as fraud-detection/security (risks cyber routing). Headline the **action** (verified extraction, diff, config swap), never the view.

---

## 10. How each piece scores
- **Impact (35%):** weeks-to-seconds on a named back-office workflow, for a real audience, with a quantified before/after and an output people trust because it's grounded, accuracy-checked, and current.
- **Demo (35%):** self-contained (watched folder, no live external deps), three earned "wow" beats — source span per field, the self-catch, the live config swap — with a checkpoint plan that guarantees something demoable.
- **Autonomy (15%):** the **code-held loop** runs the corpus end-to-end while the fresh-context verifier catches breaks and the confidence gate catches the model's own uncertain or incorrect extractions — so the session log shows the *script and verifier* doing the steering, not you. **Run it so the log shows this:** front-load the full spec in your opening prompt, let the workflow script drive the per-document loop unattended, and keep human messages to *new information*, not course-corrections. With Opus this is the safer autonomy story anyway — bounded, verifiable steps beat one long run that can drift.
- **Orchestration (15%):** one config file re-targets the whole pipeline; "done" is a verifier exit code + a responding URL + 100% accuracy on the answer key; the setup reruns on any doc type tomorrow.
