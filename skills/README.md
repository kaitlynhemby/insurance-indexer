# skills/ — drop your agent skills here

Drop your skill files/folders into this directory. Once they're here, I'll analyze
them and map each to where it can plug into the **config-authoring agent**
(`schema_agent.py`) and the wider pipeline.

## Where a skill can attach (the agent's integration surface)
- **Draft phase** — `schema_agent._phase1_draft` / `SYSTEM_AUTHOR_DRAFT`: designing a
  new doc-type schema from a description + sample PDFs (domain knowledge about what
  insurance doc types should capture).
- **Gap detection** — `schema_agent._data_driven_gaps` / `SYSTEM_AUTHOR_GAPS`: spotting
  recurring data in samples the schema doesn't yet capture.
- **Reply interpretation** — `schema_agent._resolve_decisions` / `SYSTEM_AUTHOR_INTERPRET`:
  turning the insurer's free-text answers into confirm / rename / retype / new-field.
- **Extraction** — `extract.py` / `SYSTEM_PROMPT` + `.claude/notes.md`: per-field
  extraction rules and distractor avoidance (the on-disk memory loaded each run).
- **Channels** — `channels/`: how the agent talks to the insurer (console/Discord/WhatsApp).

Model calls all go through `extract.call_model(user, system)`; nothing uses the
`claude -p --json-schema` flag (it hangs). Generated schemas must pass
`schema_util.lint_authored_schema` before activation.
