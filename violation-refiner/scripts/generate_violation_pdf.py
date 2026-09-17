#!/usr/bin/env python3
"""
generate_violation_pdf.py

Turn a "violation bundle" JSON file (schema_version 3.0 shape — as used by
CL-030: incident / segments / framework_caches / established_articles /
candidate_articles / element_grids / nexus_matrix / confidence /
open_questions / authorities / cross_references / provenance) into a styled
case-analysis file.

Outputs
-------
- <name>.report.html          styled, static HTML (always written)
- <name>.interactive.html     styled HTML with "+ Verificación / Mejora" panels
- <name>.pdf                  PDF (if a renderer is available)

PDF rendering
-------------
Preferred: WeasyPrint (pip install weasyprint).
Fallback:  wkhtmltopdf on PATH.
If neither is available, the HTML outputs are still written and a warning is
printed. No third-party Python packages are required for JSON handling.

Usage
-----
    python3 generate_violation_pdf.py input.json
    python3 generate_violation_pdf.py input.json output.pdf
    python3 generate_violation_pdf.py input.json --no-pdf
    python3 generate_violation_pdf.py input.json --validate-only
    python3 generate_violation_pdf.py input.json --strict      # non-zero on integrity issues

Exit codes
----------
0  success
1  invalid usage / unreadable input
2  integrity issues found and --strict was passed
3  PDF rendering failed but HTML outputs were written
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


# --------------------------------------------------------------------------
# Optional PDF backends
# --------------------------------------------------------------------------

try:
    import weasyprint  # type: ignore
    _HAVE_WEASYPRINT = True
except Exception:
    _HAVE_WEASYPRINT = False

_HAVE_WKHTMLTOPDF = shutil.which("wkhtmltopdf") is not None


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

CSS = r"""
:root {
  --bg-primary:#f8f7f4; --bg-card:#ffffff; --bg-card-hover:#f2f0ea;
  --bg-surface:#f1efe8; --border:#e1ddd1; --border-strong:#c7c1b0;
  --text-primary:#1b1c1e; --text-secondary:#52555c; --text-muted:#8a8b87;
  --accent:#24405f; --accent-dim:rgba(36,64,95,0.07);
  --status-flag:#7a3733; --status-flag-dim:rgba(122,55,51,0.08);
  --status-analysis:#8a6a2c; --status-analysis-dim:rgba(138,106,44,0.09);
  --status-note:#3f6b4f; --status-note-dim:rgba(63,107,79,0.08);
  --verify:#5b3f8a; --verify-dim:rgba(91,63,138,0.08);
  --mono:'JetBrains Mono','Courier New',monospace;
  --serif:'Source Serif 4',Georgia,serif;
  --sans:'Inter',-apple-system,sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--sans);background:var(--bg-primary);color:var(--text-primary);line-height:1.6}
a{color:var(--accent);text-decoration:none;word-break:break-all}
code{font-family:var(--mono);font-size:.85em;color:var(--accent);background:var(--bg-surface);padding:1px 6px;border-radius:2px}
ul{margin-left:18px}
li{margin:2px 0}

.masthead{border-bottom:1px solid var(--border);padding:32px 0 24px}
.masthead-inner{padding:0 32px}
.masthead-badge{display:inline-block;font-family:var(--mono);font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--status-flag);border:1px solid var(--status-flag);background:var(--status-flag-dim);padding:5px 12px;border-radius:2px;margin-bottom:16px}
.masthead h1{font-family:var(--serif);font-size:1.7rem;font-weight:600;line-height:1.28;margin-bottom:10px}
.masthead-sub{font-size:.9rem;color:var(--text-secondary);max-width:760px;line-height:1.7;margin-bottom:14px}
.masthead-caveat{font-family:var(--mono);font-size:.66rem;color:var(--status-analysis);background:var(--status-analysis-dim);border:1px solid var(--status-analysis);display:inline-block;padding:8px 12px;border-radius:3px;max-width:760px}

.stats-bar{background:var(--bg-card);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.stats-inner{padding:0 32px;display:flex;flex-wrap:wrap}
.stat-item{flex:1 1 130px;padding:16px 14px;border-right:1px solid var(--border)}
.stat-item:last-child{border-right:none}
.stat-val{font-family:var(--mono);font-size:.95rem;font-weight:600}
.stat-label{font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px}

.main{padding:0 32px}
.section-head{padding:30px 0 12px;border-bottom:1px solid var(--border);margin-bottom:16px}
.section-head h2{font-family:var(--serif);font-size:1.2rem;font-weight:600;padding-bottom:10px}
.section-head p{color:var(--text-secondary);font-size:.84rem;padding-bottom:10px;max-width:860px}
.subhead{font-family:var(--mono);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted);margin:18px 0 8px}

.info-box{background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:14px 20px;margin-bottom:24px;font-size:.84rem;color:var(--text-secondary)}
.info-box b{color:var(--text-primary)}

.evidence-grid{display:flex;flex-direction:column;gap:10px}
.evidence-card{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--border-strong);border-radius:3px;padding:16px 20px;page-break-inside:avoid}
.evidence-card.status-established,.evidence-card.status-strong{border-left-color:var(--status-flag)}
.evidence-card.status-contested{border-left-color:var(--status-analysis)}
.evidence-card.status-missing,.evidence-card.status-unverified{border-left-color:var(--border-strong)}
.evidence-card.status-candidate{border-left-color:var(--verify)}
.ev-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}
.ev-body h3{font-size:.9rem;font-weight:600}
.ev-sub{font-family:var(--mono);font-size:.68rem;color:var(--text-muted);margin-top:2px}
.ev-type{font-family:var(--mono);font-size:.6rem;padding:3px 9px;border-radius:2px;text-transform:uppercase;letter-spacing:.05em;font-weight:600;white-space:nowrap}
.type-established,.type-strong{background:var(--status-flag-dim);color:var(--status-flag)}
.type-contested{background:var(--status-analysis-dim);color:var(--status-analysis)}
.type-missing,.type-unverified{background:var(--bg-surface);color:var(--text-muted);border:1px solid var(--border-strong)}
.type-candidate{background:var(--verify-dim);color:var(--verify);border:1px solid var(--verify)}
.ev-summary{font-size:.82rem;color:var(--text-secondary);line-height:1.65;margin-top:6px}
.ev-weak{font-size:.76rem;color:var(--status-flag);margin-top:8px;padding-top:8px;border-top:1px dashed var(--border)}
.ev-provisions{font-family:var(--mono);font-size:.66rem;color:var(--text-muted);margin-top:8px}

.pill{display:inline-block;font-family:var(--mono);font-size:.62rem;padding:2px 8px;border-radius:2px;background:var(--bg-surface);color:var(--text-secondary);border:1px solid var(--border);margin:2px 4px 2px 0}
.pill-accent{background:var(--accent-dim);color:var(--accent);border-color:var(--accent)}
.pill-flag{background:var(--status-flag-dim);color:var(--status-flag);border-color:var(--status-flag)}

/* Framework caches */
.cache-card{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:3px;padding:14px 18px;margin-bottom:10px;page-break-inside:avoid}
.cache-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:6px;flex-wrap:wrap}
.cache-name{font-size:.88rem;font-weight:600}
.cache-code{font-family:var(--mono);font-size:.68rem;color:var(--text-muted)}
.cache-meta{font-family:var(--mono);font-size:.66rem;color:var(--text-muted);margin-top:6px;word-break:break-all;line-height:1.7}
.cache-articles{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.cache-articles span{font-family:var(--mono);font-size:.62rem;padding:2px 8px;border-radius:2px;background:var(--bg-surface);color:var(--text-secondary);border:1px solid var(--border)}

/* Transcript */
.transcript-list{display:flex;flex-direction:column;gap:6px;padding-bottom:8px}
.transcript-segment{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--border-strong);border-radius:3px;padding:11px 16px;page-break-inside:avoid}
.transcript-segment.seg-passenger{border-left-color:var(--accent)}
.transcript-segment.seg-official{border-left-color:var(--status-flag)}
.transcript-segment.seg-airline{border-left-color:var(--status-analysis)}
.transcript-segment.seg-witness{border-left-color:var(--status-note);border-left-style:dashed}
.transcript-segment.seg-other{border-left-color:var(--border-strong)}
.seg-time{font-family:var(--mono);font-size:.66rem;color:var(--text-muted);margin-bottom:3px}
.seg-text{font-size:.84rem;color:var(--text-secondary);line-height:1.6;font-style:italic}
.seg-text-en{font-size:.78rem;color:var(--text-muted);margin-top:3px}
.seg-role{font-size:.7rem;color:var(--text-muted);margin-top:4px;font-family:var(--mono)}
.seg-meta{font-family:var(--mono);font-size:.62rem;color:var(--text-muted);margin-top:6px;padding-top:6px;border-top:1px dashed var(--border);word-break:break-all;line-height:1.7}

/* Element evidence list */
.evidence-links{font-family:var(--mono);font-size:.66rem;color:var(--text-muted);margin-top:6px;line-height:1.7;word-break:break-all}

/* Nexus matrix */
.nexus-group{margin-bottom:18px;page-break-inside:avoid}
.nexus-group-head{font-family:var(--mono);font-size:.7rem;color:var(--accent);margin-bottom:6px;padding:6px 10px;background:var(--bg-surface);border-radius:2px;word-break:break-all}
table.nexus-table{width:100%;border-collapse:collapse;font-size:.74rem;margin-bottom:6px}
table.nexus-table th,table.nexus-table td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);vertical-align:top}
table.nexus-table th{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;color:var(--text-muted);letter-spacing:.04em;background:var(--bg-surface)}
.nexus-strength{font-family:var(--mono);font-size:.6rem;padding:2px 6px;border-radius:2px;text-transform:uppercase}
.strength-high{background:var(--status-flag-dim);color:var(--status-flag)}
.strength-medium{background:var(--status-analysis-dim);color:var(--status-analysis)}
.strength-low{background:var(--bg-surface);color:var(--text-muted)}
.nexus-cell-id{font-family:var(--mono);font-size:.66rem;color:var(--text-secondary);word-break:break-all}

/* Notes panel */
.notes-panel{background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:18px 22px;margin-top:10px}
.notes-label{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--text-secondary);margin-bottom:12px}
.oq-item{border-bottom:1px solid var(--border);padding:10px 0;font-size:.82rem}
.oq-item:last-child{border-bottom:none}
.oq-id{font-family:var(--mono);font-size:.66rem;color:var(--accent);margin-right:8px}
.oq-priority{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;padding:2px 7px;border-radius:2px;border:1px solid var(--border-strong);color:var(--text-muted);margin-left:6px}
.oq-method{font-size:.72rem;color:var(--text-muted);margin-top:4px;font-style:italic}
.oq-dup{color:var(--status-flag);font-family:var(--mono);font-size:.62rem;margin-left:6px}
.oq-blocks{font-family:var(--mono);font-size:.62rem;color:var(--text-secondary);margin-top:3px}

/* Authorities */
.jurisdiction-pill{background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:12px 16px;margin-bottom:8px;page-break-inside:avoid}
.jurisdiction-name{font-family:var(--mono);font-size:.72rem;color:var(--accent);margin-bottom:4px;word-break:break-all}
.jurisdiction-laws{font-size:.8rem;color:var(--text-secondary);line-height:1.6}
.jurisdiction-meta{font-family:var(--mono);font-size:.64rem;color:var(--text-muted);margin-top:6px;line-height:1.7;word-break:break-all}
.verified-tag{font-family:var(--mono);font-size:.6rem;padding:2px 8px;border-radius:2px;text-transform:uppercase}
.verified-yes{background:var(--status-note-dim);color:var(--status-note)}
.verified-no{background:var(--status-flag-dim);color:var(--status-flag)}

/* Confidence history */
table.confidence-table{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:8px;margin-bottom:16px}
table.confidence-table th,table.confidence-table td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border)}
table.confidence-table th{font-family:var(--mono);font-size:.64rem;text-transform:uppercase;color:var(--text-muted);letter-spacing:.05em}
.history-list{font-family:var(--mono);font-size:.68rem;color:var(--text-secondary);line-height:1.9;max-height:280px;overflow-y:auto}
.history-list li{list-style:none;padding:3px 0;border-bottom:1px dotted var(--border)}

/* Provenance */
table.prov-table{width:100%;border-collapse:collapse;font-size:.74rem}
table.prov-table th,table.prov-table td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:top}
table.prov-table th{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;color:var(--text-muted);letter-spacing:.04em;background:var(--bg-surface)}
.prov-ts{font-family:var(--mono);font-size:.66rem;color:var(--text-secondary);white-space:nowrap}
.prov-actor{font-family:var(--mono);font-size:.66rem;color:var(--accent)}
.prov-op{font-family:var(--mono);font-size:.66rem;color:var(--text-secondary);word-break:break-all}
.prov-layer{font-family:var(--mono);font-size:.62rem;color:var(--text-muted);text-align:center}
.prov-note{font-size:.72rem;color:var(--text-secondary)}

.page-footer{border-top:1px solid var(--border);padding:22px 32px;margin-top:36px}
.page-footer p{font-size:.72rem;color:var(--text-muted);line-height:1.8}
.page-footer .mono{font-family:var(--mono)}

/* Integrity */
.issue{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--status-flag);border-radius:3px;padding:12px 16px;margin-bottom:8px;font-size:.82rem}
.issue.sev-high{border-left-color:var(--status-flag)}
.issue.sev-medium{border-left-color:var(--status-analysis)}
.issue.sev-low{border-left-color:var(--status-note)}
.issue-code{font-family:var(--mono);font-size:.66rem;color:var(--status-flag);text-transform:uppercase;letter-spacing:.04em}
.issue-title{font-weight:600;margin-top:2px}
.issue-detail{color:var(--text-secondary);margin-top:4px;line-height:1.6}
.issue-fix{color:var(--text-secondary);margin-top:6px;font-size:.78rem}
.issue-fix b{color:var(--text-primary)}

/* TOC */
.toc{background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:14px 20px;margin-bottom:16px;columns:2;column-gap:28px}
.toc a{display:block;font-size:.8rem;color:var(--text-secondary);padding:3px 0;border-bottom:1px dotted var(--border)}
.toc a:hover{color:var(--accent)}

/* Verification panels */
.vpanel{margin:10px 0 22px;border:1px solid var(--verify);border-left:3px solid var(--verify);border-radius:4px;background:linear-gradient(0deg,var(--verify-dim),var(--verify-dim)),var(--bg-card)}
.vpanel>summary{list-style:none;cursor:pointer;padding:10px 16px;display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:.72rem;letter-spacing:.04em;text-transform:uppercase;color:var(--verify);user-select:none}
.vpanel>summary::-webkit-details-marker{display:none}
.vpanel>summary::before{content:"+";display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border:1px solid var(--verify);border-radius:3px;font-weight:700;font-size:.9rem;line-height:1}
.vpanel[open]>summary::before{content:"−"}
.vpanel>summary .vtag{margin-left:auto;font-size:.6rem;padding:2px 8px;border-radius:2px;border:1px solid var(--verify);background:rgba(255,255,255,.5)}
.vtag.status-open{color:var(--status-flag);border-color:var(--status-flag);background:var(--status-flag-dim)}
.vtag.status-inprogress{color:var(--status-analysis);border-color:var(--status-analysis);background:var(--status-analysis-dim)}
.vtag.status-resolved{color:var(--status-note);border-color:var(--status-note);background:var(--status-note-dim)}
.vbody{padding:4px 18px 18px;font-size:.82rem;color:var(--text-secondary)}
.vblock{margin-top:12px}
.vblock h4{font-family:var(--mono);font-size:.66rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin-bottom:6px}
.vfields{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.vfield{display:flex;flex-direction:column;gap:4px}
.vfield.full{grid-column:1/-1}
.vfield label{font-family:var(--mono);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}
.vfield textarea,.vfield select,.vfield input[type=text]{font-family:var(--sans);font-size:.8rem;color:var(--text-primary);background:var(--bg-card);border:1px solid var(--border-strong);border-radius:3px;padding:8px 10px;resize:vertical;min-height:38px;line-height:1.5}
.vfield textarea{min-height:72px}
.vdrop{border:1.5px dashed var(--border-strong);border-radius:3px;padding:12px 14px;text-align:center;font-family:var(--mono);font-size:.68rem;color:var(--text-muted);background:var(--bg-card);cursor:pointer;display:block}
.vdrop input{display:none}
.vfiles{margin-top:6px;font-family:var(--mono);font-size:.68rem;color:var(--text-secondary)}
.vfiles li{margin:2px 0;list-style:none}
.vbar{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.vbar select{font-family:var(--mono);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;padding:6px 8px;border:1px solid var(--border-strong);border-radius:3px;background:var(--bg-card);color:var(--text-secondary)}
.vnote{font-size:.7rem;color:var(--text-muted);font-style:italic;margin-top:8px}

@media print{
  .vpanel{display:none}
  .toc{display:none}
  .masthead,.stats-bar,.page-footer{page-break-inside:avoid}
  .section-head{page-break-after:avoid}
  .evidence-card,.transcript-segment,.jurisdiction-pill,.issue,.cache-card,.nexus-group{page-break-inside:avoid}
  .history-list{max-height:none;overflow:visible}
}
@page{size:A4;margin:16mm 12mm}
"""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def fmt_offset(seconds: Any) -> str:
    if seconds is None:
        return "?"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def speaker_class(speaker: str) -> str:
    s = (speaker or "").lower()
    if s == "passenger":
        return "seg-passenger"
    if "pdi" in s or "dgac" in s or "official" in s or "police" in s:
        return "seg-official"
    if "airline" in s or "crew" in s or "pilot" in s or "staff" in s:
        return "seg-airline"
    if "passenger" in s and s != "passenger":
        return "seg-witness"
    return "seg-other"


def strength_class(s: str) -> str:
    m = {
        "high": "strength-high",
        "medium": "strength-medium",
        "low": "strength-low",
    }
    return m.get((s or "").lower(), "strength-low")


PROOF_STATUS_CLASS = {
    "established": "established",
    "strong": "strong",
    "contested": "contested",
    "missing": "missing",
    "unverified": "unverified",
}


def status_class(s: str) -> str:
    return PROOF_STATUS_CLASS.get((s or "").lower(), "missing")


# --------------------------------------------------------------------------
# Integrity validation
# --------------------------------------------------------------------------

class IntegrityReport:
    def __init__(self) -> None:
        self.issues: list[dict] = []

    def add(self, code: str, severity: str, title: str, detail: str, fix: str = "") -> None:
        self.issues.append({
            "code": code, "severity": severity,
            "title": title, "detail": detail, "fix": fix,
        })

    def has_issues(self) -> bool:
        return bool(self.issues)

    def by_severity(self, sev: str) -> list[dict]:
        return [i for i in self.issues if i["severity"] == sev]


def validate(data: dict) -> IntegrityReport:
    r = IntegrityReport()

    grid_ids: set[str] = set()
    grid_article_ids: set[str] = set()
    for g in data.get("element_grids", []) or []:
        grid_article_ids.add(g.get("article_id", ""))
        for e in g.get("elements", []) or []:
            eid = e.get("element_id")
            if eid:
                grid_ids.add(eid)

    # --- nexus: orphan element ids ---------------------------------------
    seen_orphans: dict[str, int] = defaultdict(int)
    for n in data.get("nexus_matrix", []) or []:
        eid = n.get("element_id")
        if eid and eid not in grid_ids:
            seen_orphans[eid] += 1
    if seen_orphans:
        sample = ", ".join(f"{k} ({v}×)" for k, v in list(seen_orphans.items())[:6])
        r.add(
            "INTEGRITY-ORPHAN-ELEMENT-IDS", "high",
            "nexus_matrix references element_ids that do not exist in element_grids",
            f"{len(seen_orphans)} orphan element_id(s). Examples: {sample}.",
            "Regenerate nexus rows using the canonical element_id values from element_grids, or add the missing elements to the grids."
        )

    # --- nexus: unknown articles ------------------------------------------
    unknown_articles = set()
    for n in data.get("nexus_matrix", []) or []:
        nid = n.get("norm_id")
        if nid and grid_article_ids and nid not in grid_article_ids:
            unknown_articles.add(nid)
    if unknown_articles:
        r.add(
            "INTEGRITY-NEXUS-UNKNOWN-ARTICLE", "medium",
            "nexus_matrix references norm_id values with no matching element grid",
            f"{len(unknown_articles)} unknown norm_id(s): {', '.join(sorted(unknown_articles)[:6])}.",
            "Either add an element grid for each referenced article or remove the nexus rows."
        )

    # --- nexus: unknown fact/segment ids ----------------------------------
    seg_ids = {s.get("segment_id") for s in data.get("segments", []) or [] if s.get("segment_id")}
    orphan_facts: dict[str, int] = defaultdict(int)
    for n in data.get("nexus_matrix", []) or []:
        fid = n.get("fact_id")
        if fid and seg_ids and fid not in seg_ids:
            orphan_facts[fid] += 1
    if orphan_facts:
        sample = ", ".join(f"{k} ({v}×)" for k, v in list(orphan_facts.items())[:5])
        r.add(
            "INTEGRITY-NEXUS-ORPHAN-FACT-IDS", "medium",
            "nexus_matrix references fact_ids that do not appear in segments",
            f"{len(orphan_facts)} orphan fact_id(s). Examples: {sample}.",
            "Reconcile segment_id values between segments[] and nexus_matrix[].fact_id."
        )

    # --- duplicate open question ids --------------------------------------
    oq_ids = [oq.get("id") for oq in data.get("open_questions", []) or [] if oq.get("id")]
    dup_oq = [k for k, v in Counter(oq_ids).items() if v > 1]
    if dup_oq:
        r.add(
            "INTEGRITY-DUPLICATE-OQ-IDS", "medium",
            "Duplicate open-question IDs",
            f"{len(dup_oq)} duplicated ID(s): {', '.join(dup_oq[:8])}.",
            "Deduplicate or rename the open questions so each ID is unique."
        )

    # --- near-duplicate open questions ------------------------------------
    norm = lambda s: "".join(ch.lower() for ch in (s or "") if ch.isalnum())
    seen: dict[str, str] = {}
    near_dups: list[tuple[str, str]] = []
    for oq in data.get("open_questions", []) or []:
        q = oq.get("question") or ""
        key = norm(q)
        if len(key) < 20:
            continue
        if key in seen:
            near_dups.append((seen[key], oq.get("id", "")))
        else:
            seen[key] = oq.get("id", "")
    if near_dups:
        sample = ", ".join(f"{a}≈{b}" for a, b in near_dups[:5])
        r.add(
            "INTEGRITY-NEAR-DUPLICATE-OQ", "low",
            "Near-duplicate open questions",
            f"{len(near_dups)} pair(s) of questions are textually near-identical. Examples: {sample}.",
            "Merge or differentiate; identical questions should be one entry with one owner."
        )

    # --- duplicate authority ids ------------------------------------------
    auth_ids = [a.get("authority_id") for a in data.get("authorities", []) or [] if a.get("authority_id")]
    dup_auth = [k for k, v in Counter(auth_ids).items() if v > 1]
    if dup_auth:
        r.add(
            "INTEGRITY-DUPLICATE-AUTHORITY-IDS", "medium",
            "Duplicate authority IDs",
            f"{len(dup_auth)} duplicated authority ID(s): {', '.join(dup_auth[:8])}.",
            "Deduplicate authorities or assign distinct IDs."
        )

    # --- confidence factor vs verified ratio ------------------------------
    conf = data.get("confidence", {}) or {}
    factor = conf.get("authorities_verification_factor")
    authorities = data.get("authorities", []) or []
    if authorities and isinstance(factor, (int, float)):
        verified = sum(1 for a in authorities if a.get("verified") is True)
        ratio = verified / len(authorities)
        expected_max = 0.85 + 0.15 * ratio
        if factor > expected_max + 1e-6:
            r.add(
                "INTEGRITY-CONFIDENCE-FACTOR", "high",
                "Authorities verification factor inconsistent with verified ratio",
                f"factor={factor}, verified={verified}/{len(authorities)} (ratio={ratio:.2f}). "
                f"Given the stated derivation formula, factor should be at most ~{expected_max:.3f}.",
                "Recompute the factor from the verified ratio, or document a different formula."
            )

    # --- confidence component range ---------------------------------------
    for k, v in (conf.get("components") or {}).items():
        if isinstance(v, (int, float)) and not (0.0 <= v <= 1.0):
            r.add(
                "INTEGRITY-CONFIDENCE-RANGE", "medium",
                "Confidence component out of [0,1] range",
                f"{k} = {v}.",
                "Clamp to [0,1] or correct the derivation."
            )

    # --- established articles lack element grids --------------------------
    established_ids = {a.get("article_id") for a in data.get("established_articles", []) or []}
    missing_grids = established_ids - grid_article_ids
    if missing_grids:
        r.add(
            "INTEGRITY-MISSING-GRID", "high",
            "Established article without an element grid",
            f"Articles: {', '.join(sorted(missing_grids))}.",
            "Every article used in the analysis should have an element grid."
        )

    # --- candidate articles flagged not applicable ------------------------
    not_applicable = []
    for c in data.get("candidate_articles", []) or []:
        view = (c.get("preliminary_view") or "").lower()
        if "flag:" in view and ("mismatch" in view or "does not" in view or "not applic" in view):
            not_applicable.append(c.get("candidate_article_id", ""))
    if not_applicable:
        r.add(
            "HYGIENE-NON-APPLICABLE-CANDIDATES", "low",
            "Candidate list contains non-applicable articles",
            f"{len(not_applicable)} candidate(s) are described as not applicable: "
            f"{', '.join(not_applicable[:6])}.",
            "Move them to an explicit exclusions list so reviewers do not treat them as live candidates."
        )

    # --- framework caches carry sha but no source url ---------------------
    for c in data.get("framework_caches", []) or []:
        if not c.get("cache_source_url"):
            r.add(
                "HYGIENE-CACHE-NO-SOURCE-URL", "low",
                "Framework cache without a source URL",
                f"framework_code={c.get('framework_code')} has cache_file_sha256 but no cache_source_url.",
                "Record the official source URL and fetch date so the cache is externally auditable."
            )

    # --- element grids missing proof_evidence_segments --------------------
    for g in data.get("element_grids", []) or []:
        for e in g.get("elements", []) or []:
            if not e.get("proof_evidence_segments"):
                r.add(
                    "HYGIENE-ELEMENT-NO-EVIDENCE", "low",
                    "Element without proof_evidence_segments",
                    f"element_id={e.get('element_id')} on {g.get('article_id')} has no linked segments.",
                    "Link at least the decisive segments, or mark the element as 'missing'."
                )

    return r


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------

def build_masthead(data: dict) -> str:
    title = esc(data.get("title") or data.get("violation_id", "Untitled violation"))
    vid = esc(data.get("violation_id", ""))
    severity = esc((data.get("severity") or "UNKNOWN").upper())
    inc = data.get("incident", {}) or {}
    bits = [esc(inc.get(k, "")) for k in ("location", "date", "flight", "operator")]
    sub = " · ".join(b for b in bits if b)
    return f"""
<div class="masthead">
  <div class="masthead-inner">
    <span class="masthead-badge">{vid} · Severity: {severity} — Working Case File</span>
    <h1>{title}</h1>
    <p class="masthead-sub">{sub}</p>
    <span class="masthead-caveat">⚠ Documento de trabajo analítico generado a partir del expediente de datos.
    No constituye una determinación judicial ni una acusación formal. Los elementos marcados "contested" y las
    autoridades no verificadas no deben presentarse como hechos probados.</span>
  </div>
</div>
"""


def build_toc() -> str:
    items = [
        ("incident", "1. Incidente"),
        ("frameworks", "2. Cachés de marcos legales"),
        ("established", "3. Base normativa — establecidos"),
        ("candidates", "4. Artículos candidatos"),
        ("elements", "5. Análisis elemento por elemento"),
        ("nexus", "6. Matriz de nexo"),
        ("transcript", "7. Evidencia de la transcripción"),
        ("confidence", "8. Puntaje de confianza"),
        ("questions", "9. Preguntas abiertas"),
        ("authorities", "10. Autoridades"),
        ("xrefs", "11. Referencias cruzadas"),
        ("provenance", "12. Provenance"),
        ("integrity", "13. Reporte de integridad"),
    ]
    links = "".join(f'<a href="#sec-{k}">{esc(v)}</a>' for k, v in items)
    return f'<div class="toc">{links}</div>'


def build_stats(data: dict) -> str:
    conf = data.get("confidence", {}) or {}
    val = conf.get("value")
    conf_str = f"{val:.2f} / 1.00" if isinstance(val, (int, float)) else "n/a"

    n_articles = len(data.get("established_articles", []) or [])
    n_candidates = len(data.get("candidate_articles", []) or [])
    n_segments = len(data.get("segments", []) or [])
    n_open = len(data.get("open_questions", []) or [])
    n_nexus = len(data.get("nexus_matrix", []) or [])
    n_caches = len(data.get("framework_caches", []) or [])
    n_prov = len(data.get("provenance", []) or [])
    auths = data.get("authorities", []) or []
    n_auth = len(auths)
    n_auth_verified = sum(1 for a in auths if a.get("verified") is True)

    items = [
        (conf_str, "Confidence"),
        (str(n_articles), "Est. Articles"),
        (str(n_candidates), "Candidates"),
        (str(n_caches), "Framework Caches"),
        (str(n_segments), "Segments"),
        (str(n_nexus), "Nexus Rows"),
        (str(n_open), "Open Questions"),
        (f"{n_auth_verified} / {n_auth}", "Auth. Verified"),
        (str(n_prov), "Provenance"),
    ]
    cells = "".join(
        f'<div class="stat-item"><div class="stat-val">{esc(v)}</div>'
        f'<div class="stat-label">{esc(l)}</div></div>'
        for v, l in items
    )
    return f'<div class="stats-bar"><div class="stats-inner">{cells}</div></div>'


def build_incident_box(data: dict) -> str:
    inc = data.get("incident", {}) or {}
    if not inc:
        return ""
    rows = "".join(
        f'<div><b>{esc(k)}</b>: {esc(v) if v not in (None, "") else "—"}</div>'
        for k, v in inc.items()
    )
    return f"""
<div class="section-head" id="sec-incident"><h2>1. Incidente</h2></div>
<div class="info-box">{rows}</div>
"""


def build_framework_caches(data: dict) -> str:
    caches = data.get("framework_caches", []) or []
    if not caches:
        return ""
    cards = []
    for c in caches:
        code = esc(c.get("framework_code", ""))
        name = esc(c.get("framework_name", ""))
        cache_file = esc(c.get("cache_file", ""))
        cache_sha = esc(c.get("cache_file_sha256", ""))
        self_sha = esc(c.get("cache_self_reported_sha256", "") or "—")
        src = c.get("cache_source_url")
        src_html = f'<a href="{esc(src)}">{esc(src)}</a>' if src else "—"
        fetched = esc(c.get("cache_fetched_at", "") or "—")
        articles = as_list(c.get("articles_cached"))
        pills = "".join(f'<span>{esc(a)}</span>' for a in articles)
        cards.append(f"""
    <div class="cache-card">
      <div class="cache-head">
        <div>
          <div class="cache-name">{name}</div>
          <div class="cache-code">{code}</div>
        </div>
      </div>
      <div class="cache-meta">
        file: {cache_file}<br>
        cache_file_sha256: <code>{cache_sha}</code><br>
        self_reported_sha256: <code>{self_sha}</code><br>
        source_url: {src_html}<br>
        fetched_at: {fetched}
      </div>
      <div class="cache-articles">{pills}</div>
    </div>""")
    return f"""
<div class="section-head" id="sec-frameworks">
  <h2>2. Cachés de marcos legales</h2>
  <p>Marcos legales referenciados por el bundle y los artículos cargados en cada caché. Los hashes permiten verificar la integridad del texto legal usado para fundamentar los artículos "establecidos".</p>
</div>
<div style="margin-bottom:24px;">{''.join(cards)}</div>
"""


def build_established_articles(data: dict) -> str:
    arts = data.get("established_articles", []) or []
    if not arts:
        return ""
    cards = []
    for art in arts:
        aid = esc(art.get("article_id", ""))
        name = esc(art.get("article_name", art.get("article_id", "")))
        excerpt = esc(art.get("verbatim_excerpt", ""))
        excerpt_sha = esc(art.get("verbatim_excerpt_sha256", "") or "—")
        duty = esc(art.get("duty_bearer", ""))
        applic = esc(art.get("applicability", ""))
        fw = esc(art.get("framework_code", ""))
        cache = esc(art.get("framework_cache_status", ""))
        norm_type = esc(art.get("norm_type", ""))
        subs = as_list(art.get("subsections_invoked"))
        subs_html = "".join(f'<span class="pill">{esc(s)}</span>' for s in subs) if subs else "—"
        rationale = esc(art.get("applicability_rationale", "") or "")
        rationale_html = f'<div class="ev-weak" style="color:var(--text-secondary);border-top-color:var(--border)"><b>Racionalidad de aplicabilidad:</b> {rationale}</div>' if rationale else ""
        cards.append(f"""
    <div class="evidence-card status-strong">
      <div class="ev-head"><div class="ev-body">
        <h3>{name}</h3>
        <div class="ev-sub">Sujeto obligado: {duty} · Framework: {fw} · Tipo: {norm_type} · Aplicabilidad: {applic}</div>
      </div></div>
      <div class="ev-summary">"{excerpt}"</div>
      <div class="evidence-links">subsecciones: {subs_html}</div>
      {rationale_html}
      <div class="ev-provisions">{aid} · framework_cache: {cache} · excerpt_sha256: {excerpt_sha}</div>
    </div>""")
    return f"""
<div class="section-head" id="sec-established">
  <h2>3. Base normativa — artículos "establecidos"</h2>
  <p><strong>Nota:</strong> "establecido" aquí significa <em>texto legal identificado en caché</em>, no
  <em>violación establecida</em>. La aplicabilidad final depende de la prueba por elemento.</p>
</div>
<div class="evidence-grid" style="margin-bottom:24px;">{''.join(cards)}</div>
"""


def build_candidate_articles(data: dict) -> str:
    cands = data.get("candidate_articles", []) or []
    if not cands:
        return ""
    cards = []
    for c in cands:
        cid = esc(c.get("candidate_article_id", ""))
        name = esc(c.get("candidate_name", ""))
        view = esc(c.get("preliminary_view", ""))
        status = esc(c.get("framework_cache_status", "not_in_bundle"))
        reqs = c.get("verification_required") or []
        req_html = ""
        if reqs:
            items = "".join(f"<li>{esc(x)}</li>" for x in reqs)
            req_html = f'<div class="ev-weak"><b>Verificación requerida:</b><ul>{items}</ul></div>'
        hist = esc(c.get("history_note", ""))
        hist_html = f'<div class="ev-provisions">{hist}</div>' if hist else ""
        cards.append(f"""
    <div class="evidence-card status-candidate">
      <div class="ev-head">
        <div class="ev-body">
          <h3>{name}</h3>
          <div class="ev-sub">{cid} · cache: {status}</div>
        </div>
        <span class="ev-type type-candidate">candidate</span>
      </div>
      <div class="ev-summary">{view}</div>
      {req_html}
      {hist_html}
    </div>""")
    return f"""
<div class="section-head" id="sec-candidates">
  <h2>4. Artículos candidatos</h2>
  <p>Artículos evaluados pero aún no "establecidos". Requieren verificación de texto, sujeto activo y conducta típica.</p>
</div>
<div class="evidence-grid" style="margin-bottom:24px;">{''.join(cards)}</div>
"""


def build_element_grids(data: dict) -> str:
    grids = data.get("element_grids", []) or []
    if not grids:
        return ""
    sections = []
    for grid in grids:
        article_id = esc(grid.get("article_id", ""))
        article_short = esc(grid.get("article_short", article_id))
        elements = grid.get("elements", []) or []
        cards = []
        for elem in elements:
            label = esc(elem.get("label", elem.get("element_id", "")))
            eid = esc(elem.get("element_id", ""))
            status = elem.get("proof_status", "missing")
            cls = status_class(status)
            argument = esc(elem.get("argument_es") or elem.get("argument_en") or "")
            weaknesses = as_list(elem.get("weaknesses"))
            oqs = as_list(elem.get("open_questions"))
            basis = esc(elem.get("doctrinal_basis", ""))
            evidence_segs = as_list(elem.get("proof_evidence_segments"))

            weak_html = ""
            if weaknesses:
                items = "".join(f"<li>{esc(w)}</li>" for w in weaknesses)
                weak_html = f'<div class="ev-weak"><b>Debilidades:</b><ul>{items}</ul></div>'

            oq_html = ""
            if oqs:
                items = "".join(f"<li>{esc(q)}</li>" for q in oqs)
                oq_html = f'<div class="ev-provisions"><b>Preguntas abiertas:</b><ul>{items}</ul></div>'

            evidence_html = ""
            if evidence_segs:
                items = "".join(f"<li>{esc(s)}</li>" for s in evidence_segs)
                evidence_html = f'<div class="evidence-links"><b>Segmentos probatorios:</b><ul>{items}</ul></div>'
            else:
                evidence_html = '<div class="evidence-links"><b>Segmentos probatorios:</b> —</div>'

            basis_html = f'<div class="ev-provisions">Base doctrinal: {basis}</div>' if basis else ""

            cards.append(f"""
    <div class="evidence-card status-{cls}">
      <div class="ev-head">
        <div><h3>{label}</h3><div class="ev-sub">{eid}</div></div>
        <span class="ev-type type-{cls}">{esc(status)}</span>
      </div>
      <div class="ev-summary">{argument}</div>
      {basis_html}
      {evidence_html}
      {weak_html}
      {oq_html}
    </div>""")
        sections.append(f"""
<div class="subhead">{article_id} — {article_short}</div>
<div class="evidence-grid" style="margin-bottom:18px;">{''.join(cards)}</div>
""")
    return f"""
<div class="section-head" id="sec-elements">
  <h2>5. Análisis elemento por elemento</h2>
  <p>Estado de prueba por elemento típico. "Established"/"strong" indica respaldo documental directo;
     "contested" indica que la calificación jurídica final permanece abierta. Cada tarjeta lista los segmentos
     probatorios que la sustentan.</p>
</div>
{''.join(sections)}
"""


def build_nexus_matrix(data: dict) -> str:
    rows = data.get("nexus_matrix", []) or []
    if not rows:
        return ""
    # Group by (norm_id, element_id) for readability
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for n in rows:
        groups[(n.get("norm_id", "?"), n.get("element_id", "?"))].append(n)

    blocks = []
    for (norm_id, element_id), entries in groups.items():
        body_rows = []
        for n in entries:
            fid = esc(n.get("fact_id", ""))
            ntype = esc(n.get("nexus_type", ""))
            strength = (n.get("strength") or "").lower()
            scls = strength_class(strength)
            rationale = esc(n.get("rationale_oneline", ""))
            body_rows.append(
                f'<tr><td class="nexus-cell-id">{fid}</td>'
                f'<td><span class="pill">{ntype}</span></td>'
                f'<td><span class="nexus-strength {scls}">{esc(strength)}</span></td>'
                f'<td>{rationale}</td></tr>'
            )
        blocks.append(f"""
<div class="nexus-group">
  <div class="nexus-group-head">{esc(norm_id)}  →  {esc(element_id)}  ({len(entries)} link{'s' if len(entries) != 1 else ''})</div>
  <table class="nexus-table">
    <thead><tr><th>fact_id (segmento)</th><th>tipo</th><th>fuerza</th><th>racional</th></tr></thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
</div>""")
    return f"""
<div class="section-head" id="sec-nexus">
  <h2>6. Matriz de nexo hecho ↔ norma ↔ elemento</h2>
  <p>Vinculación entre cada segmento probatorio y el elemento típico del artículo que lo sustenta. Los enlaces huérfanos se reportan en la Sección 13.</p>
</div>
<div style="margin-bottom:24px;">{''.join(blocks)}</div>
"""


def build_transcript(data: dict, max_segments: int | None = None) -> str:
    segs = data.get("segments", []) or []
    if not segs:
        return ""
    shown = segs if max_segments is None else segs[:max_segments]
    note = ""
    if max_segments is not None and len(segs) > max_segments:
        note = f"<p>Mostrando {max_segments} de {len(segs)} segmentos.</p>"

    rows = []
    for seg in shown:
        speaker = seg.get("speaker", "")
        cls = speaker_class(speaker)
        t0 = fmt_offset(seg.get("audio_offset_start"))
        t1 = fmt_offset(seg.get("audio_offset_end"))
        sid = esc(seg.get("segment_id", ""))
        role = esc(seg.get("role_in_argument", ""))
        verbatim = esc(seg.get("verbatim_es", ""))
        translation = esc(seg.get("translation_en", ""))
        notes = esc(seg.get("transcription_notes", "") or "")
        notes_html = f'<div class="seg-role">nota: {notes}</div>' if notes else ""
        role_html = f'<div class="seg-role">rol: {role}</div>' if role else ""
        v_sha = esc(seg.get("verbatim_sha256", "") or "—")
        src = esc(seg.get("source_uri", "") or "—")
        src_sha = esc(seg.get("source_sha256", "") or "—")
        audio = esc(seg.get("audio_uri", "") or "—")
        meta_html = (
            f'<div class="seg-meta">'
            f'verbatim_sha256: {v_sha}<br>'
            f'source_uri: {src}<br>'
            f'source_sha256: {src_sha}<br>'
            f'audio_uri: {audio}'
            f'</div>'
        )
        rows.append(f"""
    <div class="transcript-segment {cls}">
      <div class="seg-time">{esc(speaker)} · {t0}–{t1} · {sid}</div>
      <div class="seg-text">"{verbatim}"</div>
      <div class="seg-text-en">{translation}</div>
      {role_html}
      {notes_html}
      {meta_html}
    </div>""")
    return f"""
<div class="section-head" id="sec-transcript">
  <h2>7. Evidencia de la transcripción</h2>
  {note}
</div>
<div class="transcript-list" style="margin-bottom:24px;">{''.join(rows)}</div>
"""


def build_confidence(data: dict) -> str:
    conf = data.get("confidence", {}) or {}
    if not conf:
        return ""
    comps = conf.get("components", {}) or {}
    factor = conf.get("authorities_verification_factor")
    value = conf.get("value")
    formula = esc(conf.get("derivation_formula", ""))
    derived_at = esc(conf.get("derived_at", "") or "—")
    history = as_list(conf.get("history"))

    rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in comps.items())
    if factor is not None:
        rows += f"<tr><td>Authorities verification factor</td><td>{esc(factor)}</td></tr>"
    if value is not None:
        rows += f"<tr><td><strong>Confianza global</strong></td><td><strong>{esc(value)}</strong></td></tr>"
    rows += f"<tr><td>derived_at</td><td>{derived_at}</td></tr>"
    formula_html = f'<p style="font-family:var(--mono);font-size:.7rem;color:var(--text-muted);margin-top:8px">{formula}</p>' if formula else ""

    hist_html = ""
    if history:
        items = "".join(f"<li>{esc(h)}</li>" for h in history)
        hist_html = f"""
<div class="subhead">Historial de puntaje ({len(history)} eventos)</div>
<ul class="history-list">{items}</ul>
"""

    return f"""
<div class="section-head" id="sec-confidence"><h2>8. Puntaje de confianza</h2></div>
<table class="confidence-table">
  <tr><th>Componente</th><th>Valor</th></tr>
  {rows}
</table>
{formula_html}
{hist_html}
"""


def build_open_questions(data: dict) -> str:
    oqs = data.get("open_questions", []) or []
    if not oqs:
        return ""
    counts = Counter(oq.get("id") for oq in oqs if oq.get("id"))
    items = []
    for oq in oqs:
        oid = esc(oq.get("id", ""))
        q = esc(oq.get("question", ""))
        pr = esc(oq.get("priority", ""))
        method = esc(oq.get("obtaining_method", "") or "")
        blocks = esc(oq.get("blocks_element", "") or "")
        dup = f'<span class="oq-dup">×{counts[oq.get("id")]}</span>' if counts.get(oq.get("id"), 0) > 1 else ""
        method_html = f'<div class="oq-method">{method}</div>' if method else ""
        blocks_html = f'<div class="oq-blocks">bloquea: {blocks}</div>' if blocks else ""
        items.append(
            f'<div class="oq-item"><span class="oq-id">{oid}</span>{q}'
            f'<span class="oq-priority">{pr}</span>{dup}{blocks_html}{method_html}</div>'
        )
    return f"""
<div class="section-head" id="sec-questions">
  <h2>9. Preguntas abiertas (verificación pendiente)</h2>
</div>
<div class="notes-panel" style="margin-bottom:28px;">
  <div class="notes-label">{len(oqs)} open questions</div>
  {''.join(items)}
</div>
"""


def build_authorities(data: dict) -> str:
    auths = data.get("authorities", []) or []
    if not auths:
        return ""
    n_verified = sum(1 for a in auths if a.get("verified") is True)
    pills = []
    for a in auths:
        aid = esc(a.get("authority_id", ""))
        typ = esc(a.get("type", ""))
        verified = a.get("verified") is True
        tag_cls = "verified-yes" if verified else "verified-no"
        tag_txt = "verificado" if verified else "no verificado"
        proposition = esc(a.get("proposition_to_verify", "") or "")
        risk = esc(a.get("fabrication_risk_note", "") or "")
        query = esc(a.get("research_query", "") or "")
        supports = as_list(a.get("supports"))
        support_pills = "".join(f'<span class="pill">{esc(s)}</span>' for s in supports) if supports else "—"

        # Optional case metadata
        meta_bits = []
        for key, label in [
            ("court", "court"), ("rol", "rol"), ("decision_date", "date"),
            ("author", "author"), ("work", "work"), ("pages", "pages"),
            ("instrument", "instrument"),
        ]:
            v = a.get(key)
            if v:
                meta_bits.append(f"{label}: {esc(v)}")
        meta_html = f'<div class="jurisdiction-meta">{" · ".join(meta_bits)}</div>' if meta_bits else ""

        holding = esc(a.get("holding_summary", "") or "")
        holding_html = f'<div class="jurisdiction-meta">holding: {holding}</div>' if holding else ""

        vproto = esc(a.get("verification_protocol", "") or "")
        vprov = esc(a.get("verification_provenance", "") or "")
        vproto_html = f'<div class="jurisdiction-meta">verification_protocol: {vproto}</div>' if vproto else ""
        vprov_html = f'<div class="jurisdiction-meta">verification_provenance: {vprov}</div>' if vprov else ""

        risk_html = f'<div class="jurisdiction-meta" style="color:var(--status-flag)">riesgo: {risk}</div>' if risk else ""
        query_html = f'<div class="jurisdiction-meta">query: {query}</div>' if query else ""

        pills.append(f"""
    <div class="jurisdiction-pill">
      <div class="jurisdiction-name">{aid} <span class="verified-tag {tag_cls}">{tag_txt}</span></div>
      <div class="jurisdiction-laws">{proposition or "—"}</div>
      <div class="evidence-links">soporta: {support_pills}</div>
      <div class="jurisdiction-meta">tipo: {typ}</div>
      {meta_html}
      {holding_html}
      {vproto_html}
      {vprov_html}
      {risk_html}
      {query_html}
    </div>""")
    return f"""
<div class="section-head" id="sec-authorities">
  <h2>10. Autoridades citadas</h2>
  <p><strong>{n_verified} de {len(auths)}</strong> autoridades listadas están verificadas. Las autoridades
     no verificadas no deben citarse como texto confirmado.</p>
</div>
<div style="margin-bottom:16px;">{''.join(pills)}</div>
"""


def build_cross_references(data: dict) -> str:
    xrefs = data.get("cross_references", []) or []
    if not xrefs:
        return ""
    items = "".join(
        f"<li><code>{esc(x.get('ref', ''))}</code> — {esc(x.get('relation', ''))}</li>"
        for x in xrefs
    )
    return f"""
<div class="section-head" id="sec-xrefs">
  <h2>11. Referencias cruzadas</h2>
  <p>{len(xrefs)} referencias a otros expedientes o instrumentos internacionales relacionados.</p>
</div>
<div class="notes-panel" style="margin-bottom:28px;">
  <ul>{items}</ul>
</div>
"""


def build_provenance(data: dict) -> str:
    events = data.get("provenance", []) or []
    if not events:
        return ""
    rows = []
    for p in events:
        ts = esc(p.get("timestamp", "") or "")
        actor = esc(p.get("actor", "") or "")
        op = esc(p.get("operation", "") or "")
        layer = p.get("layer")
        layer_html = "—" if layer is None else esc(layer)
        note = esc(p.get("note", "") or "")
        rows.append(
            f'<tr><td class="prov-ts">{ts}</td>'
            f'<td class="prov-actor">{actor}</td>'
            f'<td class="prov-op">{op}</td>'
            f'<td class="prov-layer">{layer_html}</td>'
            f'<td class="prov-note">{note}</td></tr>'
        )
    return f"""
<div class="section-head" id="sec-provenance">
  <h2>12. Provenance — historial de construcción del expediente</h2>
  <p>Registro de cada operación que ha modificado este bundle: ingestas, enriquecimientos, capas de
  evidencia, revisiones legales humanas y actualizaciones de score. Permite auditar cómo evolucionó el
  análisis y qué cambios fueron manuales.</p>
</div>
<table class="prov-table">
  <thead><tr><th>timestamp</th><th>actor</th><th>operation</th><th>layer</th><th>note</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def build_integrity_section(report: IntegrityReport) -> str:
    if not report.has_issues():
        return """
<div class="section-head" id="sec-integrity">
  <h2>13. Reporte de integridad</h2>
  <p>Sin incidencias detectadas por el validador automático.</p>
</div>
"""
    sev_order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(report.issues, key=lambda i: sev_order.get(i["severity"], 9))
    cards = []
    for i in issues:
        fix_html = f'<div class="issue-fix"><b>Acción sugerida:</b> {esc(i["fix"])}</div>' if i["fix"] else ""
        cards.append(f"""
    <div class="issue sev-{esc(i['severity'])}">
      <div class="issue-code">{esc(i['code'])} · {esc(i['severity'])}</div>
      <div class="issue-title">{esc(i['title'])}</div>
      <div class="issue-detail">{esc(i['detail'])}</div>
      {fix_html}
    </div>""")
    return f"""
<div class="section-head" id="sec-integrity">
  <h2>13. Reporte de integridad</h2>
  <p>{len(issues)} incidencia(s) detectada(s). Alto: {len(report.by_severity('high'))},
  medio: {len(report.by_severity('medium'))}, bajo: {len(report.by_severity('low'))}.</p>
</div>
{''.join(cards)}
"""


def build_footer(data: dict) -> str:
    vid = esc(data.get("violation_id", ""))
    schema = esc(data.get("schema_version", ""))
    return f"""
<div class="page-footer">
  <p><span class="mono">{vid} · schema_version {schema}</span> — Documento generado automáticamente a partir del
  expediente de análisis. Los elementos "contested" y las autoridades "no verificadas" no deben presentarse
  como hechos probados o citas confirmadas.</p>
</div>
"""


# --------------------------------------------------------------------------
# Interactive HTML (verification panels)
# --------------------------------------------------------------------------

VPANEL_SCRIPT = r"""
<script>
(function(){
  var KEY='cl-violation-annotations-v1';
  var store={};
  try{store=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){store={}}
  function save(){try{localStorage.setItem(KEY,JSON.stringify(store))}catch(e){}}
  document.querySelectorAll('[data-field][data-vid]').forEach(function(el){
    var vid=el.dataset.vid,f=el.dataset.field;
    store[vid]=store[vid]||{};
    if(typeof store[vid][f]==='string') el.value=store[vid][f];
    el.addEventListener('input',function(){
      store[vid][f]=el.value;save();if(f==='status') refresh(vid);
    });
    el.addEventListener('change',function(){
      store[vid][f]=el.value;save();if(f==='status') refresh(vid);
    });
  });
  document.querySelectorAll('input[type=file][data-drop]').forEach(function(input){
    var vid=input.dataset.drop,list=document.getElementById('files-'+vid);
    var drop=input.closest('.vdrop');
    function render(files){
      if(!list)return;
      list.innerHTML='';
      store[vid]=store[vid]||{};store[vid].files=store[vid].files||[];
      Array.prototype.forEach.call(files,function(f){
        var li=document.createElement('li');
        li.textContent='• '+f.name+' ('+Math.round(f.size/1024)+' KB)';
        list.appendChild(li);
        if(!store[vid].files.some(function(x){return x.name===f.name&&x.size===f.size}))
          store[vid].files.push({name:f.name,size:f.size,type:f.type,ts:Date.now()});
      });
      save();
    }
    if(store[vid]&&store[vid].files&&list){
      store[vid].files.forEach(function(f){
        var li=document.createElement('li');
        li.textContent='• '+f.name+' ('+Math.round(f.size/1024)+' KB)';
        list.appendChild(li);
      });
    }
    input.addEventListener('change',function(){render(input.files)});
    if(drop){
      ['dragenter','dragover'].forEach(function(ev){drop.addEventListener(ev,function(e){e.preventDefault();drop.classList.add('dragover')})});
      ['dragleave','drop'].forEach(function(ev){drop.addEventListener(ev,function(e){e.preventDefault();drop.classList.remove('dragover')})});
      drop.addEventListener('drop',function(e){if(e.dataTransfer&&e.dataTransfer.files)render(e.dataTransfer.files)});
    }
  });
  function refresh(vid){
    var p=document.querySelector('.vpanel[data-vid="'+vid+'"]');
    if(!p)return;
    var tag=p.querySelector('.vtag');
    var s=(store[vid]&&store[vid].status)||'open';
    tag.classList.remove('status-open','status-inprogress','status-resolved');
    tag.classList.add('status-'+s);
    tag.textContent=s==='inprogress'?'in progress':s;
  }
  document.querySelectorAll('.vpanel').forEach(function(p){refresh(p.dataset.vid)});
})();
</script>
"""


def make_vpanel(vid: str, title: str, problem: str, why: str,
                needs: Iterable[str], status_default: str = "open") -> str:
    needs_html = "".join(f"<li>{esc(n)}</li>" for n in needs)
    return f"""
<details class="vpanel" data-vid="{esc(vid)}">
  <summary><span>{esc(vid)}</span> Verificación / Mejora — {esc(title)}
    <span class="vtag status-{esc(status_default)}">{esc(status_default)}</span></summary>
  <div class="vbody">
    <div class="vblock"><h4>Problema</h4><p>{esc(problem)}</p></div>
    <div class="vblock"><h4>Por qué bloquea</h4><p>{esc(why)}</p></div>
    <div class="vblock"><h4>Qué se necesita</h4><ul>{needs_html}</ul></div>
    <div class="vfields">
      <div class="vfield full">
        <label>Archivos (arrastre o seleccione)</label>
        <label class="vdrop" for="f-{esc(vid)}">Arrastre archivos aquí o haga clic
          <input id="f-{esc(vid)}" type="file" multiple data-drop="{esc(vid)}"></label>
        <ul class="vfiles" id="files-{esc(vid)}"></ul>
      </div>
      <div class="vfield full">
        <label>Pegar información</label>
        <textarea data-field="paste" data-vid="{esc(vid)}"></textarea>
      </div>
      <div class="vfield"><label>Notas</label>
        <textarea data-field="notes" data-vid="{esc(vid)}"></textarea></div>
      <div class="vfield"><label>Razonamiento</label>
        <textarea data-field="reasoning" data-vid="{esc(vid)}"></textarea></div>
    </div>
    <div class="vbar">
      <label style="font-family:var(--mono);font-size:.62rem;text-transform:uppercase;color:var(--text-muted)">Estado:</label>
      <select data-field="status" data-vid="{esc(vid)}">
        <option value="open">open</option>
        <option value="inprogress">in progress</option>
        <option value="resolved">resolved</option>
      </select>
      <span class="vnote">Persistencia local en este navegador.</span>
    </div>
  </div>
</details>
"""


def build_interactive_panels(data: dict, report: IntegrityReport) -> dict[str, str]:
    panels: dict[str, str] = {}

    panels["incident"] = make_vpanel(
        "ANNOT-INCIDENT", "Incidente",
        "El incidente está descrito en campos planos: sin línea de tiempo absoluta verificada, sin identidad jurídica del operador, sin ruta ni horas programada/real, y sin criterio de severidad.",
        "La 'oportunidad' del Art. 3.b LPDC depende del tiempo; 'LATAM Airlines' no identifica persona jurídica para el Art. 2° LPDC; la severidad CRITICAL no está justificada.",
        ["Línea de tiempo absoluta (boarding programado, llamado real, orden, intervención PDI/DGAC, salida).",
         "Razón social y RUT del proveedor.",
         "Rúbrica de severidad.",
         "Fuente y procedencia de cada dato."]
    )
    panels["frameworks"] = make_vpanel(
        "ANNOT-FRAMEWORKS", "Cachés de marcos legales",
        "Las cachés citan hashes y nombres de archivo pero carecen de URL de origen y fecha de descarga. La relación entre el hash declarado en el bundle y el archivo real no está auditada externamente.",
        "Sin URL ni fecha, el texto legal usado para fundamentar los artículos 'establecidos' no es verificable de forma independiente.",
        ["URL de origen oficial (BCN/leychile) por cada framework_code.",
         "Fecha de descarga y versión.",
         "Verificación externa del cache_file_sha256 contra el archivo real.",
         "Confirmación de que los articles_cached cubren los artículos efectivamente citados."]
    )
    panels["base_normativa"] = make_vpanel(
        "ANNOT-BASE", "Base normativa",
        "'Established' mezcla 'texto legal en caché' con 'violación establecida'. El texto del Art. 255 tiene erratas de OCR. 'verified_in_bundle' no equivale a verificación externa (0/27 autoridades). CPCL y LPDC están fusionados bajo un mismo rótulo.",
        "Un juez o contraparte puede desestimar el archivo si se presenta como '3 artículos establecidos' cuando solo hay 3 citas en caché. Las erratas impiden citar textualmente.",
        ["Texto oficial vigente con URL, fecha y hash.",
         "Reetiquetar 'verified_in_bundle' como 'internal_cache — external verification pending'.",
         "Separar CPCL Art. 255 de LPDC Arts. 3.b y 23.",
         "Desglose de elementos por artículo con carga de prueba."]
    )
    panels["elements"] = make_vpanel(
        "ANNOT-ELEMENTS", "Análisis elemento por elemento",
        "Los elementos de tres artículos están mezclados. Los proof_evidence_segments son la única ligadura al hecho; si faltan, el elemento queda huérfano. La nexus_matrix referencia element_id que no existen en element_grids.",
        "Sin separar regímenes, no se puede decidir si el estándar es dolo (CPCL) o negligencia (LPDC). Los IDs huérfanos rompen la trazabilidad.",
        ["Tres matrices separadas (CPCL 255 / LPDC 3.b / LPDC 23).",
         "Por elemento: estándar legal, carga de prueba, evidencia a favor, en contra, prueba faltante, acción siguiente.",
         "Verificar que cada proof_evidence_segments apunte a un segment_id existente.",
         "Corregir nexus_matrix con IDs que existan en element_grids.",
         "Añadir contraargumentos."]
    )
    panels["nexus"] = make_vpanel(
        "ANNOT-NEXUS", "Matriz de nexo",
        "La matriz enlaza hechos, normas y elementos, pero contiene element_id y fact_id huérfanos que rompen la trazabilidad.",
        "Sin trazabilidad hecho→norma→elemento, el análisis no es auditable y las conclusiones por elemento no son defendibles.",
        ["Corregir fact_id que no existan en segments[].segment_id.",
         "Corregir element_id que no existan en element_grids.",
         "Revisar 'strength' y 'nexus_type' con criterio uniforme.",
         "Confirmar que cada enlace tiene un rationale_oneline claro."]
    )
    panels["transcript"] = make_vpanel(
        "ANNOT-TRANSCRIPT", "Transcripción",
        "Sin cadena de custodia, sin hash por audio, sin verificación de hablantes. Traducción y original al mismo nivel visual. 58 segmentos declarados, subconjunto exhibido sin reconciliación. Citas no mapeadas a elementos.",
        "Sin cadena de custodia y sin verificación de hablantes, la transcripción no es utilizable como prueba.",
        ["Registro de evidencia: ID, fuente, hash, duración, idioma, hablante, verificación, elemento mapeado, fiabilidad.",
         "Original y traducción certificada en campos separados.",
         "Verificación de identidad y rol de cada hablante.",
         "Mapeo cita → elemento típico.",
         "Reconciliar los 58 segmentos."]
    )
    panels["confidence"] = make_vpanel(
        "ANNOT-CONFIDENCE", "Puntaje de confianza",
        "Un solo número global mezcla confianza factual, verificación de fuentes y aplicación jurídica. factor = 0.85 es incoherente con 0/27 autoridades verificadas. La fórmula del JSON no es reproducible.",
        "El score no es auditable y puede inducir a sobrevalorar la fiabilidad.",
        ["Sustituir por scores separados: autenticidad, completitud factual, verificación legal, prueba por elemento, readiness externo.",
         "Publicar rúbrica y pesos.",
         "Bajar el factor hasta completar verificación.",
         "Justificar cada cambio en el historial."]
    )
    panels["open_questions"] = make_vpanel(
        "ANNOT-OQ", "Preguntas abiertas",
        "60 preguntas sin dueño, método, fuente, fecha ni impacto. Hay duplicaciones (CONSUMER-CONTRACT/TRANSPORT-CONTRACT, AIRLINE-IDENTITY/LPDC3B-PROVEEDOR, PROVIDER-STATUS-PROVEN/PROVIDER-STATUS-ART23).",
        "No se puede priorizar la investigación ni medir avance.",
        ["Deduplicar y convertir en plan: pregunta / tipo / prioridad / fuente / método / dueño / estado / impacto.",
         "Priorizar: estatus de empleado público, causa justificada, vejación, dolo, nexo causal, protocolo, información oficial."]
    )
    panels["authorities"] = make_vpanel(
        "ANNOT-AUTHORITIES", "Autoridades",
        "Las 27 autoridades están sin verificar, pero algunas se usan como apoyo de proposiciones jurídicas. Hay contradicciones internas (perjuicio vs. no perjuicio; dolo directo vs. eventual). Se mezclan ley, doctrina, comparado y tesis del propio expediente.",
        "Citar autoridades no verificadas o contradictorias puede invalidar el análisis ante un tribunal.",
        ["Verificar cada autoridad contra fuente oficial.",
         "Etiquetar: norma / reglamento / jurisprudencia / doctrina / comparado.",
         "Añadir cita, URL, fecha, jurisdicción (court, rol, decision_date).",
         "Registrar verification_protocol y verification_provenance.",
         "Resolver contradicciones antes de citar."]
    )
    panels["provenance"] = make_vpanel(
        "ANNOT-PROVENANCE", "Provenance",
        "El expediente registra 80+ eventos de construcción pero no hay políticas explícitas de revisión humana que definan qué cambios requieren aprobación.",
        "Sin política de cambios, es imposible auditar quién modificó qué y por qué.",
        ["Definir qué cambios son automáticos y cuáles requieren revisión humana.",
         "Registrar responsable por cada operación legal_audit_human.",
         "Vincular cada cambio de score con su justificación.",
         "Exportar periódicamente el provenance a un almacén inmutable."]
    )
    panels["integrity"] = make_vpanel(
        "ANNOT-INTEGRITY", "Integridad del expediente",
        f"El validador detectó {len(report.issues)} incidencia(s). Ver Sección 13 para detalle.",
        "Rompe la trazabilidad hecho → norma → elemento y con ello la auditabilidad.",
        ["Corregir IDs huérfanos en nexus_matrix.",
         "Reconciliar conteos HTML ↔ JSON ↔ provenance.",
         "Mover candidatos no aplicables a lista de exclusiones.",
         "Registrar cambios de score con justificación."]
    )
    return panels


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_static_html(data: dict, report: IntegrityReport, max_segments: int | None = None) -> str:
    body = "".join([
        build_masthead(data),
        build_stats(data),
        '<div class="main">',
        build_toc(),
        build_incident_box(data),
        build_framework_caches(data),
        build_established_articles(data),
        build_candidate_articles(data),
        build_element_grids(data),
        build_nexus_matrix(data),
        build_transcript(data, max_segments=max_segments),
        build_confidence(data),
        build_open_questions(data),
        build_authorities(data),
        build_cross_references(data),
        build_provenance(data),
        build_integrity_section(report),
        "</div>",
        build_footer(data),
    ])
    title = esc(data.get("violation_id", "violation"))
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>{title} — Case Analysis File</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_interactive_html(data: dict, report: IntegrityReport) -> str:
    panels = build_interactive_panels(data, report)

    body = "".join([
        build_masthead(data),
        build_stats(data),
        '<div class="main">',
        build_toc(),
        '<div class="info-box"><b>Cómo usar este archivo:</b> cada sección tiene un panel '
        '<strong>“+ Verificación / Mejora”</strong>. Ábralo, lea el problema, agregue archivos, pegue texto, '
        'escriba notas o razonamiento, y marque el estado. La información se guarda localmente en este navegador.</div>',
        build_incident_box(data),
        panels["incident"],
        build_framework_caches(data),
        panels["frameworks"],
        build_established_articles(data),
        panels["base_normativa"],
        build_candidate_articles(data),
        build_element_grids(data),
        panels["elements"],
        build_nexus_matrix(data),
        panels["nexus"],
        build_transcript(data),
        panels["transcript"],
        build_confidence(data),
        panels["confidence"],
        build_open_questions(data),
        panels["open_questions"],
        build_authorities(data),
        panels["authorities"],
        build_cross_references(data),
        build_provenance(data),
        panels["provenance"],
        build_integrity_section(report),
        panels["integrity"],
        "</div>",
        build_footer(data),
    ])
    title = esc(data.get("violation_id", "violation"))
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>{title} — Case Analysis File (interactive)</title>
<style>{CSS}</style>
</head>
<body>
{body}
{VPANEL_SCRIPT}
</body>
</html>
"""


# --------------------------------------------------------------------------
# PDF rendering
# --------------------------------------------------------------------------

def render_pdf(html_str: str, base_dir: Path, out_path: Path) -> bool:
    if _HAVE_WEASYPRINT:
        try:
            weasyprint.HTML(string=html_str, base_url=str(base_dir)).write_pdf(str(out_path))
            print(f"[pdf] weasyprint → {out_path}")
            return True
        except Exception as e:
            print(f"[pdf] weasyprint failed: {e}", file=sys.stderr)

    if _HAVE_WKHTMLTOPDF:
        tmp_html = out_path.with_suffix(".wkhtml.html")
        tmp_html.write_text(html_str, encoding="utf-8")
        try:
            subprocess.run(
                ["wkhtmltopdf", "--enable-local-file-access", "--print-media-type",
                 str(tmp_html), str(out_path)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            print(f"[pdf] wkhtmltopdf → {out_path}")
            tmp_html.unlink(missing_ok=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"[pdf] wkhtmltopdf failed: {e.stderr.decode(errors='ignore')[:400]}", file=sys.stderr)
            tmp_html.unlink(missing_ok=True)

    print("[pdf] no PDF backend available (install weasyprint or wkhtmltopdf); "
          "HTML outputs were still written.", file=sys.stderr)
    return False


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a styled case-analysis report (HTML + PDF) from a violation-bundle JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input", help="Path to the violation-bundle JSON file.")
    p.add_argument("output", nargs="?",
                   help="Path to the output PDF (default: input basename + .pdf).")
    p.add_argument("--no-pdf", action="store_true", help="Only write HTML outputs.")
    p.add_argument("--no-interactive", action="store_true",
                   help="Skip writing the interactive HTML with verification panels.")
    p.add_argument("--validate-only", action="store_true",
                   help="Run integrity checks and exit without writing outputs.")
    p.add_argument("--strict", action="store_true",
                   help="Return non-zero exit code if integrity issues are found.")
    p.add_argument("--max-segments", type=int, default=None,
                   help="Cap the number of transcript segments shown (default: all).")

    args = p.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"error: input not found: {in_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in {in_path}: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("error: top-level JSON must be an object", file=sys.stderr)
        return 1

    report = validate(data)
    if report.has_issues():
        print(f"[validate] {len(report.issues)} issue(s) found:", file=sys.stderr)
        for i in report.issues:
            print(f"  - [{i['severity']}] {i['code']}: {i['title']}", file=sys.stderr)
    else:
        print("[validate] no integrity issues detected.")

    if args.validate_only:
        return 2 if (args.strict and report.has_issues()) else 0

    # Static HTML (with max-segments cap if requested)
    static_html = build_static_html(data, report, max_segments=args.max_segments)
    static_path = in_path.with_suffix(".report.html")
    static_path.write_text(static_html, encoding="utf-8")
    print(f"[html] static → {static_path}")

    if not args.no_interactive:
        interactive_html = build_interactive_html(data, report)
        inter_path = in_path.with_suffix(".interactive.html")
        inter_path.write_text(interactive_html, encoding="utf-8")
        print(f"[html] interactive → {inter_path}")

    if not args.no_pdf:
        out_path = Path(args.output) if args.output else in_path.with_suffix(".pdf")
        ok = render_pdf(static_html, in_path.parent, out_path)
        if not ok:
            return 3

    if args.strict and report.has_issues():
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())