# verifier-rubric.md — Independent Verifier Spec

Run by a **fresh context** (`verifier.py`, or a fresh agent invocation) — never the same context that produced the extraction. Independent grading is what makes this a real check rather than self-critique.

For each record, emit:
```json
{ "doc_id": "...", "gates": { "...": "pass|fail" }, "pass": true, "reasons": ["..."] }
```

## Gates

**GATE 1 — Span grounding** *(binary, per field)*
For every populated field, the value (after normalization: trim, date-parse, currency-parse) must be locatable in the source OCR text, or carry a valid page+bbox. PASS only if 100% of populated fields are grounded.
*Note: grounding proves PROVENANCE, not CORRECTNESS — a value can appear in the doc and still sit in the wrong field. Gate 6 closes that gap.*

**GATE 2 — Schema conformance** *(per record)*
The `.value` layer validates against `config/active.schema.json`: required fields present, types correct, enums valid, date/currency formats valid. PASS if the JSON-Schema validator returns zero errors.

**GATE 3 — Confidence routing** *(per field)*
Every field has confidence in [0,1]. Any field < 0.85 MUST have `needs_review=true` and the record MUST be in `/review-queue`, not `/index`. FAIL if any sub-threshold field is asserted as final.

**GATE 4 — No fabrication** *(per field)*
Any field whose value cannot be grounded (Gate 1) must be `null`. FAIL if a non-null value lacks a source.

**GATE 5 — Reconciliation** *(update path only, per updated doc)*
The diff lists exactly the fields whose grounded value changed vs the prior record. Unchanged fields are byte-identical to prior. Changed fields are re-grounded. FAIL on any spurious or missed diff entry.

**GATE 6 — Accuracy vs ground truth** *(labeled set only)*
Each field matches `config/answer-key.json` after normalization. This is the ONLY gate that proves the extraction MEANING is right, and it's what makes "done" verifiable by the model at demo time without a human re-reading documents. FAIL on any mismatch.

## Run-level pass
A record passes only if every applicable gate passes. The run passes only when every record passes or is correctly in `/review-queue`, and accuracy on the labeled set == 100%. `verifier.py` exits `0` on pass, non-zero otherwise.

## Extraction envelope (what `extract.py` must emit)
```json
{
  "field_name": {
    "value": "<normalized value | null>",
    "confidence": 0.0,
    "source": { "page": 1, "text_span": "<verbatim source substring>", "bbox": [0,0,0,0] },
    "needs_review": false
  }
}
```
