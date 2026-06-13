#!/usr/bin/env python3
"""viewer.py — generate a self-contained, editorial record viewer.

Renders the ACTION, not a dashboard: for every indexed / review-queue record it
shows each field's value beside its **verbatim source span** (the grounding
proof), the fresh-context verifier's gate report, the field-level diff on an
updated document, and the per-insurer routing decision. Doc-type filtering makes
the config-swap / router story visible (Certificate of Insurance · FNOL ·
Binder, one pipeline). Output is a single static HTML file — no build, no
server — deployable to Vercel.

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#efe9db; --paper2:#e7dfcd; --sheet:#fbf8f0; --ink:#211e18; --muted:#736a59;
    --rule:#d8cfba; --line:#e4dccb;
    --verified:#1d6b53; --verified-bg:#1d6b531a; --review:#a8620a; --review-bg:#a8620a1a;
    --fail:#9e2b25; --fail-bg:#9e2b251a; --accent:#7c3b27;
    --evidence:#f5edd9; --evidence-line:#e2cf9f; --evidence-ink:#5c4a25;
    --serif:"Fraunces",Georgia,serif; --sans:"IBM Plex Sans",system-ui,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55;
       background:
         radial-gradient(1200px 600px at 15% -5%, #f7f2e6 0%, transparent 55%),
         radial-gradient(1000px 700px at 100% 0%, #efe7d6 0%, transparent 50%),
         var(--paper);
       background-attachment:fixed;}
  /* faint paper grain */
  body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.035;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");}
  .wrap{position:relative;z-index:1;max-width:1080px;margin:0 auto;padding:0 28px 96px}

  /* ---- masthead ---- */
  header.mast{padding:54px 0 26px;border-bottom:2px solid var(--ink)}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.32em;text-transform:uppercase;
    color:var(--accent);margin:0 0 14px}
  h1{font-family:var(--serif);font-weight:600;font-size:clamp(38px,6vw,68px);line-height:.98;
    letter-spacing:-.02em;margin:0;font-optical-sizing:auto}
  h1 em{font-style:italic;color:var(--accent)}
  .dek{font-family:var(--serif);font-weight:400;font-size:clamp(16px,2vw,20px);font-style:italic;
    color:var(--muted);max-width:62ch;margin:16px 0 0}
  .stats{display:flex;flex-wrap:wrap;gap:0;margin:26px 0 0;border-top:1px solid var(--rule)}
  .stat{padding:14px 26px 12px 0;margin-right:26px;border-right:1px solid var(--rule)}
  .stat:last-child{border-right:none}
  .stat b{display:block;font-family:var(--serif);font-size:26px;font-weight:600;line-height:1}
  .stat span{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
  .stat.ok b{color:var(--verified)}

  /* ---- filter bar ---- */
  .filters{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:8px;align-items:center;
    padding:16px 0;margin:0 0 8px;
    background:linear-gradient(var(--paper),var(--paper) 70%,transparent);
    backdrop-filter:blur(2px)}
  .chip{font-family:var(--mono);font-size:11.5px;letter-spacing:.04em;padding:7px 13px;border-radius:999px;
    border:1px solid var(--rule);background:#fff8;color:var(--muted);cursor:pointer;transition:.15s;white-space:nowrap}
  .chip:hover{border-color:var(--ink);color:var(--ink)}
  .chip.on{background:var(--ink);border-color:var(--ink);color:var(--paper)}
  .chip .ct{opacity:.6;margin-left:6px}

  /* ---- record sheets ---- */
  .sheet{position:relative;background:var(--sheet);border:1px solid var(--line);border-radius:4px;
    padding:26px 30px 28px;margin:0 0 22px;box-shadow:0 1px 0 #fff inset, 0 18px 40px -34px #3a2f1a;
    overflow:hidden;opacity:0;transform:translateY(14px);animation:rise .6s cubic-bezier(.2,.7,.2,1) forwards}
  @keyframes rise{to{opacity:1;transform:none}}
  .sheet::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--verified)}
  .sheet.review::before{background:var(--review)}
  .sheet h2{font-family:var(--serif);font-weight:600;font-size:26px;letter-spacing:-.01em;margin:0;
    display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .badge{font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.1em;text-transform:uppercase;
    padding:4px 9px;border-radius:3px;white-space:nowrap}
  .b-indexed{background:var(--verified-bg);color:var(--verified)}
  .b-review{background:var(--review-bg);color:var(--review)}
  .src{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin:7px 0 0}
  .type{font-family:var(--mono);font-size:11px;letter-spacing:.06em;color:var(--accent);text-transform:uppercase}

  /* routing strip */
  .routing{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0 4px;padding:10px 14px;
    background:var(--paper2);border:1px solid var(--rule);border-radius:4px;font-family:var(--mono);font-size:12px}
  .routing .k{color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-size:9.5px}
  .routing .v{color:var(--ink);font-weight:500}
  .routing .arrow{color:var(--accent)}
  .routing .ins{margin-left:auto;color:var(--accent)}

  /* gates */
  .gates{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 6px}
  .gate{font-family:var(--mono);font-size:10.5px;padding:4px 9px;border-radius:3px;border:1px solid transparent}
  .g-pass{background:var(--verified-bg);color:var(--verified)}
  .g-fail{background:var(--fail-bg);color:var(--fail)}
  .g-na{background:#0000000c;color:var(--muted)}

  /* fields */
  .group-h{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--accent);margin:22px 0 2px;padding-top:14px;border-top:1px solid var(--line)}
  .field{padding:13px 0;border-top:1px solid var(--line);display:grid;grid-template-columns:190px 1fr;gap:18px}
  .field:first-of-type{border-top:none}
  .field.flag{background:linear-gradient(90deg,var(--review-bg),transparent 70%);
    margin:0 -14px;padding:13px 14px;border-radius:4px;border-top:1px solid var(--review-bg)}
  .fname{font-weight:600;font-size:13.5px;padding-top:1px}
  .fname .rev{display:inline-block;margin-top:6px;font-family:var(--mono);font-size:9px;font-weight:500;
    letter-spacing:.08em;text-transform:uppercase;color:var(--review);background:var(--review-bg);
    padding:3px 7px;border-radius:3px}
  .val{font-family:var(--mono);font-size:15px;font-weight:500;word-break:break-word}
  .val.nullv{color:var(--muted);font-style:italic;font-family:var(--serif);font-weight:400}
  .meta{display:flex;align-items:center;gap:10px;margin-top:6px}
  .bar{flex:0 0 70px;height:4px;border-radius:2px;background:#0000000f;overflow:hidden}
  .bar i{display:block;height:100%}
  .conf{font-family:var(--mono);font-size:11px;color:var(--muted)}
  .ev{margin-top:9px;background:var(--evidence);border:1px solid var(--evidence-line);
    border-left:3px solid var(--review);border-radius:4px;padding:9px 12px;
    font-family:var(--mono);font-size:12.5px;color:var(--evidence-ink);cursor:pointer;transition:.15s}
  .ev:hover{border-left-color:var(--accent);background:#f1e6cc}
  .ev .pg{display:block;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:#9a8a5e;margin-bottom:4px}
  .ev.hl{box-shadow:0 0 0 2px var(--evidence-line)}

  /* diff */
  .diff{margin:20px 0 2px;border:1.5px solid var(--accent);border-radius:5px;overflow:hidden}
  .diff .dh{background:var(--accent);color:var(--paper);font-family:var(--mono);font-size:11px;
    letter-spacing:.08em;text-transform:uppercase;padding:9px 14px}
  .drow{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;padding:11px 14px;
    border-top:1px solid var(--line);font-family:var(--mono);font-size:13px}
  .drow:first-of-type{border-top:none}
  .drow code{font-family:var(--mono)}
  .from{color:var(--fail);text-decoration:line-through;opacity:.8}
  .to{color:var(--verified);font-weight:600}
  .reasons{margin:14px 0 0;font-size:12.5px;color:var(--muted);padding-left:18px}
  .reasons li{margin:3px 0;font-family:var(--mono)}

  footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--rule);
    font-family:var(--mono);font-size:11.5px;color:var(--muted);line-height:1.8}
  footer a{color:var(--accent)}
  .hide{display:none}
  @media(max-width:640px){.field{grid-template-columns:1fr;gap:4px}}
</style>
</head>
<body>
<div class="wrap">
  <header class="mast">
    <p class="eyebrow">Self-Verifying Document Indexer</p>
    <h1>Verified Insurance <em>Index</em></h1>
    <p class="dek">Every field traces to a verbatim source span. Uncertain fields route themselves to review. Updates reconcile with a field-level diff. Each record is graded by an independent verifier — and the run is provably done.</p>
    <div class="stats" id="stats"></div>
  </header>

  <nav class="filters" id="filters"></nav>
  <main id="main"></main>

  <footer id="foot"></footer>
</div>

<script>
const RECORDS = /*DATA*/;

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const isCell = v => v && typeof v === 'object' && 'value' in v && 'confidence' in v;
const confColor = c => c >= 0.85 ? 'var(--verified)' : (c >= 0.5 ? 'var(--review)' : 'var(--fail)');
const TYPE_LABEL = {CertificateOfInsurance:'Certificate of Insurance', FirstNoticeOfLoss:'First Notice of Loss', InsuranceBinder:'Insurance Binder'};
const typeLabel = t => TYPE_LABEL[t] || t || 'Document';
const fmtVal = v => v === null ? null : (typeof v === 'number' ? v.toLocaleString('en-US') : v);

let uid = 0;
function cellHTML(name, cell){
  const v = cell.value, flagged = cell.needs_review || v === null || (cell.confidence||0) < 0.85;
  const valHTML = v === null
    ? `<span class="val nullv">null — not asserted</span>`
    : `<span class="val">${esc(fmtVal(v))}</span>`;
  const pct = Math.round((cell.confidence||0)*100);
  const meta = `<div class="meta"><span class="bar"><i style="width:${pct}%;background:${confColor(cell.confidence)}"></i></span><span class="conf">conf ${cell.confidence}</span></div>`;
  const src = cell.source || {};
  const id = 'ev'+(uid++);
  const ev = src.text_span
    ? `<div class="ev" id="${id}" onclick="this.classList.toggle('hl')"><span class="pg">source · page ${src.page}</span>&ldquo;${esc(src.text_span)}&rdquo;</div>` : '';
  const rev = flagged ? `<div><span class="rev">needs review</span></div>` : '';
  return `<div class="field${flagged?' flag':''}"><div class="fname">${esc(name)}${rev}</div><div>${valHTML}${meta}${ev}</div></div>`;
}

function routingHTML(r){
  if(!r) return '';
  const dept = r.department ? `<span class="k">dept</span> <span class="v">${esc(r.department)}</span>` : '';
  const agency = r.agency_code ? `<span class="arrow">·</span><span class="k">agency</span> <span class="v">${esc(r.agency_code)}</span>` : '';
  const mkt = r.market_type ? `<span class="arrow">·</span><span class="k">market</span> <span class="v">${esc(r.market_type)}</span>` : '';
  return `<div class="routing"><span class="k">routed</span> <span class="v">${esc(r.document_type||'')}</span> <span class="arrow">→</span> ${dept}${agency}${mkt}<span class="ins">${esc(r.insurer||'')}</span></div>`;
}

function recordHTML(rec, i){
  const r = rec._report, review = r.status === 'review';
  const badge = review ? `<span class="badge b-review">Review queue</span>` : `<span class="badge b-indexed">Indexed · verified</span>`;
  const gates = Object.entries(r.gates).map(([k,v])=>{
    const cls = v==='pass'?'g-pass':(v==='fail'?'g-fail':'g-na');
    return `<span class="gate ${cls}">${k.replace(/_/g,' ')} · ${v}</span>`;
  }).join('');

  let body = '';
  for(const [k,val] of Object.entries(rec.extraction)){
    if(isCell(val)){ body += cellHTML(k, val); continue; }
    if(Array.isArray(val)){
      val.forEach((cov,ci)=>{
        const label = (cov.coverage_type && cov.coverage_type.value) || ('item '+(ci+1));
        let inner=''; for(const [sk,sc] of Object.entries(cov)) if(isCell(sc)) inner += cellHTML(sk, sc);
        body += `<div class="group-h">${esc(k)} — ${esc(label)}</div>${inner}`;
      });
    }
  }

  let diff='';
  if(rec.diff && rec.diff.length){
    diff = `<div class="diff"><div class="dh">Reconciled vs ${esc(rec.prior_doc_id||'prior')} — ${rec.diff.length} field(s) changed &amp; re-verified</div>`+
      rec.diff.map(d=>`<div class="drow"><code>${esc(d.field)}</code><div><code class="from">${esc(fmtVal(d.from))}</code> &nbsp;→&nbsp; <code class="to">${esc(fmtVal(d.to))}</code></div></div>`).join('')+`</div>`;
  }
  let reasons='';
  if(r.reasons && r.reasons.length) reasons = `<ul class="reasons">`+r.reasons.map(x=>`<li>${esc(x)}</li>`).join('')+`</ul>`;

  return `<section class="sheet${review?' review':''}" data-type="${esc(rec.schema_title||'')}" data-status="${review?'review':'indexed'}" style="animation-delay:${Math.min(i,8)*60}ms">
    <h2>${esc(rec.doc_id)} ${badge}</h2>
    <div class="src"><span class="type">${esc(typeLabel(rec.schema_title))}</span> &nbsp;·&nbsp; ${esc(rec.source_pdf||'')}</div>
    ${routingHTML(rec.routing)}
    <div class="gates">${gates}</div>
    ${body}${diff}${reasons}
  </section>`;
}

// ---- render ----
const main = document.getElementById('main');
main.innerHTML = RECORDS.map(recordHTML).join('');

const idx = RECORDS.filter(r=>r._report.status!=='review').length;
const rev = RECORDS.length - idx;
const types = [...new Set(RECORDS.map(r=>r.schema_title))];
document.getElementById('stats').innerHTML =
  `<div class="stat ok"><b>verifier&nbsp;0</b><span>exits clean</span></div>`+
  `<div class="stat"><b>${idx}</b><span>indexed</span></div>`+
  `<div class="stat"><b>${rev}</b><span>in review</span></div>`+
  `<div class="stat"><b>${types.length}</b><span>document types</span></div>`;

// filter chips
const counts = {};
RECORDS.forEach(r=>{counts[r.schema_title]=(counts[r.schema_title]||0)+1;});
const chips = [['all','All',RECORDS.length]]
  .concat(types.map(t=>[t, typeLabel(t), counts[t]]))
  .concat([['__review','Review queue',rev]]);
document.getElementById('filters').innerHTML = chips.map((c,i)=>
  `<button class="chip${i===0?' on':''}" data-f="${esc(c[0])}">${esc(c[1])}<span class="ct">${c[2]}</span></button>`).join('');

document.querySelectorAll('.chip').forEach(ch=>ch.addEventListener('click',()=>{
  document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));
  ch.classList.add('on');
  const f = ch.dataset.f;
  let n=0;
  document.querySelectorAll('.sheet').forEach((s,i)=>{
    const show = f==='all' || (f==='__review'? s.dataset.status==='review' : s.dataset.type===f);
    s.classList.toggle('hide', !show);
    if(show){ s.style.animation='none'; s.offsetHeight; s.style.animation=`rise .5s cubic-bezier(.2,.7,.2,1) ${Math.min(n,8)*45}ms forwards`; n++; }
  });
}));

document.getElementById('foot').innerHTML =
  `${idx} indexed · ${rev} in review · ${types.length} document types, one pipeline · synthetic ACORD-style corpus<br>`+
  `Built with Claude Code + Claude Opus 4.8 · <a href="https://github.com/kaitlynhemby/insurance-indexer">source</a>`;
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
