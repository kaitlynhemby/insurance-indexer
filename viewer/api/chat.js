// api/chat.js — Vercel serverless endpoint for the config-authoring agent chat.
//
// This is the insurer <-> CONFIG AGENT conversation only: the agent helps an
// insurance company define what to collect for a document type (propose a field
// set, ask about uncertain fields, show the schema it assembles). It is NOT a
// "chat with your index" / RAG box — it never answers questions about stored or
// indexed data and has no access to records. The Anthropic API key lives in the
// Vercel server env (ANTHROPIC_API_KEY) and is never exposed to the browser.

const SYSTEM = [
  "You are the CONFIGURATION AGENT for a self-verifying insurance document indexer.",
  "Your one job: help an insurance company define WHAT TO COLLECT from a type of document, by",
  "authoring a config schema for it through conversation.",
  "",
  "What you do:",
  "- Ask what document type they want to process (e.g. ACORD 125 commercial app, a binder, a loss run).",
  "- Propose a concise field set with types: dates as ISO date, money/limits as integers, short",
  "  enums where natural, and at most ONE repeating group (e.g. a coverages/locations list).",
  "- Proactively flag fields they might be missing (e.g. retroactive date for a claims-made policy),",
  "  and ask yes/no so THEY decide. Honor renames ('call it effective_date') and type changes.",
  "- When they confirm, summarize the finalized schema as a short field list (name — type), and note",
  "  that dropping it into config/<DocType>.schema.json re-targets the whole pipeline with no code change.",
  "",
  "Hard rules:",
  "- You ONLY author configuration. You do NOT answer questions about already-indexed documents, you do",
  "  NOT retrieve or summarize stored data, and you have no database. If asked, say that's the indexer/",
  "  viewer's job and steer back to defining the schema.",
  "- Be concise and conversational (a few sentences per turn). One focused question at a time.",
  "- Every field an insurer's documents vary on is configurable — emphasize this flexibility when relevant.",
].join("\n");

module.exports = async (req, res) => {
  res.setHeader("content-type", "application/json");
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) {
    res.status(500).json({ error: "Server is not configured for chat yet." });
    return;
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  const raw = Array.isArray(body && body.messages) ? body.messages : [];

  // Guards: cap turns + per-message size (public endpoint that calls the model).
  if (raw.length > 30) {
    res.status(400).json({ error: "This conversation is long — please restart to keep the demo snappy." });
    return;
  }
  let messages = raw
    .slice(-30)
    .map((m) => ({
      role: m && m.role === "assistant" ? "assistant" : "user",
      content: String((m && m.content) || "").slice(0, 2000),
    }))
    .filter((m) => m.content.trim());
  // The Messages API requires the first message to be from the user.
  while (messages.length && messages[0].role !== "user") messages.shift();
  if (!messages.length) {
    res.status(400).json({ error: "Say something to start." });
    return;
  }

  try {
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-opus-4-8",
        max_tokens: 1024,
        system: SYSTEM,
        messages,
      }),
    });
    if (!r.ok) {
      const detail = (await r.text()).slice(0, 300);
      res.status(502).json({ error: "The model is unavailable right now.", detail });
      return;
    }
    const data = await r.json();
    const reply = (data.content || [])
      .filter((b) => b.type === "text")
      .map((b) => b.text)
      .join("")
      .trim();
    res.status(200).json({ reply: reply || "(no response)" });
  } catch (e) {
    res.status(502).json({ error: "Could not reach the model service." });
  }
};
