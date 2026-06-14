# Live Q&A Cheat Sheet

Self-Verifying Insurance Document Indexer · live demo: https://viewer-puce-phi.vercel.app

> **One-liner:** Emailed insurance PDFs → verified structured records where every field is grounded to its source, independently verified, self-routes its own uncertainty, and is re-targetable to any insurer by editing one config file.

---

## ⭐ The two they'll press on hardest

**Q. How do you know the extraction is *correct*, not just plausible?**
Three layers: (1) **Grounding** — every field carries its verbatim source span, deterministically confirmed to exist in the doc, so nothing is invented. (2) **Accuracy** — Gate 6 compares values to a ground-truth answer key (proves *meaning*, not just provenance). (3) **Independent verification** — the grader is deterministic code, not the model; "done" = `verifier.py` exits 0. Anything uncertain self-routes to review instead of being asserted.

**Q. Your corpus is synthetic — does this work on real documents?**
The *pipeline* is real (pdfplumber text layer, OCR fallback, schema-driven extraction, deterministic verification). Synthetic is deliberate: clean-room (no client data/IP) and it lets me control the messy beat. It's ACORD-*style*, so real forms share the structure. For production: seed a labeled held-out set so Gate 6 grades real accuracy, and let the loop accumulate doc-specific rules in its on-disk memory — both already supported.

---

## Impact / product
- **Who's the user?** Claims intake, underwriting support, policy admin at MGAs, carriers, wholesale brokers — teams hand-keying emailed PDFs today.
- **ROI?** ~15–20 min of hand-keying + double-checking per packet → seconds, *with* a field-level audit trail. (Illustrative, not a benchmarked stat.)
- **Why not just existing OCR/IDP?** IDP gives you fields; it doesn't *prove* each field, route its own uncertainty, reconcile updates with a diff, re-target to any doc type via one config file, or let a non-engineer reconfigure it by chatting with an agent.

## Trust / correctness
- **Who verifies the verifier?** It's deterministic code (JSON-Schema validation, regex/string matching, answer-key compare) — not a model. Can't hallucinate; logic is auditable; ground truth is the answer key you maintain.
- **What if the model hallucinates?** No-fabrication gate: an ungrounded value fails grounding → must be null → flagged for review. A confident-but-wrong value that *is* in the doc is caught by Gate 6 vs. ground truth.
- **Isn't grounding just string matching?** Yes, deliberately — provenance should be cheap and deterministic. Correctness is a *separate* gate (accuracy vs. ground truth).
- **Doc with no answer key?** Gate 6 → n/a; you still get grounding, schema, confidence-routing, no-fabrication. Accuracy grading needs a labeled set, seeded once per doc type.

## The model (Opus 4.8)
- **Why Opus 4.8?** Handles distractor-heavy extraction zero-shot (issue date not revision date; per-occurrence not aggregate), follows the strict envelope/schema reliably. It also *built* the app.
- **Cost / latency at scale?** One bounded call per doc — seconds, a few cents. Tierable (Haiku/Sonnet on easy docs, Opus on hard), batchable. The verifier is free (deterministic).
- **Deterministic?** Extraction isn't (it's an LLM) — which is exactly why the deterministic verifier + retry loop exists. The *outcome* is gated: a record only lands in the index if it passes every check.

## Generalization / scale
- **Unseen document type?** Router parks it to review (never auto-onboards). A human or the config agent authors a schema → handled from then on. No code change.
- **Handwriting / bad scans?** OCR handles image-only pages; handwriting isn't solved — but it degrades gracefully: low-confidence → review, not a guess (see the Pinecrest scan).
- **Volume / throughput?** Stateless per-doc, checkpointed → embarrassingly parallel. The watched folder fakes email; production swaps in IMAP / an email webhook with no core change.
- **Other languages / non-ACORD?** Same mechanism; add a schema (+ a few rules if needed). Nothing is hardcoded to ACORD.

## Config agent & flexibility
- **Isn't the chat a "chat with your index" / RAG box?** No — it's strictly **builder-side**: it helps an insurer *define what to collect* (author a schema/profile). It never queries or summarizes indexed records; no DB access.
- **What stops a broken schema?** A linter + behavioral round-trip + draft-07 meta-validation run before any write; nothing activates unless it passes, with a model-retry-on-invalid loop. Schemas are constrained to the supported shape.
- **How does the config-swap work?** Every component reads `config/active.schema.json`; extractor + verifier are schema-agnostic. Swap the file → pipeline re-targets. That's how COI/FNOL/Binder run on one codebase.

## Per-insurer adaptation
- **Routes differently per company?** A profile (config) maps line-of-business → department and producer → agency code per insurer. Same doc → `CL` for an admitted MGA, `SPEC` for an E&S wholesaler. Config only.
- **Agency codes are mocked — why?** Real resolution hits the insurer's agency-management system, which a clean-room demo shouldn't touch. The mechanism is real + deterministic; only the lookup table is synthetic.

## Architecture / autonomy
- **Autonomy in one line?** Builder ≠ grader: the model extracts, a deterministic verifier independently grades, the loop self-corrects from the verifier's reasons until it exits 0. The log shows the *script + verifier* steering, not me.
- **Why a code-held loop, not one big agent run?** Bounded per-doc steps don't drift, survive restarts (checkpointed), and hold only one document's context — more robust and more verifiable.
- **Mixed doc types in one index?** Each record stores its `schema_title`; the verifier grades it against its *own* schema — so a COI+FNOL+Binder index verifies green in one run.

## Security / production
- **PII / privacy?** Corpus is synthetic. In production the source-span audit trail is exactly what insurers/regulators want; add per-tenant isolation + retention controls.
- **API key for the live chat?** Server-side only — in the Vercel function's env, never sent to the browser; chat scoped to config authoring.
- **Production-ready?** Hackathon build on synthetic data, but the spine is real and the verification discipline is production-grade. Next: real email ingestion, a review-queue write-back UI, labeled-set bootstrapping per doc type, model tiering.

## Honest limitations (candor lands well)
- Small synthetic labeled set; real accuracy needs a real labeled set per doc type.
- Handwriting / severely degraded scans degrade to review (by design), not solved.
- One array-of-objects per schema — a doc needing two repeating groups (e.g. property locations *and* a claims list) flattens the secondary one.
- Live chat is a real model call — network/API dependent on stage (pre-warm it).

## How it was built (one-liner)
Built end-to-end in Claude Code on Opus 4.8 (1M context): front-loaded spec, autonomous self-correcting loop steered by the verifier, plus multi-agent workflows for design analysis, adversarial verification, and an open-source security audit. The way I directed Claude mirrors the app's own architecture — spec + code-held loop + independent verifier.

---

## Don't-trip notes (for the demo itself)
- **Don't** click a source span on the *scanned* Pinecrest doc — image-only, no highlight. Just show its flagged fields.
- **Pre-warm the chat** once before presenting; if it lags, say "it's drafting the schema live" and move on.
- Strong openers: the clean **Harborview binder** or **COI-1001** (rich, clean fields).
