# Self-Verifying Insurance Document Indexer

Built during the Build Day event using **Claude Code + Claude Opus 4.8**.

**What it does:** turns emailed insurance PDFs (certificates of insurance, first-notice-of-loss packets) into structured, verified records. Every field traces back to its source span, low-confidence fields route themselves to a human review queue, the index updates and re-verifies as new documents arrive, and a single config file re-targets the whole pipeline to any insurance document type.

## Original work statement
All application code in this repository (`extract.py`, `verifier.py`, `workflow.py`, and any viewer) was written from scratch **during the event**. The document corpus under `inbox/` is **synthetic and fictional** — no real client data, names, or proprietary assets are used.

## Repository layout
```
CLAUDE.md                   project guide (architecture, run, key constraints)
extract.py verifier.py workflow.py   the pipeline (built during the event)
pdftext.py normalize.py schema_util.py   shared: PDF→text, normalization, schema walk
viewer.py                   thin record viewer (source span per field + report + diff)
config/active.schema.json   active canonical schema (starts = COI)
config/coi.schema.json      Certificate of Insurance schema
config/fnol.schema.json     First Notice of Loss schema (swap to re-target)
config/answer-key.json      ground truth for accuracy grading + expected diff/review
inbox/                      source PDFs
index/                      verified records (output)
review-queue/               flagged low-confidence records (output)
.claude/goal.md             target + definition of done
.claude/verifier-rubric.md  gates the independent verifier grades against
.claude/notes.md            on-disk memory (learned extraction rules, loaded each step)
.claude/orchestration-brief.md  design brief   ·   .claude/kickoff-prompt.md  original brief
```

## Run
```bash
pip install pdfplumber jsonschema pytesseract pdf2image
# system packages: tesseract, poppler  (only needed for the one scanned PDF)

python workflow.py          # process inbox/ once: extract -> verify -> route to index/ or review-queue/
python workflow.py --watch  # or watch inbox/ continuously and index documents as they arrive
python verifier.py          # independent grader; exits 0 when DONE
python viewer.py --serve    # thin record viewer at http://localhost:8000 (source span per field, verifier report, diff)
```

The model is invoked **per document** by `workflow.py`. By default it uses the local
`claude` CLI (no API key — same login as Claude Code). To use the Anthropic API instead
(faster, fully deterministic), copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

**Re-target to a new document type with no code change:** `cp config/fnol.schema.json config/active.schema.json`, then drop that doc type into `inbox/`.

## "Done" is verifiable without a human
`verifier.py` exits `0` on the labeled held-out set: 100% grounded, 100% schema-valid, accuracy == 100%, and every low-confidence field correctly routed to `review-queue/`. Re-target to a new document type by replacing `config/active.schema.json` — no code change.
