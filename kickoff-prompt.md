# kickoff-prompt.md

Paste the block below as your **first message** in Claude Code (Opus 4.8), once the repo skeleton, `config/` files, and `inbox/` corpus are in place. Front-loading the full spec is what keeps your autonomy log clean — after this, only message the model with genuinely *new information*, never course-corrections.

---

```
You are building a self-verifying insurance document indexer in this repo, today, from
scratch. Work autonomously: drive the loop yourself, self-correct from the verifier's
output, and only stop to ask me on genuinely new information — never for course-corrections.

READ FIRST:
- goal.md            the target + definition of done (optimize to score == 1.0 on the labeled set)
- verifier-rubric.md the gates a FRESH-context verifier grades each record against
- config/coi.schema.json, config/fnol.schema.json  (config/active.schema.json starts = coi)
- config/answer-key.json  ground truth (Gate 6) + expected diff + review-queue routing
- inbox/ source PDFs; index/ and review-queue/ are outputs; notes.md is your on-disk memory

BUILD THE SPINE IN THIS ORDER (don't advance until each is verified):
1. extract.py  one PDF -> extraction envelope {value, confidence, source span, needs_review}
   keyed to config/active.schema.json. pdfplumber for the text layer; OCR (pytesseract/
   pdf2image) ONLY for image-only pages.
2. verifier.py  a fresh-context grader of verifier-rubric.md (grounding, schema via jsonschema,
   confidence routing, no-fabrication, accuracy vs answer-key). Structured pass/fail; exits 0
   only when the run passes.
3. workflow.py  a CODE-HELD loop: watch inbox/; per doc run extract -> verify -> on pass write
   index/, on low-confidence write review-queue/, on fail feed the verifier's reasons back and
   retry (max 3). Invoke the model per-document (bounded steps), checkpoint to disk, load
   notes.md each step and append a new rule whenever you fix a failure.

CHECKPOINT 1 (do this first, then stop and tell me): create a github repo, you can use the setup.sh file. steps 1-3 working end-to-end on ONE doc,
COI-1001_Harborview.pdf, passing gates 1/2/3/6. That slice is the demo floor — lock it.

THEN: run the full COI corpus; add the COI->FNOL config swap; add the update/diff path for
COI-1001_Harborview_UPDATED.pdf; confirm the scan routes itself to review-queue/. A thin viewer
(record + source span per field + verifier report + diff) is LAST, only if ahead.

WATCH THE DISTRACTORS: pick the true ISSUE date (not revision/printed/signature), the true policy
number (not prior-carrier/quote/cert/claim/police numbers), and the PRIMARY per-occurrence LIMIT
(not aggregates). answer-key.json's _comment defines the limit mapping.

DON'T add a chat-with-your-index box or a metrics dashboard centerpiece. The headline is the
ACTION: verified extraction, the diff, the config swap.

Start by reading goal.md and verifier-rubric.md, then build to Checkpoint 1.
```
