# Self-Verifying Insurance Document Indexer

Built during the Build Day event using **Claude Code + Claude Opus 4.8**.

**🔗 Live record viewer:** https://viewer-puce-phi.vercel.app — the verified index, each field beside its source span, the verifier's gate report, and the reconciliation diff.

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

**Deploy the viewer** (static, no build): `viewer.py` writes a self-contained `viewer/index.html`. It's deployed to Vercel at the live URL above via `vercel deploy ./viewer --prod`. To redeploy after re-indexing: `python viewer.py` then `vercel deploy ./viewer --prod --scope <your-scope>`.

The model is invoked **per document** by `workflow.py`. By default it uses the local
`claude` CLI (no API key — same login as Claude Code). To use the Anthropic API instead
(faster, fully deterministic), copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

**Re-target to a new document type with no code change:** `cp config/fnol.schema.json config/active.schema.json`, then drop that doc type into `inbox/`.

## Configure what to collect (the schema-authoring agent)
The schema config doesn't have to be hand-written. `schema_agent.py` is an agent that **designs the config for what an insurer needs to collect**: it proposes a complete field set for a doc type, scans sample PDFs to flag salient data it isn't yet capturing, and **chats with the insurer to confirm the gaps** before applying them — then validates the schema, activates it, and re-runs the pipeline to prove it works.
```bash
# Author a NEW doc type from a description + sample PDFs (asks you about uncertain fields)
python schema_agent.py onboard "Insurance binder: insured, carrier, policy number, effective/expiration dates, coverage + limit, premium" \
    --samples samples_binder --channel console [--keep]
# Data-driven gap pass on the ACTIVE schema: "what recurring data am I missing?"
python schema_agent.py review --samples <dir-of-pdfs> --channel console
```
- It chats over a **pluggable channel** — `console` (offline default), `discord` (set `DISCORD_BOT_TOKEN`/`DISCORD_CHANNEL_ID` in `.env`), or `whatsapp` (Twilio, a documented stretch). See `.env.example`.
- It's **builder-side**: it authors `config/<DocType>.schema.json` and re-runs the existing pipeline — it never queries the index. Generated schemas are linted against the supported shape and round-tripped through the pipeline before activation (`schema_util.lint_authored_schema`); nothing is written or activated unless it passes. A freshly-authored type self-verifies on gates 1–4 (no answer-key needed). By default `onboard` restores `active=COI` and removes the sample records afterward, leaving only the new `config/*.schema.json`; `--keep` leaves it live for the viewer.

## "Done" is verifiable without a human
`verifier.py` exits `0` on the labeled held-out set: 100% grounded, 100% schema-valid, accuracy == 100%, and every low-confidence field correctly routed to `review-queue/`. Re-target to a new document type by replacing `config/active.schema.json` — no code change.
