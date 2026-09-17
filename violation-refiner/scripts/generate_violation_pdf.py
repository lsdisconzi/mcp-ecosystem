#!/usr/bin/env python3
"""
generate_violation_pdf.py

Turn a "violation bundle" JSON file (schema_version 3.0 shape — as used by
CL-030: incident / established_articles / candidate_articles / element_grids /
nexus_matrix / segments / confidence / open_questions / authorities /
cross_references / provenance) into a styled case-analysis file.

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
# CSS — same design system as CL-030, plus print rules and verification panel
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
a{color:var(--accent);text-decoration:none}
code{font-family:var(--mono);font-size:.85em;color:var(--accent);background:var(--bg-surface);padding:1px 6px;border-radius:2px}

.masthead{border-bottom:1px solid var(--border);padding:32px 0 24px}
.masthead-inner{padding:0 32px}
.masthead-badge{display:inline-block;font-family:var(--mono);font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--status-flag);border:1px solid var(--status-flag);background:var(--status-flag-dim);padding:5px 12px;border-radius:2px;margin-bottom:16px}
.masthead h1{font-family:var(--serif);font-size:1.7rem;font-weight:600;line-height:1.28;margin-bottom:10px}
.masthead-sub{font-size:.9rem;color:var(--text-secondary);max-width:760px;line-height:1.7;margin-bottom:14px}
.masthead-caveat{font-family:var(--mono);font-size:.66rem;color:var(--status-analysis);background:var(--status-analysis-dim);border:1px solid var(--status-analysis);display:inline-block;padding:8px 12px;border-radius:3px;max-width:760px}

.stats-bar{background:var(--bg-card);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.stats-inner{padding:0 32px;display:flex;flex-wrap:wrap}
.stat-item{flex:1 1 150px;padding:16px 14px;border-right:1px solid var(--border)}
.stat-item:last-child{border-right:none}
.stat-val{font-family:var(--mono);font-size:.95rem;font-weight:600}
.stat-label{font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px}

.main{padding:0 32px}
.section-head{padding:30px 0 12px;border-bottom:1px solid var(--border);margin-bottom:16px}
.section-head h2{font-family:var(--serif);font-size:1.2rem;font-weight:600;padding-bottom:10px}
.section-head p{color:var(--text-secondary);font-size:.84rem;padding-bottom:10px;max-width:760px}
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

.notes-panel{background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:18px 22px;margin-top:10px}
.notes-label{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--text-secondary);margin-bottom:12px}
.oq-item{border-bottom:1px solid var(--border);padding:10px 0;font-size:.82rem}
.oq-item:last-child{border-bottom:none}
.oq-id{font-family:var(--mono);font-size:.66rem;color:var(--accent);margin-right:8px}
.oq-priority{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;padding:2px 7px;border-radius:2px;border:1px solid var(--border-strong);color:var(--text-muted);margin-left:6px}
.oq-method{font-size:.72rem;color:var(--text-muted);margin-top:4px;font-style:italic}
.oq-dup{color:var(--status-flag);font-family:var(--mono);font-size:.62rem;margin-left:6px}

.jurisdiction-pill{background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:12px 16px;margin-bottom:8px}
.jurisdiction-name{font-family:var(--mono);font-size:.72rem;color:var(--accent);margin-bottom:4px}
.jurisdiction-laws{font-size:.8rem;color:var(--text-secondary);line-height:1.6}
.jurisdiction-meta{font-family:var(--mono);font-size:.64rem;color:var(--text-muted);margin-top:6px}
.verified-tag{font-family:var(--mono);font-size:.6rem;padding:2px 8px;border-radius:2px;text-transform:uppercase}
.verified-yes{background:var(--status-note-dim);color:var(--status-note)}
.verified-no{background:var(--status-flag-dim);color:var(--status-flag)}

.page-footer{border-top:1px solid var(--border);padding:22px 32px;margin-top:36px}
.page-footer p{font-size:.72rem;color:var(--text-muted);line-height:1.8}
.page-footer .mono{font-family:var(--mono)}

table.confidence-table{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:8px;margin-bottom:28px}
table.confidence-table th,table.confidence-table td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border)}
table.confidence-table th{font-family:var(--mono);font-size:.64rem;text-transform:uppercase;color:var(--text-muted);letter-spacing:.05em}

/* Integrity + verification map */
.issue{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--status-flag);border-radius:3px;padding:12px 16px;margin-bottom:8px;font-size:.82rem}
.issue.sev-high{border-left-color:var(--status-flag)}
.issue.sev-medium{border-left-color:var(--status-analysis)}
.issue.sev-low{border-left-color:var(--status-note)}
.issue-code{font-family:var(--mono);font-size:.66rem;color:var(--status-flag);text-transform:uppercase;letter-spacing:.04em}
.issue-title{font-weight:600;margin-top:2px}
.issue-detail{color:var(--text-secondary);margin-top:4px;line-height:1.6}
.issue-fix{color:var(--text-secondary);margin-top:6px;font-size:.78rem}
.issue-fix b{color:var(--text-primary)}

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
.vblock ul{margin:4px 0 4px 18px}
.vblock li{margin:3px 0}
.vfields{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.vfield{display:flex;flex-direction:column;gap:4px}
.vfield.full{grid-column:1/-1}
.vfield label{font-family:var(--mono);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}
.vfield textarea,.vfield select,.vfield input[type=text]{font-family:var(--sans);font-size:.8rem;color:var(--text-primary);background:var(--bg-card);border:1px solid var(--border-strong);border-radius:3px;padding:8px 10px;resize:vertical;min-height:38px;line-height:1.5}
.vfield textarea{min-height:72px}
.vdrop{border:1.5px dashed var(--border-strong);border-radius:3px;padding:12px 14px;text-align:center;font-family:var(--mono);font-size:.68rem;color:var(--text-muted);background:var(--bg-card);cursor:pointer}
.vdrop input{display:none}
.vfiles{margin-top:6px;font-family:var(--mono);font-size:.68rem;color:var(--text-secondary)}
.vfiles li{margin:2px 0;list-style:none}
.vbar{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.vbar select{font-family:var(--mono);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;padding:6px 8px;border:1px solid var(--border-strong);border-radius:3px;background:var(--bg-card);color:var(--text-secondary)}
.vnote{font-size:.7rem;color:var(--text-muted);font-style:italic;margin-top:8px}

@media print{
  .vpanel{display:none}
  .masthead,.stats-bar,.page-footer{page-break-inside:avoid}
  .section-head{page-break-after:avoid}
  .evidence-card,.transcript-segment,.jurisdiction-pill,.issue{page-break-inside:avoid}
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

    # --- referenced element ids exist -------------------------------------
    grid_ids: set[str] = set()
    grid_article_ids: set[str] = set()
    for g in data.get("element_grids", []) or []:
        grid_article_ids.add(g.get("article_id", ""))
        for e in g.get("elements", []) or []:
            eid = e.get("element_id")
            if eid:
                grid_ids.add(eid)

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

    # --- nexus references articles that exist -----------------------------
    for n in data.get("nexus_matrix", []) or []:
        nid = n.get("norm_id")
        if nid and grid_article_ids and nid not in grid_article_ids:
            r.add(
                "INTEGRITY-NEXUS-UNKNOWN-ARTICLE", "medium",
                "nexus_matrix references a norm_id with no matching element grid",
                f"norm_id = {nid}.",
                "Either add an element grid for this article or remove the nexus rows."
            )
            break

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
        # if factor is supposed to be 0.85 + 0.15*ratio, it should be <= 1.0 and >= 0.85
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


def build_stats(data: dict) -> str:
    conf = data.get("confidence", {}) or {}
    val = conf.get("value")
    conf_str = f"{val:.2f} / 1.00" if isinstance(val, (int, float)) else "n/a"

    n_articles = len(data.get("established_articles", []) or [])
    n_candidates = len(data.get("candidate_articles", []) or [])
    n_segments = len(data.get("segments", []) or [])
    n_open = len(data.get("open_questions", []) or [])
    auths = data.get("authorities", []) or []
    n_auth = len(auths)
    n_auth_verified = sum(1 for a in auths if a.get("verified") is True)

    items = [
        (conf_str, "Confidence Score"),
        (str(n_articles), "Established Articles"),
        (str(n_candidates), "Candidate Articles"),
        (str(n_segments), "Evidence Segments"),
        (str(n_open), "Open Questions"),
        (f"{n_auth_verified} / {n_auth}", "Authorities Verified"),
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
    rows = "".join(f"<div><b>{esc(k)}:</b> {esc(v)}</div>" for k, v in inc.items())
    return f"""
<div class="section-head"><h2>1. Incident</h2></div>
<div class="info-box">{rows}</div>
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
        duty = esc(art.get("duty_bearer", ""))
        applic = esc(art.get("applicability", ""))
        fw = esc(art.get("framework_code", ""))
        cache = esc(art.get("framework_cache_status", ""))
        cards.append(f"""
    <div class="evidence-card status-strong">
      <div class="ev-head"><div class="ev-body">
        <h3>{name}</h3>
        <div class="ev-sub">Sujeto obligado: {duty} · Framework: {fw} · Aplicabilidad: {applic}</div>
      </div></div>
      <div class="ev-summary">{excerpt}</div>
      <div class="ev-provisions">{aid} · framework_cache: {cache}</div>
    </div>""")
    return f"""
<div class="section-head">
  <h2>2. Base normativa — artículos "establecidos"</h2>
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
<div class="section-head">
  <h2>2.b. Artículos candidatos</h2>
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
        # weighted score if present
        cards = []
        for elem in elements:
            label = esc(elem.get("label", elem.get("element_id", "")))
            status = elem.get("proof_status", "missing")
            cls = status_class(status)
            argument = esc(elem.get("argument_es") or elem.get("argument_en") or "")
            weaknesses = as_list(elem.get("weaknesses"))
            oqs = as_list(elem.get("open_questions"))
            basis = esc(elem.get("doctrinal_basis", ""))

            weak_html = ""
            if weaknesses:
                items = "".join(f"<li>{esc(w)}</li>" for w in weaknesses)
                weak_html = f'<div class="ev-weak"><b>Debilidades:</b><ul>{items}</ul></div>'

            oq_html = ""
            if oqs:
                items = "".join(f"<li>{esc(q)}</li>" for q in oqs)
                oq_html = f'<div class="ev-provisions"><b>Preguntas abiertas:</b><ul>{items}</ul></div>'

            basis_html = f'<div class="ev-provisions">Base doctrinal: {basis}</div>' if basis else ""

            cards.append(f"""
    <div class="evidence-card status-{cls}">
      <div class="ev-head">
        <h3>{label}</h3>
        <span class="ev-type type-{cls}">{esc(status)}</span>
      </div>
      <div class="ev-summary">{argument}</div>
      {basis_html}
      {weak_html}
      {oq_html}
    </div>""")
        sections.append(f"""
<div class="subhead">{article_id} — {article_short}</div>
<div class="evidence-grid" style="margin-bottom:18px;">{''.join(cards)}</div>
""")
    return f"""
<div class="section-head">
  <h2>3. Análisis elemento por elemento</h2>
  <p>Estado de prueba por elemento típico. "Established"/"strong" indica respaldo documental directo;
     "contested" indica que la calificación jurídica final permanece abierta.</p>
</div>
{''.join(sections)}
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
        rows.append(f"""
    <div class="transcript-segment {cls}">
      <div class="seg-time">{esc(speaker)} · {t0}–{t1} · {sid}</div>
      <div class="seg-text">"{verbatim}"</div>
      <div class="seg-text-en">{translation}</div>
      {role_html}
      {notes_html}
    </div>""")
    return f"""
<div class="section-head">
  <h2>4. Evidencia de la transcripción</h2>
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

    rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in comps.items())
    if factor is not None:
        rows += f"<tr><td>Authorities verification factor</td><td>{esc(factor)}</td></tr>"
    if value is not None:
        rows += f"<tr><td><strong>Confianza global</strong></td><td><strong>{esc(value)}</strong></td></tr>"
    formula_html = f'<p style="font-family:var(--mono);font-size:.7rem;color:var(--text-muted);margin-top:8px">{formula}</p>' if formula else ""

    return f"""
<div class="section-head"><h2>5. Puntaje de confianza</h2></div>
<table class="confidence-table">
  <tr><th>Componente</th><th>Valor</th></tr>
  {rows}
</table>
{formula_html}
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
        dup = f'<span class="oq-dup">×{counts[oq.get("id")]}</span>' if counts.get(oq.get("id"), 0) > 1 else ""
        method_html = f'<div class="oq-method">{method}</div>' if method else ""
        items.append(
            f'<div class="oq-item"><span class="oq-id">{oid}</span>{q}'
            f'<span class="oq-priority">{pr}</span>{dup}{method_html}</div>'
        )
    return f"""
<div class="section-head">
  <h2>6. Preguntas abiertas (verificación pendiente)</h2>
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
        risk_html = f'<div class="jurisdiction-meta">riesgo: {risk}</div>' if risk else ""
        query_html = f'<div class="jurisdiction-meta">query: {query}</div>' if query else ""
        pills.append(f"""
    <div class="jurisdiction-pill">
      <div class="jurisdiction-name">{aid} <span class="verified-tag {tag_cls}">{tag_txt}</span></div>
      <div class="jurisdiction-laws">{proposition or "—"}</div>
      <div class="jurisdiction-meta">tipo: {typ}</div>
      {risk_html}
      {query_html}
    </div>""")
    return f"""
<div class="section-head">
  <h2>7. Autoridades citadas</h2>
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
<div class="section-head">
  <h2>8. Referencias cruzadas</h2>
</div>
<div class="notes-panel" style="margin-bottom:28px;">
  <ul style="margin-left:18px;font-size:.82rem;color:var(--text-secondary);line-height:1.7">{items}</ul>
</div>
"""


def build_integrity_section(report: IntegrityReport) -> str:
    if not report.has_issues():
        return """
<div class="section-head">
  <h2>9. Reporte de integridad</h2>
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
<div class="section-head">
  <h2>9. Reporte de integridad</h2>
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
    """Return a mapping section_key -> HTML of a verification panel for that section."""
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
        "Los elementos de tres artículos están mezclados. No hay matriz elemento↔estándar↔prueba↔acción. La nexus_matrix referencia element_id que no existen en element_grids.",
        "Sin separar regímenes, no se puede decidir si el estándar es dolo (CPCL) o negligencia (LPDC). Los IDs huérfanos rompen la trazabilidad.",
        ["Tres matrices separadas (CPCL 255 / LPDC 3.b / LPDC 23).",
         "Por elemento: estándar legal, carga de prueba, evidencia a favor, en contra, prueba faltante, acción siguiente.",
         "Corregir nexus_matrix con IDs que existan en element_grids.",
         "Añadir contraargumentos."]
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
         "Bajar el factor hasta completar verificación."]
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
         "Añadir cita, URL, fecha, jurisdicción.",
         "Resolver contradicciones antes de citar."]
    )
    panels["integrity"] = make_vpanel(
        "ANNOT-INTEGRITY", "Integridad del expediente",
        f"El validador detectó {len(report.issues)} incidencia(s). Ver Sección 9 para detalle.",
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

def build_static_html(data: dict, report: IntegrityReport) -> str:
    body = "".join([
        build_masthead(data),
        build_stats(data),
        '<div class="main">',
        build_incident_box(data),
        build_established_articles(data),
        build_candidate_articles(data),
        build_element_grids(data),
        build_transcript(data),
        build_confidence(data),
        build_open_questions(data),
        build_authorities(data),
        build_cross_references(data),
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
        '<div class="info-box"><b>Cómo usar este archivo:</b> cada sección tiene un panel '
        '<strong>“+ Verificación / Mejora”</strong>. Ábralo, lea el problema, agregue archivos, pegue texto, '
        'escriba notas o razonamiento, y marque el estado. La información se guarda localmente en este navegador.</div>',
        build_incident_box(data),
        panels["incident"],
        build_established_articles(data),
        panels["base_normativa"],
        build_candidate_articles(data),
        build_element_grids(data),
        panels["elements"],
        build_transcript(data),
        panels["transcript"],
        build_confidence(data),
        panels["confidence"],
        build_open_questions(data),
        panels["open_questions"],
        build_authorities(data),
        panels["authorities"],
        build_cross_references(data),
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
    """Render HTML to PDF. Returns True on success."""
    # Preferred: WeasyPrint
    if _HAVE_WEASYPRINT:
        try:
            weasyprint.HTML(string=html_str, base_url=str(base_dir)).write_pdf(str(out_path))
            print(f"[pdf] weasyprint → {out_path}")
            return True
        except Exception as e:
            print(f"[pdf] weasyprint failed: {e}", file=sys.stderr)

    # Fallback: wkhtmltopdf
    if _HAVE_WKHTMLTOPDF:
        tmp_html = out_path.with_suffix(".wkhtml.html")
        tmp_html.write_text(html_str, encoding="utf-8")
        try:
            subprocess.run(
                ["wkhtmltopdf", "--enable-local-file-access", "--print-media-type",
                 str(tmp_html), str(out_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
                   help="Cap the number of transcript segments shown in the PDF (default: all).")

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

    # Validate
    report = validate(data)
    if report.has_issues():
        print(f"[validate] {len(report.issues)} issue(s) found:", file=sys.stderr)
        for i in report.issues:
            print(f"  - [{i['severity']}] {i['code']}: {i['title']}", file=sys.stderr)
    else:
        print("[validate] no integrity issues detected.")

    if args.validate_only:
        return 2 if (args.strict and report.has_issues()) else 0

    # Static HTML
    static_html = build_static_html(data, report)
    static_path = in_path.with_suffix(".report.html")
    static_path.write_text(static_html, encoding="utf-8")
    print(f"[html] static → {static_path}")

    # Interactive HTML
    if not args.no_interactive:
        interactive_html = build_interactive_html(data, report)
        inter_path = in_path.with_suffix(".interactive.html")
        inter_path.write_text(interactive_html, encoding="utf-8")
        print(f"[html] interactive → {inter_path}")

    # PDF
    if not args.no_pdf:
        out_path = Path(args.output) if args.output else in_path.with_suffix(".pdf")
        # Build a print-oriented HTML (same as static but with max-segments cap applied)
        if args.max_segments is not None:
            # rebuild with cap
            body = "".join([
                build_masthead(data),
                build_stats(data),
                '<div class="main">',
                build_incident_box(data),
                build_established_articles(data),
                build_candidate_articles(data),
                build_element_grids(data),
                build_transcript(data, max_segments=args.max_segments),
                build_confidence(data),
                build_open_questions(data),
                build_authorities(data),
                build_cross_references(data),
                build_integrity_section(report),
                "</div>",
                build_footer(data),
            ])
            title = esc(data.get("violation_id", "violation"))
            pdf_html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{title}</title>
<style>{CSS}</style></head><body>{body}</body></html>"""
        else:
            pdf_html = static_html

        ok = render_pdf(pdf_html, in_path.parent, out_path)
        if not ok:
            # HTML outputs still written; use exit code 3 to signal partial success
            return 3

    if args.strict and report.has_issues():
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())