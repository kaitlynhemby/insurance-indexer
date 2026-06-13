#!/usr/bin/env python3
"""viewer.py — generate a thin, self-contained record viewer.

Renders the ACTION, not a dashboard: for every indexed / review-queue record it
shows each field's value beside its **verbatim source span** (the grounding
proof), the fresh-context verifier's gate report, and — for an updated document
— the field-level diff. Output is a single static HTML file that opens directly
(file://) or over `python -m http.server`.

  python viewer.py            # writes viewer/index.html
  python viewer.py --serve    # writes it and serves at http://localhost:8000
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import verifier as V

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "viewer", "index.html")


def _collect():
    answer_key = V._answer_key()
    active = V._active_schema()
    records = []
    paths = sorted(glob.glob(os.path.join(ROOT, "index", "*.json"))) + sorted(
        glob.glob(os.path.join(ROOT, "review-queue", "*.json"))
    )
    for p in paths:
        rec = json.load(open(p))
        rec["_report"] = V.grade_record(p, answer_key, active)
        records.append(rec)
    return records


def build_html() -> str:
    data = json.dumps(_collect(), indent=2)
    return _TEMPLATE.replace("/*DATA*/", data)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verified Insurance Index</title>
<style>
  :root{
    --paper:#f4f2ec; --card:#fffdf8; --ink:#23282c; --muted:#6b7177;
    --line:#e2ddd1; --verified:#0f6e5f; --review:#b4690e; --fail:#b3261e;
    --span:#fbf6e9; --spanline:#ead9b0; --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif;
       line-height:1.5;font-size:15px}
  header{padding:30px 32px 18px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:22px;letter-spacing:-.01em}
  header p{margin:6px 0 0;color:var(--muted);font-size:14px;max-width:70ch}
  .layout{display:flex;align-items:flex-start}
  nav{position:sticky;top:0;flex:0 0 250px;padding:22px 16px;border-right:1px solid var(--line);
      height:100vh;overflow:auto}
  nav a{display:flex;justify-content:space-between;gap:8px;align-items:center;
        text-decoration:none;color:var(--ink);padding:8px 10px;border-radius:8px;font-size:14px}
  nav a:hover{background:#0000000a}
  main{flex:1;padding:24px 32px 80px;max-width:1000px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
        padding:22px 24px;margin-bottom:26px;box-shadow:0 1px 2px #0000000a}
  .card h2{margin:0;font-size:18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .sub{color:var(--muted);font-size:13px;margin:4px 0 16px}
  .chip{font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;
        padding:3px 9px;border-radius:999px;white-space:nowrap}
  .c-indexed{background:#0f6e5f1a;color:var(--verified)}
  .c-review{background:#b4690e1a;color:var(--review)}
  .gates{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 18px}
  .gate{font-size:11px;font-family:var(--mono);padding:3px 8px;border-radius:6px;border:1px solid var(--line)}
  .g-pass{background:#0f6e5f12;color:var(--verified);border-color:#0f6e5f33}
  .g-fail{background:#b3261e12;color:var(--fail);border-color:#b3261e33}
  .g-na{background:#0000000a;color:var(--muted)}
  .field{display:grid;grid-template-columns:200px 1fr;gap:14px;padding:13px 0;border-top:1px solid var(--line)}
  .fname{font-weight:600;font-size:14px}
  .fname .rev{display:inline-block;margin-top:5px;font-weight:600;font-size:10.5px;
              color:var(--review);background:#b4690e1a;padding:2px 7px;border-radius:999px;text-transform:uppercase;letter-spacing:.03em}
  .val{font-family:var(--mono);font-size:14px;word-break:break-word}
  .val.null{color:var(--muted);font-style:italic}
  .conf{font-size:12px;color:var(--muted);margin-top:3px}
  .bar{display:inline-block;width:84px;height:5px;border-radius:3px;background:#0000000f;vertical-align:middle;margin-right:7px;overflow:hidden}
  .bar > i{display:block;height:100%;border-radius:3px}
  .span{margin-top:9px;background:var(--span);border:1px solid var(--spanline);border-left:3px solid var(--review);
        border-radius:6px;padding:8px 11px;font-family:var(--mono);font-size:12.5px;color:#5a4a25}
  .span .pg{display:block;color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
  .cov{margin:14px 0 4px;padding:14px 16px;background:#00000005;border:1px solid var(--line);border-radius:10px}
  .cov h3{margin:0 0 4px;font-size:13px;letter-spacing:.02em;text-transform:uppercase;color:var(--muted)}
  .diff{margin-top:18px;border:1px solid #b4690e44;border-radius:10px;overflow:hidden}
  .diff .dh{background:#b4690e12;color:var(--review);font-weight:600;font-size:13px;padding:9px 14px}
  .drow{display:grid;grid-template-columns:1fr auto;gap:12px;padding:10px 14px;border-top:1px solid var(--line);font-size:13px;align-items:center}
  .drow code{font-family:var(--mono);font-size:12.5px}
  .from{color:var(--fail);text-decoration:line-through}
  .to{color:var(--verified);font-weight:600}
  .reasons{margin-top:12px;font-size:12.5px;color:var(--muted)}
  .reasons li{margin:2px 0}
  footer{color:var(--muted);font-size:12px;padding:0 32px 40px;max-width:1000px}
</style>
</head>
<body>
<header>
  <h1>Verified Insurance Index</h1>
  <p>Every field traces to a verbatim source span. Low-confidence fields route themselves to the review queue. The index reconciles updated documents with a field-level diff. Graded by an independent verifier — <code>verifier.py</code> exits&nbsp;0.</p>
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"></main>
</div>
<footer id="foot"></footer>
<script>
const RECORDS = /*DATA*/;

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const isCell = v => v && typeof v === 'object' && 'value' in v && 'confidence' in v;
const confColor = c => c >= 0.85 ? 'var(--verified)' : (c >= 0.5 ? 'var(--review)' : 'var(--fail)');

function cellHTML(name, cell){
  const v = cell.value;
  const valHTML = v === null
    ? `<span class="val null">null — not asserted</span>`
    : `<span class="val">${esc(typeof v === 'number' ? v.toLocaleString('en-US') : v)}</span>`;
  const pct = Math.round((cell.confidence||0)*100);
  const conf = `<div class="conf"><span class="bar"><i style="width:${pct}%;background:${confColor(cell.confidence)}"></i></span>confidence ${cell.confidence}</div>`;
  const src = cell.source || {};
  const span = src.text_span
    ? `<div class="span"><span class="pg">source · page ${src.page}</span>“${esc(src.text_span)}”</div>` : '';
  const rev = cell.needs_review ? `<div><span class="rev">needs review</span></div>` : '';
  return `<div class="field"><div class="fname">${esc(name)}${rev}</div><div>${valHTML}${conf}${span}</div></div>`;
}

function recordHTML(rec){
  const r = rec._report, st = rec._report.status;
  const stChip = st === 'review'
    ? `<span class="chip c-review">Review queue</span>`
    : `<span class="chip c-indexed">Indexed · verified</span>`;
  const gates = Object.entries(r.gates).map(([k,v])=>{
    const cls = v==='pass'?'g-pass':(v==='fail'?'g-fail':'g-na');
    return `<span class="gate ${cls}">${k.replace('_',' ')}: ${v}</span>`;
  }).join('');

  let body = '';
  for (const [k,val] of Object.entries(rec.extraction)){
    if (isCell(val)) { body += cellHTML(k, val); continue; }
    if (Array.isArray(val)){
      val.forEach((cov,i)=>{
        const label = (cov.coverage_type && cov.coverage_type.value) || `item ${i+1}`;
        let inner = '';
        for (const [sk,sc] of Object.entries(cov)) if (isCell(sc)) inner += cellHTML(sk, sc);
        body += `<div class="cov"><h3>${esc(k)} — ${esc(label)}</h3>${inner}</div>`;
      });
    }
  }

  let diff = '';
  if (rec.diff && rec.diff.length){
    diff = `<div class="diff"><div class="dh">Reconciled vs ${esc(rec.prior_doc_id||'prior record')} — ${rec.diff.length} field(s) changed, re-verified</div>` +
      rec.diff.map(d=>`<div class="drow"><code>${esc(d.field)}</code><div><code class="from">${esc(d.from)}</code> &rarr; <code class="to">${esc(d.to)}</code></div></div>`).join('') +
      `</div>`;
  }

  let reasons = '';
  if (r.reasons && r.reasons.length){
    reasons = `<ul class="reasons">` + r.reasons.map(x=>`<li>${esc(x)}</li>`).join('') + `</ul>`;
  }

  return `<section class="card" id="${esc(rec.doc_id)}">
    <h2>${esc(rec.doc_id)} ${stChip}</h2>
    <div class="sub">${esc(rec.schema_title||'')} · source: ${esc(rec.source_pdf||'')}</div>
    <div class="gates">${gates}</div>
    ${body}${diff}${reasons}
  </section>`;
}

document.getElementById('main').innerHTML = RECORDS.map(recordHTML).join('');
document.getElementById('nav').innerHTML = RECORDS.map(rec=>{
  const cls = rec._report.status==='review'?'c-review':'c-indexed';
  const tag = rec._report.status==='review'?'review':'indexed';
  return `<a href="#${esc(rec.doc_id)}"><span>${esc(rec.doc_id)}</span><span class="chip ${cls}">${tag}</span></a>`;
}).join('');
const idx = RECORDS.filter(r=>r._report.status!=='review').length;
const rev = RECORDS.length - idx;
document.getElementById('foot').textContent =
  `${idx} indexed · ${rev} in review queue · synthetic ACORD-style corpus · built with Claude Code + Opus 4.8`;
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Generate the record viewer")
    ap.add_argument("--serve", action="store_true", help="serve at http://localhost:8000")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(build_html())
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    if args.serve:
        import http.server
        import socketserver

        os.chdir(os.path.dirname(OUT))
        with socketserver.TCPServer(("", 8000), http.server.SimpleHTTPRequestHandler) as httpd:
            print("serving at http://localhost:8000  (Ctrl-C to stop)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
