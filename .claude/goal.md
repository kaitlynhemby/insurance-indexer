# goal.md — Target & Definition of Done
*Self-verifying insurance document indexer · Claude Opus 4.8*

**GOAL:** Index every PDF in `/inbox` into a verified record in `/index`, and keep it current as new or updated PDFs arrive.

## DONE when ALL of these hold
…on the demo corpus AND the labeled held-out set in `config/answer-key.json` (≥5 docs, including ≥1 degraded scan):

1. **GROUNDING** — 100% of populated fields carry provenance (page + verbatim text span, or bbox) locatable in the source document.
2. **CONFORMANCE** — 100% of records validate against the active canonical schema (`config/active.schema.json`). Zero schema violations.
3. **CONFIDENCE** — every field with confidence < 0.85 is marked `needs_review=true` and its record routed to `/review-queue`. No low-confidence field is presented as final.
4. **NO FABRICATION** — any field unsupported by the source is `null` + `needs_review`, never invented.
5. **RECONCILIATION** — on an updated document, the diff is field-accurate (changed detected, unchanged preserved) and changed fields are re-verified.
6. **ACCURACY** — on the labeled set (`config/answer-key.json`), every field matches ground truth after normalization. This proves the extraction is CORRECT, not merely grounded.
7. **SELF-PROVING** — `verifier.py` exits `0` on the labeled set with zero human edits.

## Optimize this score toward 1.0
```
score = field_accuracy_vs_answer_key * pct_records_schema_valid * (1 - fabrication_rate)
```
Grounding and confidence-routing are hard gates, not part of the score.

## Loop
After each run, read `verifier.py` output, fix the single largest failing gate, re-run. Do not stop until `score == 1.0` on the labeled set.

## Normalization
- Dates → ISO `YYYY-MM-DD` (documents print `MM/DD/YYYY`).
- Limits → integers (strip `$` and commas).

## Distractors — must NOT be picked
- Revision / printed / signature dates → not the true **ISSUE** date.
- Prior-carrier / quote / certificate / claim / police-report numbers → not the true **policy** number.
- Additional-insured / project-owner names → not the **certificate holder** / **insured**.
- Aggregate & sub-limits → not the **primary per-occurrence** limit. See `config/answer-key.json` `_comment` for the exact per-coverage limit mapping.
