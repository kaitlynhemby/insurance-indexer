# notes.md — On-disk Memory (the outer loop)

Persistent, file-based memory so the loop re-derives nothing and survives restarts. **Load this at the start of every per-document step. Append a new rule whenever you investigate and fix a failure** (fail → investigate → verify → distill). Keep rules short, specific, and general enough to apply beyond one document. Refine rules; don't delete them.

## General / cross-document
- Dates print `MM/DD/YYYY`; normalize to ISO `YYYY-MM-DD`.
- `limit` = the PRIMARY per-occurrence limit only (see `config/answer-key.json` `_comment` for the per-coverage mapping).
- Ignore the distractors listed in `goal.md` (revision/printed/signature dates, prior-carrier/quote/cert/claim/police numbers, additional-insured names, aggregate sub-limits).

## Certificate of Insurance (COI)
- `issue_date` = the header `DATE ISSUED (MM/DD/YYYY)` value ONLY. Not `REVISION DATE`, not `FORM PRINTED`, not the page-2 signature `Date:` (they often share or nearly share the value — don't be fooled).
- `policy_number` / `effective_date` / `expiration_date` come from each coverage's `POLICY NUMBER` / `POLICY EFF` / `POLICY EXP` row. NOT `CERTIFICATE NUMBER` (CRT-…), `MASTER QUOTE REF` (Q-…), `NAIC #`, `REVISION`, or a prior-carrier policy named in the Description of Operations (e.g. "Prior carrier: … policy EI-99001").
- `limit` = PRIMARY per-occurrence only: GL & Umbrella → `Each Occurrence`; Auto → `Combined Single Limit`; Workers Comp → `E.L. Each Accident`; Professional/E&O → `Each Claim`. NEVER `General Aggregate`, `Products - Comp/Op Agg`, `Aggregate`, `Damage to Rented Premises`, `Med Exp`, or any disease/sub-limit.
- `insured_name` = the `INSURED` block (top); `certificate_holder` = the page-2 `CERTIFICATE HOLDER` block. NOT additional-insured / project-owner names from the Description of Operations or remarks.
- `coverage_type` mapping: `COMMERCIAL GENERAL LIABILITY`→general_liability, `AUTOMOBILE LIABILITY`→auto_liability, `UMBRELLA / EXCESS LIAB`→umbrella, `WORKERS COMPENSATION AND EMPLOYERS' LIABILITY`→workers_comp, `PROFESSIONAL LIABILITY (E&O)`→professional_liability.
- A born-digital COI's header + coverage rows are crisp text: assign high confidence (≥0.95). Reserve low confidence for genuinely garbled (OCR'd) cells.

## First Notice of Loss (FNOL)
- `policy_number` = `Policy Number: POL-…`. NOT `Claim Number (internal)` (CLM-…) and NOT `Police Report #` (WSP-…).
- `reported_by` = the `Reported By` / intake contact (e.g. Fleet Manager, Site Supervisor). NOT the `Assigned Adjuster`.
- `loss_type` enum from `Type of Loss`: "Auto - Collision"→auto, "Property - Water Damage"→property, liability→liability, workers_comp→workers_comp, else→other.
- `claimant_name` verbatim, including "N/A (first-party)" when the loss is first-party.
- `estimated_severity` = the `Estimated Severity` word, lowercased (low/medium/high/unknown).
- `loss_description` = the full DESCRIPTION OF LOSS / NARRATIVE paragraph, verbatim (whitespace will be normalized for grounding).
