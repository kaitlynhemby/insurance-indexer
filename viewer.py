#!/usr/bin/env python3
"""viewer.py — generate the self-contained demo console (static + one function).

The story end to end, on one page:
  INBOX  — synthetic emails arrive with PDF attachments (fakes the email layer)
  RECORD — open an email → the pipeline runs → a verified record, every field
           beside its verbatim source span; click a field to see it highlighted
           in the actual source PDF (PDF.js)
  CONFIGURE — chat with the config agent to define what to collect for any
           insurer (live, via /api/chat — a Vercel serverless function)

Output: viewer/index.html (records + emails embedded), viewer/pdfs/* (bundled
sources), viewer/api/chat.js (the chat function). Deployable to Vercel as-is.

  python viewer.py            # generate
  python viewer.py --serve    # generate + serve at http://localhost:8000
                              #   (chat needs the deployed function; local = inbox/record/PDF only)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil

import schema_util as S
import verifier as V

ROOT = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(ROOT, "viewer")
OUT = os.path.join(VIEWER, "index.html")
PDF_DIR = os.path.join(VIEWER, "pdfs")

# Synthetic sender directory (producer/agency -> email), so emails look real.
_SENDER_EMAIL = {
    "Brightline Insurance Brokers": "certs@brightline.example",
    "Anchor Risk Partners": "submissions@anchorrisk.example",
}


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


def _values(rec):
    schema = V._schemas_by_title().get(rec.get("schema_title")) or V._active_schema()
    try:
        return S.value_layer(rec.get("extraction", {}), schema)
    except Exception:
        return {}


def _money(x):
    return f"${x:,.0f}" if isinstance(x, (int, float)) else (str(x) if x else "")


def _coverage_summary(v):
    parts = []
    for c in (v.get("coverages") or []):
        ct = (c.get("coverage_type") or "").replace("_", " ")
        lim = _money(c.get("limit"))
        if ct:
            parts.append((ct + (f" {lim}" if lim else "")).strip())
    return "; ".join(parts)


def _emails(records):
    """Synthesize a plausible inbound email per record — subject + body carry real
    detail (the way real submission/claims emails do), fakes the email layer."""
    times = ["08:51", "09:03", "09:17", "09:32", "09:46", "10:08", "10:21", "10:39", "10:55"]
    out = []
    for i, rec in enumerate(records):
        v = _values(rec)
        title = rec.get("schema_title")
        attach = os.path.basename(rec.get("source_pdf", rec["doc_id"] + ".pdf"))
        if title == "FirstNoticeOfLoss":
            who = v.get("policyholder_name") or "Policyholder"
            sender, email = who, "claims-intake@harborview.example"
            lt = (v.get("loss_type") or "").replace("_", " ")
            subject = f"FNOL — {who} · {lt} loss {v.get('loss_date','')}".strip()
            body = (f"Reporting a new {lt or 'loss'} for {who} on policy {v.get('policy_number','—')}. "
                    f"Date of loss {v.get('loss_date','—')} at {v.get('loss_location','—')}. "
                    f"Reported by {v.get('reported_by','the insured')}. Estimated severity "
                    f"{v.get('estimated_severity','—')}. Full packet attached — please set up the claim.")
        elif title == "InsuranceBinder":
            who = v.get("producing_agency") or "Insurance Brokers"
            email = _SENDER_EMAIL.get(who, "submissions@broker.example")
            sender = who
            insured = v.get("insured_name") or "the insured"
            lob = (v.get("coverage_type") or "coverage").replace("_", " ")
            subject = f"Bind request — {insured} ({lob}, eff {v.get('binder_effective_date','')})".strip()
            body = (f"Please bind the attached for {insured}: {lob}, "
                    f"{_money(v.get('coverage_limit'))} per occurrence / each claim, carrier "
                    f"{v.get('insurer_name','—')}. Binder {v.get('binder_number','—')} effective "
                    f"{v.get('binder_effective_date','—')} through {v.get('binder_expiration_date','—')}. "
                    f"Estimated premium {_money(v.get('estimated_premium'))}. Confirm and issue.")
        else:  # COI
            who = v.get("producer") or v.get("producing_agency") or "Insurance Brokers"
            email = _SENDER_EMAIL.get(who, "submissions@broker.example")
            sender = who
            insured = v.get("insured_name") or "the insured"
            holder = v.get("certificate_holder")
            subject = f"Certificate of insurance — {insured}" + (f" for {holder}" if holder else "")
            cov = _coverage_summary(v)
            body = (f"Attached is the certificate of insurance for {insured}"
                    + (f", naming {holder} as certificate holder" if holder else "") + ". "
                    + (f"Coverages: {cov}. " if cov else "")
                    + f"Issued {v.get('issue_date','—')}. Let us know if anything else is required.")
        out.append({
            "from_name": sender, "from_email": email, "subject": subject,
            "preview": body, "body": body, "time": times[i % len(times)],
            "attachment": attach, "doc_id": rec["doc_id"],
        })
    return out


def _copy_pdfs(records):
    os.makedirs(PDF_DIR, exist_ok=True)
    for rec in records:
        src = os.path.join(ROOT, rec.get("source_pdf", ""))
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(PDF_DIR, os.path.basename(src)))


def build_html():
    records = _collect()
    _copy_pdfs(records)
    emails = _emails(records)
    data = json.dumps({"records": records, "emails": emails}, indent=2)
    return _TEMPLATE.replace("/*DATA*/", data)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verified Insurance Index — live demo</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%237c3b27'/%3E%3Cpath d='M9 16.5l4.5 4.5L23 11' stroke='%23efe9db' stroke-width='3' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<meta name="description" content="Emailed insurance PDFs, indexed and proven — every field traces to its source span, verified, and configurable for any insurer.">
<meta property="og:title" content="Verified Insurance Index — live demo">
<meta property="og:description" content="Emailed insurance PDFs → verified records with source proof, self-routing review, and a config agent that re-targets the pipeline to any insurer.">
<meta name="twitter:card" content="summary">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,400;1,9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js" integrity="sha512-q+4liFwdPC/bNdhUpZx6aXDx/h77yEQtn4I1slHydcbZK34nLaR3cAeYSJshoxIOq3mjEf7xJE8YWIUHMn+oCQ==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>
  :root{
    --paper:#efe9db; --paper2:#e7dfcd; --sheet:#fbf8f0; --ink:#211e18; --muted:#736a59;
    --rule:#d8cfba; --line:#e7dfcb;
    --verified:#1d6b53; --verified-bg:#1d6b531a; --review:#a8620a; --review-bg:#a8620a14;
    --fail:#9e2b25; --fail-bg:#9e2b251a; --accent:#7c3b27;
    --evidence:#f5edd9; --evidence-line:#e2cf9f; --evidence-ink:#5c4a25; --hl:#ffd86b88;
    --serif:"Fraunces",Georgia,serif; --sans:"IBM Plex Sans",system-ui,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;color:var(--ink);font-family:var(--sans);font-size:14.5px;line-height:1.5;
    background:radial-gradient(1100px 560px at 12% -8%,#f7f2e6 0,transparent 55%),
      radial-gradient(900px 640px at 100% 0,#efe7d6 0,transparent 50%),var(--paper);
    background-attachment:fixed;}
  body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.03;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");}
  .wrap{position:relative;z-index:1;max-width:1240px;margin:0 auto;padding:0 26px 80px}
  a{color:var(--accent)}

  header.mast{padding:44px 0 18px}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--accent);margin:0 0 12px}
  h1{font-family:var(--serif);font-weight:600;font-size:clamp(34px,5.4vw,60px);line-height:1;letter-spacing:-.02em;margin:0}
  h1 em{font-style:italic;color:var(--accent)}
  .dek{font-family:var(--serif);font-style:italic;font-size:clamp(15px,1.7vw,19px);color:var(--muted);max-width:70ch;margin:14px 0 0}

  /* how-it-works ribbon */
  .steps{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin:26px 0 6px;border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--sheet)}
  .step{padding:14px 16px;border-right:1px solid var(--line)}
  .step:last-child{border-right:none}
  .step b{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
  .step p{margin:5px 0 0;font-size:13px;color:var(--ink)}
  .step.flex{background:var(--paper2)}

  /* console */
  .console{display:grid;grid-template-columns:380px 1fr;gap:22px;margin-top:26px;align-items:start}
  @media(max-width:900px){.console{grid-template-columns:1fr}}

  .panel{background:var(--sheet);border:1px solid var(--line);border-radius:8px;box-shadow:0 18px 44px -38px #3a2f1a}
  .panel-h{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line)}
  .panel-h .dot{width:8px;height:8px;border-radius:50%;background:var(--verified)}
  .panel-h h2{font-family:var(--serif);font-size:18px;font-weight:600;margin:0}
  .panel-h .count{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted)}

  .filters{display:flex;flex-wrap:wrap;gap:6px;padding:11px 14px;border-bottom:1px solid var(--line)}
  .chip{font-family:var(--mono);font-size:11px;padding:5px 10px;border-radius:999px;border:1px solid var(--rule);background:#fff8;color:var(--muted);cursor:pointer;transition:.15s}
  .chip:hover{border-color:var(--ink);color:var(--ink)}
  .chip.on{background:var(--ink);border-color:var(--ink);color:var(--paper)}
  .chip .ct{opacity:.6;margin-left:5px}

  .inbox{max-height:72vh;overflow:auto}
  .email{display:block;width:100%;text-align:left;border:none;background:none;border-bottom:1px solid var(--line);
    padding:14px 16px;cursor:pointer;transition:.12s;position:relative}
  .email:hover{background:#fff6}
  .email.sel{background:var(--paper2)}
  .email.sel::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
  .email .top{display:flex;align-items:baseline;gap:8px}
  .email .from{font-weight:600;font-size:13.5px}
  .email .time{margin-left:auto;font-family:var(--mono);font-size:10.5px;color:var(--muted)}
  .email .subj{font-size:13px;margin:3px 0 0}
  .email .att{display:inline-flex;align-items:center;gap:5px;margin-top:7px;font-family:var(--mono);font-size:10.5px;color:var(--accent);background:var(--evidence);border:1px solid var(--evidence-line);border-radius:4px;padding:2px 7px}
  .email .pill{position:absolute;right:14px;bottom:14px;font-family:var(--mono);font-size:9px;letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;border-radius:3px}
  .pill.indexed{background:var(--verified-bg);color:var(--verified)} .pill.review{background:var(--review-bg);color:var(--review)}

  /* stage */
  .stage{min-height:60vh}
  .empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:60vh;text-align:center;color:var(--muted)}
  .empty .big{font-family:var(--serif);font-style:italic;font-size:24px;color:var(--ink);margin-bottom:8px}

  .emailcard{margin:18px 22px 0;padding:14px 16px;background:var(--paper2);border:1px solid var(--rule);border-radius:8px}
  .ec-row{display:flex;gap:10px;align-items:baseline;font-size:13px;margin-bottom:4px}
  .ec-k{font-family:var(--mono);font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);min-width:52px}
  .ec-time{margin-left:auto;font-family:var(--mono);font-size:10.5px;color:var(--muted)}
  .ec-subj{font-family:var(--serif);font-size:15px}
  .ec-body{font-size:13px;color:var(--ink);margin:8px 0 10px;line-height:1.5}
  .ec-att{font-family:var(--mono);font-size:11px;color:var(--accent);background:var(--evidence);border:1px solid var(--evidence-line);border-radius:4px;padding:4px 9px;display:inline-flex;align-items:center;gap:8px}
  .ec-pill{font-size:9px;letter-spacing:.06em;text-transform:uppercase}
  .ec-pill.indexed{color:var(--verified)} .ec-pill.review{color:var(--review)}
  .run{padding:24px 28px}
  .run .step-line{display:flex;align-items:center;gap:12px;padding:11px 0;opacity:.3;transition:.3s;font-family:var(--mono);font-size:13px}
  .run .step-line.on{opacity:1}
  .run .step-line .tick{width:18px;height:18px;border-radius:50%;border:2px solid var(--rule);display:grid;place-items:center;flex:0 0 auto}
  .run .step-line.done .tick{background:var(--verified);border-color:var(--verified);color:#fff}

  .sheet{position:relative;padding:24px 28px 26px;opacity:0;animation:rise .5s cubic-bezier(.2,.7,.2,1) forwards}
  @keyframes rise{to{opacity:1}}
  .sheet h2.rec{font-family:var(--serif);font-weight:600;font-size:25px;margin:0;display:flex;gap:11px;align-items:baseline;flex-wrap:wrap}
  .badge{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:4px 9px;border-radius:3px}
  .b-indexed{background:var(--verified-bg);color:var(--verified)} .b-review{background:var(--review-bg);color:var(--review)}
  .src{font-family:var(--mono);font-size:11px;color:var(--muted);margin:6px 0 0}
  .type{color:var(--accent);text-transform:uppercase;letter-spacing:.06em}
  .routing{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:15px 0 4px;padding:9px 13px;background:var(--paper2);border:1px solid var(--rule);border-radius:5px;font-family:var(--mono);font-size:11.5px}
  .routing .k{color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-size:9px} .routing .v{font-weight:500} .routing .arrow{color:var(--accent)} .routing .ins{margin-left:auto;color:var(--accent)}
  .gates{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 4px}
  .gate{font-family:var(--mono);font-size:10px;padding:4px 8px;border-radius:3px}
  .g-pass{background:var(--verified-bg);color:var(--verified)} .g-fail{background:var(--fail-bg);color:var(--fail)} .g-na{background:#0000000c;color:var(--muted)}
  .group-h{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:20px 0 2px;padding-top:13px;border-top:1px solid var(--line)}
  .field{padding:12px 0;border-top:1px solid var(--line);display:grid;grid-template-columns:175px 1fr;gap:16px}
  .field:first-of-type{border-top:none}
  .field.flag{background:linear-gradient(90deg,var(--review-bg),transparent 72%);margin:0 -12px;padding:12px;border-radius:5px}
  .fname{font-weight:600;font-size:13px}
  .fname .rev{display:inline-block;margin-top:6px;font-family:var(--mono);font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:var(--review);background:var(--review-bg);padding:3px 7px;border-radius:3px}
  .val{font-family:var(--mono);font-size:14.5px;font-weight:500;word-break:break-word}
  .val.nullv{font-family:var(--serif);font-style:italic;font-weight:400;color:var(--muted)}
  .meta{display:flex;align-items:center;gap:9px;margin-top:5px}
  .bar{flex:0 0 64px;height:4px;border-radius:2px;background:#0000000f;overflow:hidden} .bar i{display:block;height:100%}
  .conf{font-family:var(--mono);font-size:10.5px;color:var(--muted)}
  .ev{margin-top:8px;background:var(--evidence);border:1px solid var(--evidence-line);border-left:3px solid var(--review);border-radius:5px;padding:8px 11px;font-family:var(--mono);font-size:12px;color:var(--evidence-ink);cursor:pointer;transition:.13s}
  .ev:hover{border-left-color:var(--accent);background:#f1e6cc}
  .ev .pg{display:flex;justify-content:space-between;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:#9a8a5e;margin-bottom:4px}
  .ev .see{color:var(--accent)}
  .diff{margin:18px 0 2px;border:1.5px solid var(--accent);border-radius:6px;overflow:hidden}
  .diff .dh{background:var(--accent);color:var(--paper);font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding:9px 13px}
  .drow{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:10px 13px;border-top:1px solid var(--line);font-family:var(--mono);font-size:12.5px}
  .from-v{color:var(--fail);text-decoration:line-through;opacity:.8} .to-v{color:var(--verified);font-weight:600}
  .reasons{margin:13px 0 0;padding-left:16px;font-family:var(--mono);font-size:12px;color:var(--muted)}

  /* configure FAB + chat */
  .fab{position:fixed;right:22px;bottom:22px;z-index:30;font-family:var(--sans);font-weight:600;font-size:14px;
    background:var(--accent);color:#fff;border:none;border-radius:999px;padding:14px 20px;cursor:pointer;
    box-shadow:0 10px 30px -8px #7c3b2799;display:flex;align-items:center;gap:9px;transition:.15s}
  .fab:hover{transform:translateY(-2px)}
  .drawer{position:fixed;right:0;top:0;bottom:0;width:min(440px,94vw);z-index:40;background:var(--sheet);
    border-left:1px solid var(--rule);box-shadow:-24px 0 60px -30px #3a2f1a;display:flex;flex-direction:column;
    transform:translateX(100%);transition:transform .28s cubic-bezier(.2,.7,.2,1)}
  .drawer.open{transform:none}
  .drawer-h{padding:18px 20px;border-bottom:1px solid var(--line)}
  .drawer-h h3{font-family:var(--serif);font-size:20px;font-weight:600;margin:0}
  .drawer-h p{margin:5px 0 0;font-size:12.5px;color:var(--muted)}
  .drawer-h .x{position:absolute;right:16px;top:16px;border:none;background:none;font-size:22px;cursor:pointer;color:var(--muted);line-height:1}
  .msgs{flex:1;overflow:auto;padding:18px 20px;display:flex;flex-direction:column;gap:12px}
  .msg{max-width:88%;padding:10px 13px;border-radius:12px;font-size:13.5px;line-height:1.5;white-space:pre-wrap}
  .msg.user{align-self:flex-end;background:var(--accent);color:#fff;border-bottom-right-radius:3px}
  .msg.bot{align-self:flex-start;background:var(--paper2);border:1px solid var(--rule);border-bottom-left-radius:3px}
  .msg.bot.think{color:var(--muted);font-style:italic}
  .composer{display:flex;gap:8px;padding:14px 16px;border-top:1px solid var(--line)}
  .composer input{flex:1;font-family:var(--sans);font-size:13.5px;padding:10px 12px;border:1px solid var(--rule);border-radius:8px;background:#fff;color:var(--ink)}
  .composer button{font-family:var(--sans);font-weight:600;border:none;background:var(--accent);color:#fff;border-radius:8px;padding:0 16px;cursor:pointer}
  .composer button:disabled{opacity:.5;cursor:default}
  .seed{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 12px}
  .seed button{font-family:var(--mono);font-size:11px;border:1px dashed var(--rule);background:none;color:var(--accent);border-radius:6px;padding:6px 9px;cursor:pointer;text-align:left}

  /* pdf modal */
  .modal{position:fixed;inset:0;z-index:50;background:#211e18cc;display:none;align-items:center;justify-content:center;padding:24px}
  .modal.open{display:flex}
  .modal-card{background:var(--sheet);border-radius:8px;max-width:880px;width:100%;max-height:92vh;display:flex;flex-direction:column;overflow:hidden}
  .modal-h{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)}
  .modal-h h3{font-family:var(--serif);font-size:17px;margin:0}
  .modal-h .sub{font-family:var(--mono);font-size:11px;color:var(--muted)}
  .modal-h .x{margin-left:auto;border:none;background:none;font-size:22px;cursor:pointer;color:var(--muted)}
  .pdf-scroll{overflow:auto;padding:18px;background:var(--paper2)}
  .pdf-stage{position:relative;margin:0 auto;width:max-content;box-shadow:0 8px 30px -10px #0006;background:#fff}
  .pdf-stage canvas{display:block}
  .hllayer{position:absolute;inset:0;pointer-events:none}
  .hlbox{position:absolute;background:var(--hl);border-radius:2px;mix-blend-mode:multiply}
  .modal-note{padding:10px 18px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11.5px;color:var(--evidence-ink);background:var(--evidence)}

  footer{margin-top:34px;padding-top:18px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:11px;color:var(--muted);line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <header class="mast">
    <p class="eyebrow">Self-Verifying Document Indexer · live demo</p>
    <h1>Emailed insurance PDFs, <em>indexed &amp; proven</em></h1>
    <p class="dek">Insurance teams hand-key emailed certificates, binders, and claims for weeks. Here the email arrives, every field is extracted with its source proof, anything uncertain routes itself to review — and one config file, authored by chatting with the agent, re-targets the whole pipeline to any insurer's documents.</p>
    <div class="steps">
      <div class="step"><b>1 · Email arrives</b><p>A PDF lands in the inbox — no IMAP, just a watched folder.</p></div>
      <div class="step"><b>2 · Extract &amp; ground</b><p>Every field carries a verbatim source span you can see in the PDF.</p></div>
      <div class="step"><b>3 · Verify &amp; route</b><p>An independent verifier grades it; low-confidence self-routes to review.</p></div>
      <div class="step flex"><b>4 · Configure · any insurer</b><p>Chat with the agent to define a new doc type or per-company routing.</p></div>
    </div>
  </header>

  <div class="console">
    <section class="panel">
      <div class="panel-h"><span class="dot"></span><h2>Inbox</h2><span class="count" id="inboxCount"></span></div>
      <div class="filters" id="filters"></div>
      <div class="inbox" id="inbox"></div>
    </section>
    <section class="panel stage" id="stage"></section>
  </div>

  <footer id="foot"></footer>
</div>

<button class="fab" id="fab">⚙ Configure for your company</button>

<aside class="drawer" id="drawer">
  <div class="drawer-h" style="position:relative">
    <button class="x" id="chatX">×</button>
    <h3>Configuration agent</h3>
    <p>Tell it what your company needs to collect. It designs the schema by asking you — it never reads your indexed data.</p>
  </div>
  <div class="msgs" id="msgs"></div>
  <div class="seed" id="seed"></div>
  <div class="composer"><input id="chatIn" placeholder="e.g. We process commercial property applications…" autocomplete="off"><button id="chatSend">Send</button></div>
</aside>

<div class="modal" id="modal">
  <div class="modal-card">
    <div class="modal-h"><h3 id="mTitle">Source document</h3><span class="sub" id="mSub"></span><button class="x" id="mX">×</button></div>
    <div class="pdf-scroll"><div class="pdf-stage" id="pdfStage"><canvas id="pdfCanvas"></canvas><div class="hllayer" id="hlLayer"></div></div></div>
    <div class="modal-note" id="mNote"></div>
  </div>
</div>

<script>
const DATA = /*DATA*/;
const RECORDS = DATA.records, EMAILS = DATA.emails;
const byId = {}; RECORDS.forEach(r => byId[r.doc_id] = r);
const emailById = {}; EMAILS.forEach(e => emailById[e.doc_id] = e);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const isCell = v => v && typeof v === 'object' && 'value' in v && 'confidence' in v;
const confColor = c => c >= .85 ? 'var(--verified)' : (c >= .5 ? 'var(--review)' : 'var(--fail)');
const TYPE = {CertificateOfInsurance:'Certificate of Insurance', FirstNoticeOfLoss:'First Notice of Loss', InsuranceBinder:'Insurance Binder'};
const typeLabel = t => TYPE[t] || t || 'Document';
const fmt = v => v === null ? null : (typeof v === 'number' ? v.toLocaleString('en-US') : v);
if (window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

/* ---------- inbox ---------- */
let activeFilter = 'all';
function renderInbox(){
  const inbox = document.getElementById('inbox');
  const items = EMAILS.filter(e => {
    if (activeFilter === 'all') return true;
    const r = byId[e.doc_id];
    if (activeFilter === '__review') return r._report.status === 'review';
    return r.schema_title === activeFilter;
  });
  inbox.innerHTML = items.map(e => {
    const r = byId[e.doc_id], st = r._report.status;
    return `<button class="email" data-id="${esc(e.doc_id)}">
      <div class="top"><span class="from">${esc(e.from_name)}</span><span class="time">${esc(e.time)}</span></div>
      <div class="subj">${esc(e.subject)}</div>
      <span class="att">📎 ${esc(e.attachment)}</span>
      <span class="pill ${st==='review'?'review':'indexed'}">${st==='review'?'review':'indexed'}</span>
    </button>`;
  }).join('');
  document.getElementById('inboxCount').textContent = items.length + ' message' + (items.length===1?'':'s');
  inbox.querySelectorAll('.email').forEach(b => b.addEventListener('click', () => openEmail(b.dataset.id, b)));
}

/* ---------- the email itself (its subject + body carry real detail) ---------- */
function emailCardHTML(e){
  const r = byId[e.doc_id], st = r._report.status;
  return `<div class="emailcard">
    <div class="ec-row"><span class="ec-k">From</span><span>${esc(e.from_name)} &lt;${esc(e.from_email)}&gt;</span><span class="ec-time">${esc(e.time)}</span></div>
    <div class="ec-row"><span class="ec-k">Subject</span><span class="ec-subj">${esc(e.subject)}</span></div>
    <div class="ec-body">${esc(e.body||e.preview||'')}</div>
    <div class="ec-att">📎 ${esc(e.attachment)} <span class="ec-pill ${st==='review'?'review':'indexed'}">${st==='review'?'→ review queue':'→ indexed'}</span></div>
  </div>`;
}

/* ---------- open email → pipeline-run animation → the record ---------- */
function openEmail(docId, btn){
  document.querySelectorAll('.email').forEach(e=>e.classList.remove('sel'));
  if (btn) btn.classList.add('sel');
  const rec = byId[docId], review = rec._report.status === 'review';
  const email = emailById[docId] || {};
  const steps = [
    'Reading attachment ('+ (rec.source_pdf||'').split('/').pop() +')',
    'Extracting fields to the schema envelope',
    'Verifying — grounding · schema · confidence · accuracy',
    review ? 'Low-confidence fields caught → routed to review-queue' : 'All gates pass → routed to index'
  ];
  const stage = document.getElementById('stage');
  stage.scrollTop = 0;
  stage.innerHTML = emailCardHTML(email)
    + `<div id="recslot"><div class="run" id="run">`+steps.map((s,i)=>
      `<div class="step-line" data-i="${i}"><span class="tick">${i+1}</span><span>${esc(s)}</span></div>`).join('')+`</div></div>`;
  const lines = [...stage.querySelectorAll('.step-line')];
  let i = 0;
  (function tick(){
    if (i>0) lines[i-1].classList.add('done');
    if (i<lines.length){ lines[i].classList.add('on'); i++; setTimeout(tick, 460); }
    else setTimeout(()=>renderRecord(rec), 380);
  })();
}

function cellHTML(name, cell, file){
  const v = cell.value, flagged = cell.needs_review || v===null || (cell.confidence||0)<.85;
  const valHTML = v===null ? `<span class="val nullv">null — not asserted</span>` : `<span class="val">${esc(fmt(v))}</span>`;
  const pct = Math.round((cell.confidence||0)*100);
  const meta = `<div class="meta"><span class="bar"><i style="width:${pct}%;background:${confColor(cell.confidence)}"></i></span><span class="conf">conf ${cell.confidence}</span></div>`;
  const src = cell.source||{};
  let ev = '';
  if (src.text_span){
    // data-* attributes (double-quoted; esc handles ") + a delegated listener —
    // no inline onclick, so untrusted field/file/span text can't break into JS.
    ev = `<div class="ev" data-file="${esc(file)}" data-page="${src.page||1}" data-span="${esc(src.text_span)}" data-name="${esc(name)}">
      <div class="pg"><span>source · page ${src.page}</span><span class="see">view in PDF →</span></div>&ldquo;${esc(src.text_span)}&rdquo;</div>`;
  }
  const rev = flagged ? `<div><span class="rev">needs review</span></div>` : '';
  return `<div class="field${flagged?' flag':''}"><div class="fname">${esc(name)}${rev}</div><div>${valHTML}${meta}${ev}</div></div>`;
}

function renderRecord(rec){
  const r = rec._report, review = r.status==='review';
  const file = (rec.source_pdf||'').split('/').pop();
  const badge = review ? `<span class="badge b-review">Review queue</span>` : `<span class="badge b-indexed">Indexed · verified</span>`;
  const gates = Object.entries(r.gates).map(([k,v])=>{
    const cls = v==='pass'?'g-pass':(v==='fail'?'g-fail':'g-na'); return `<span class="gate ${cls}">${k.replace(/_/g,' ')} · ${v}</span>`;}).join('');
  let body='';
  for(const [k,val] of Object.entries(rec.extraction)){
    if(isCell(val)){ body+=cellHTML(k,val,file); continue; }
    if(Array.isArray(val)){ val.forEach((cov,ci)=>{
      const label=(cov.coverage_type&&cov.coverage_type.value)||('item '+(ci+1));
      let inner=''; for(const [sk,sc] of Object.entries(cov)) if(isCell(sc)) inner+=cellHTML(sk,sc,file);
      body+=`<div class="group-h">${esc(k)} — ${esc(label)}</div>${inner}`;});}
  }
  let routing='';
  if(rec.routing){const rt=rec.routing;
    routing=`<div class="routing"><span class="k">routed</span> <span class="v">${esc(rt.document_type||'')}</span> <span class="arrow">→</span> <span class="k">dept</span> <span class="v">${esc(rt.department||'—')}</span>`+
      (rt.agency_code?` <span class="arrow">·</span> <span class="k">agency</span> <span class="v">${esc(rt.agency_code)}</span>`:'')+
      (rt.market_type?` <span class="arrow">·</span> <span class="k">market</span> <span class="v">${esc(rt.market_type)}</span>`:'')+
      `<span class="ins">${esc(rt.insurer||'')}</span></div>`;}
  let diff='';
  if(rec.diff&&rec.diff.length){diff=`<div class="diff"><div class="dh">Reconciled vs ${esc(rec.prior_doc_id||'prior')} — ${rec.diff.length} field(s) changed &amp; re-verified</div>`+
    rec.diff.map(d=>`<div class="drow"><code>${esc(d.field)}</code><div><code class="from-v">${esc(fmt(d.from))}</code> → <code class="to-v">${esc(fmt(d.to))}</code></div></div>`).join('')+`</div>`;}
  let reasons=''; if(r.reasons&&r.reasons.length) reasons=`<ul class="reasons">`+r.reasons.map(x=>`<li>${esc(x)}</li>`).join('')+`</ul>`;
  const target = document.getElementById('recslot') || document.getElementById('stage');
  target.innerHTML = `<div class="sheet">
    <h2 class="rec">${esc(rec.doc_id)} ${badge}</h2>
    <div class="src"><span class="type">${esc(typeLabel(rec.schema_title))}</span> &nbsp;·&nbsp; ${esc(rec.source_pdf||'')}</div>
    ${routing}<div class="gates">${gates}</div>${body}${diff}${reasons}</div>`;
}

/* ---------- PDF.js: render cited page + highlight the span ---------- */
let pdfCache = {};
async function openPdf(file, page, span, fieldName){
  const modal = document.getElementById('modal');
  document.getElementById('mTitle').textContent = file;
  document.getElementById('mSub').textContent = 'page ' + page + ' · ' + fieldName;
  document.getElementById('mNote').textContent = 'Highlighted: the verbatim span this field was grounded to — “' + span + '”';
  modal.classList.add('open');
  try{
    const doc = pdfCache[file] || (pdfCache[file] = await pdfjsLib.getDocument('pdfs/'+file).promise);
    const pg = await doc.getPage(page);
    const scale = 1.5, viewport = pg.getViewport({scale});
    const canvas = document.getElementById('pdfCanvas'), ctx = canvas.getContext('2d');
    canvas.width = viewport.width; canvas.height = viewport.height;
    document.getElementById('pdfStage').style.width = viewport.width+'px';
    document.getElementById('pdfStage').style.height = viewport.height+'px';
    await pg.render({canvasContext: ctx, viewport}).promise;
    // highlight: anchor on the span's DISTINCTIVE tokens (the value, dates,
    // long words) so we highlight the right line even when PDF.js returns whole
    // lines as single text items.
    const layer = document.getElementById('hlLayer'); layer.innerHTML='';
    const STOP = new Set(['mm/dd/yyyy']);
    const clean = s => s.toLowerCase().replace(/[():;]/g,' ').replace(/\s+/g,' ').trim(); // keep , $ / -
    const toks = clean(span).split(' ');
    // prefer the precise value/date/number tokens; fall back to long words
    let anchors = toks.filter(w => /\d/.test(w) && !STOP.has(w));
    if(!anchors.length) anchors = toks.filter(w => w.length>=6 && !STOP.has(w));
    let firstTop=null;
    const tc = await pg.getTextContent();
    tc.items.forEach(it=>{
      const t = clean(it.str); if(t.length<2) return;
      const hit = anchors.length ? anchors.some(a => t.includes(a)) : clean(span).includes(t);
      if(hit){
        const m = pdfjsLib.Util.transform(viewport.transform, it.transform);
        const h = Math.hypot(m[2], m[3]); const w = (it.width||0)*scale;
        const left = m[4], top = m[5]-h;
        const box = document.createElement('div'); box.className='hlbox';
        box.style.left=left+'px'; box.style.top=top+'px'; box.style.width=Math.max(w,4)+'px'; box.style.height=(h*1.2)+'px';
        layer.appendChild(box); if(firstTop===null||top<firstTop) firstTop=top;
      }
    });
    if(firstTop!==null) document.querySelector('.pdf-scroll').scrollTop = Math.max(0, firstTop-90);
  }catch(e){
    document.getElementById('mNote').textContent = 'Could not render this PDF here (the scanned doc is image-only). Span: “'+span+'”';
  }
}

/* ---------- chat (live config agent via /api/chat) ---------- */
const drawer=document.getElementById('drawer'), msgsEl=document.getElementById('msgs');
let history=[];
function addMsg(role,text,cls){const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'bot')+(cls?(' '+cls):'');d.textContent=text;msgsEl.appendChild(d);msgsEl.scrollTop=msgsEl.scrollHeight;return d;}
function openChat(){drawer.classList.add('open');document.getElementById('chatIn').focus();
  if(!history.length){addMsg('bot',"Hi — I'm the configuration agent. Tell me what kind of document your company needs to process, and I'll propose the fields to collect and confirm the details with you. (I author config only — I don't read your indexed data.)");}}
function closeChat(){drawer.classList.remove('open');}
async function send(text){
  text=(text||'').trim(); if(!text) return;
  document.getElementById('seed').style.display='none';
  addMsg('user',text); history.push({role:'user',content:text});
  const sendBtn=document.getElementById('chatSend'), input=document.getElementById('chatIn');
  sendBtn.disabled=true; input.value='';
  const thinking=addMsg('bot','thinking…','think');
  try{
    const res=await fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({messages:history})});
    const data=await res.json(); thinking.remove();
    if(data.reply){addMsg('bot',data.reply); history.push({role:'assistant',content:data.reply});}
    else addMsg('bot',data.error||'Something went wrong — try again.','think');
  }catch(e){thinking.remove(); addMsg('bot','Could not reach the agent (is the function deployed?).','think');}
  sendBtn.disabled=false; input.focus();
}

/* ---------- wire up ---------- */
function init(){
  // filters
  const counts={}; RECORDS.forEach(r=>counts[r.schema_title]=(counts[r.schema_title]||0)+1);
  const types=[...new Set(RECORDS.map(r=>r.schema_title))];
  const rev=RECORDS.filter(r=>r._report.status==='review').length;
  const chips=[['all','All',RECORDS.length]].concat(types.map(t=>[t,typeLabel(t),counts[t]])).concat([['__review','Review',rev]]);
  document.getElementById('filters').innerHTML=chips.map((c,i)=>`<button class="chip${i===0?' on':''}" data-f="${esc(c[0])}">${esc(c[1])}<span class="ct">${c[2]}</span></button>`).join('');
  document.querySelectorAll('.chip').forEach(ch=>ch.addEventListener('click',()=>{document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));ch.classList.add('on');activeFilter=ch.dataset.f;renderInbox();}));
  renderInbox();
  // empty stage
  document.getElementById('stage').innerHTML=`<div class="empty"><div class="big">Open an email to run it through the pipeline</div><div>Every field will show its source span — click one to see it highlighted in the PDF.</div></div>`;
  // chat
  const idx=RECORDS.length-rev;
  document.getElementById('foot').innerHTML=`${idx} indexed · ${rev} in review · ${types.length} document types, one pipeline · synthetic ACORD-style corpus<br>Built with Claude Code + Claude Opus 4.8 · <a href="https://github.com/kaitlynhemby/insurance-indexer">source</a>`;
  // delegated: open a field's source PDF from its data-* attributes (no inline JS)
  document.addEventListener('click',e=>{
    const el=e.target.closest('.ev'); if(!el||!el.dataset.file) return;
    openPdf(el.dataset.file, +el.dataset.page, el.dataset.span, el.dataset.name);
  });
  document.getElementById('fab').addEventListener('click',openChat);
  document.getElementById('chatX').addEventListener('click',closeChat);
  document.getElementById('mX').addEventListener('click',()=>document.getElementById('modal').classList.remove('open'));
  document.getElementById('modal').addEventListener('click',e=>{if(e.target.id==='modal')document.getElementById('modal').classList.remove('open');});
  document.getElementById('chatSend').addEventListener('click',()=>send(document.getElementById('chatIn').value));
  document.getElementById('chatIn').addEventListener('keydown',e=>{if(e.key==='Enter')send(e.target.value);});
  const seeds=["We process commercial property applications","Set up a workers' comp doc type","Make a profile for our E&S brokerage"];
  document.getElementById('seed').innerHTML=seeds.map(s=>`<button>${esc(s)}</button>`).join('');
  document.querySelectorAll('.seed button').forEach(b=>b.addEventListener('click',()=>{openChat();send(b.textContent);}));
}
init();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Generate the demo console")
    ap.add_argument("--serve", action="store_true", help="serve at http://localhost:8000")
    args = ap.parse_args()
    os.makedirs(VIEWER, exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(build_html())
    print(f"wrote {os.path.relpath(OUT, ROOT)} + bundled PDFs to {os.path.relpath(PDF_DIR, ROOT)}/")
    if args.serve:
        import http.server
        import socketserver
        os.chdir(VIEWER)
        with socketserver.TCPServer(("", 8000), http.server.SimpleHTTPRequestHandler) as httpd:
            print("serving at http://localhost:8000  (chat needs the deployed function)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
