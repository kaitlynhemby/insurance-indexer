#!/usr/bin/env bash
# setup.sh — stand up the insurance-indexer repo skeleton in one command.
#
# Expected layout when you run this (download everything into one folder):
#   ./setup.sh
#   ./repo-starter/   (goal.md, verifier-rubric.md, notes.md, README.md, kickoff-prompt.md)
#   ./corpus/         (the 7 PDFs + answer-key.json)
#
# Usage:
#   ./setup.sh                          # local repo only (git init + commit)
#   ./setup.sh --name my-indexer        # custom project folder name
#   ./setup.sh --github my-indexer      # ALSO create + push a PUBLIC GitHub repo (needs `gh auth login`)
#   ./setup.sh --starter ./repo-starter --corpus ./corpus   # custom source paths
#
set -euo pipefail

PROJECT="insurance-indexer"
STARTER_DIR="./repo-starter"
CORPUS_DIR="./corpus"
GITHUB_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)    PROJECT="$2"; shift 2;;
    --starter) STARTER_DIR="$2"; shift 2;;
    --corpus)  CORPUS_DIR="$2"; shift 2;;
    --github)  GITHUB_NAME="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

echo "==> 1/6  Creating repo: $PROJECT"
mkdir -p "$PROJECT"
cd "$PROJECT"
if [[ ! -d .git ]]; then git init -q; fi
cat > .gitignore <<'GI'
__pycache__/
*.pyc
.env
.venv/
.DS_Store
GI

echo "==> 2/6  Folder structure"
mkdir -p config inbox index review-queue
touch index/.gitkeep review-queue/.gitkeep

echo "==> 3/6  Canonical schemas (config/)"
cat > config/coi.schema.json <<'JSON'
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
JSON

cat > config/fnol.schema.json <<'JSON'
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
JSON

cp config/coi.schema.json config/active.schema.json
echo "    active.schema.json = coi (swap to fnol.schema.json for the config-swap beat)"

echo "==> 4/6  Markdown specs + corpus"
S="../$STARTER_DIR"; [[ -d "$STARTER_DIR" ]] && S="$STARTER_DIR" || S="../${STARTER_DIR#./}"
C="../$CORPUS_DIR";  [[ -d "$CORPUS_DIR"  ]] && C="$CORPUS_DIR"  || C="../${CORPUS_DIR#./}"

copy_md() {
  local src="$1"
  for f in goal.md verifier-rubric.md notes.md README.md kickoff-prompt.md; do
    if [[ -f "$src/$f" ]]; then cp "$src/$f" "./$f"; else echo "    WARN: missing $src/$f"; fi
  done
}
if [[ -d "$S" ]]; then copy_md "$S"; else echo "    WARN: starter dir not found ($STARTER_DIR) — copy the 5 .md files in manually"; fi

if [[ -d "$C" ]]; then
  cp "$C"/*.pdf inbox/ 2>/dev/null && echo "    copied PDFs -> inbox/" || echo "    WARN: no PDFs in $CORPUS_DIR"
  if [[ -f "$C/answer-key.json" ]]; then cp "$C/answer-key.json" config/; else echo "    WARN: missing answer-key.json"; fi
  [[ -f "$C/README.md" ]] && cp "$C/README.md" inbox/README-corpus.md || true
else
  echo "    WARN: corpus dir not found ($CORPUS_DIR) — copy PDFs into inbox/ and answer-key.json into config/ manually"
fi

echo "==> 5/6  Initial commit"
git add -A
git -c user.email=you@example.com -c user.name="Build Day" commit -q -m "scaffold: specs, schemas, corpus (no app code yet)" || echo "    (nothing to commit)"

echo "==> 6/6  GitHub (public repo required by the rules)"
if [[ -n "$GITHUB_NAME" ]]; then
  if command -v gh >/dev/null 2>&1; then
    echo "    Creating PUBLIC repo '$GITHUB_NAME' and pushing (uses your gh auth)..."
    gh repo create "$GITHUB_NAME" --public --source=. --push
  else
    echo "    'gh' not found. Install GitHub CLI or run manually:"
    echo "      git remote add origin https://github.com/<you>/$GITHUB_NAME.git"
    echo "      git branch -M main && git push -u origin main"
  fi
else
  echo "    Skipped (local only). To publish later:  gh auth login  then re-run with --github <name>"
fi

echo ""
echo "Done. Repo ready at: $(pwd)"
echo "Tree:"; find . -maxdepth 2 -not -path '*/.git/*' | sed 's|^\./||' | sort | sed 's|^|  |'
echo ""
echo "Next: open this folder in Claude Code (model = Opus 4.8), then paste kickoff-prompt.md as your first message."
