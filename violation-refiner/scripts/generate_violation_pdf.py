#!/usr/bin/env python3
"""
generate_violation_pdf.py

Turns a "violation bundle" JSON file (schema_version 3.0 style — the same
shape as CL-030: incident / established_articles / element_grids / segments /
confidence / open_questions / authorities / cross_references) into a styled
PDF case-analysis file, using the same visual design as the CL-030 report.

Usage:
    python3 generate_violation_pdf.py input.json output.pdf
    python3 generate_violation_pdf.py input.json               # writes input.pdf next to it

Requires: wkhtmltopdf on PATH (already installed in this environment).
No third-party Python packages are required — only the standard library.
"""

import sys
import json
import html
import subprocess
from pathlib import Path

import weasyprint

# --------------------------------------------------------------------------
# CSS — same design system as the CL-030 report
# --------------------------------------------------------------------------

CSS = """
:root {
  --bg-primary: #f8f7f4; --bg-card: #ffffff; --bg-card-hover: #f2f0ea;
  --bg-surface: #f1efe8; --border: #e1ddd1; --border-strong: #c7c1b0;
  --text-primary: #1b1c1e; --text-secondary: #52555c; --text-muted: #8a8b87;
  --accent: #24405f; --accent-dim: rgba(36, 64, 95, 0.07);
  --status-flag: #7a3733; --status-flag-dim: rgba(122, 55, 51, 0.08);
  --status-analysis: #8a6a2c; --status-analysis-dim: rgba(138, 106, 44, 0.09);
  --status-note: #3f6b4f; --status-note-dim: rgba(63, 107, 79, 0.08);
  --mono: 'JetBrains Mono', 'Courier New', monospace;
  --serif: 'Source Serif 4', Georgia, serif;
  --sans: 'Inter', -apple-system, sans-serif;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: var(--sans); background: var(--bg-primary); color: var(--text-primary); line-height:1.6; }
a { color: var(--accent); text-decoration:none; }
code { font-family: var(--mono); font-size:0.85em; color: var(--accent); background: var(--bg-surface); padding:1px 6px; border-radius:2px; }

.masthead { border-bottom:1px solid var(--border); padding:32px 0 24px; }
.masthead-inner { padding:0 32px; }
.masthead-badge { display:inline-block; font-family:var(--mono); font-size:0.68rem; letter-spacing:0.08em; text-transform:uppercase; color:var(--status-flag); border:1px solid var(--status-flag); background:var(--status-flag-dim); padding:5px 12px; border-radius:2px; margin-bottom:16px; }
.masthead h1 { font-family: var(--serif); font-size:1.7rem; font-weight:600; line-height:1.28; margin-bottom:10px; }
.masthead-sub { font-size:0.9rem; color:var(--text-secondary); max-width:760px; line-height:1.7; margin-bottom:14px; }
.masthead-caveat { font-family: var(--mono); font-size:0.66rem; color: var(--status-analysis); background: var(--status-analysis-dim); border:1px solid var(--status-analysis); display:inline-block; padding:8px 12px; border-radius:3px; max-width:760px; }

.stats-bar { background: var(--bg-card); border-top:1px solid var(--border); border-bottom:1px solid var(--border); }
.stats-inner { padding:0 32px; display:flex; flex-wrap:wrap; }
.stat-item { flex:1 1 150px; padding:16px 14px; border-right:1px solid var(--border); }
.stat-item:last-child { border-right:none; }
.stat-val { font-family:var(--mono); font-size:0.95rem; font-weight:600; }
.stat-label { font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.06em; margin-top:4px; }

.main { padding:0 32px; }
.section-head { padding:30px 0 12px; border-bottom:1px solid var(--border); margin-bottom:16px; }
.section-head h2 { font-family:var(--serif); font-size:1.2rem; font-weight:600; padding-bottom:10px; }
.section-head p { color:var(--text-secondary); font-size:0.84rem; padding-bottom:10px; max-width:760px; }

.transcript-list { display:flex; flex-direction:column; gap:6px; padding-bottom:8px; }
.transcript-segment { background:var(--bg-card); border:1px solid var(--border); border-left:3px solid var(--border-strong); border-radius:3px; padding:11px 16px; page-break-inside:avoid; }
.transcript-segment.seg-passenger { border-left-color: var(--accent); }
.transcript-segment.seg-other { border-left-color: var(--status-analysis); border-left-style:dashed; }
.seg-time { font-family:var(--mono); font-size:0.66rem; color:var(--text-muted); margin-bottom:3px; }
.seg-speaker { font-size:0.76rem; font-weight:600; margin-bottom:5px; }
.seg-text { font-size:0.84rem; color:var(--text-secondary); line-height:1.6; font-style:italic; }
.seg-text-en { font-size:0.78rem; color:var(--text-muted); margin-top:3px; }

.evidence-grid { display:flex; flex-direction:column; gap:10px; }
.evidence-card { background:var(--bg-card); border:1px solid var(--border); border-left:3px solid var(--border-strong); border-radius:3px; padding:16px 20px; page-break-inside:avoid; }
.evidence-card.status-established, .evidence-card.status-strong { border-left-color: var(--status-flag); }
.evidence-card.status-contested { border-left-color: var(--status-analysis); }
.evidence-card.status-missing { border-left-color: var(--border-strong); }
.ev-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:8px; }
.ev-body h3 { font-size:0.9rem; font-weight:600; }
.ev-sub { font-family:var(--mono); font-size:0.68rem; color:var(--text-muted); margin-top:2px;}
.ev-type { font-family:var(--mono); font-size:0.6rem; padding:3px 9px; border-radius:2px; text-transform:uppercase; letter-spacing:0.05em; font-weight:600; white-space:nowrap; }
.type-established, .type-strong { background:var(--status-flag-dim); color:var(--status-flag); }
.type-contested { background:var(--status-analysis-dim); color:var(--status-analysis); }
.type-missing, .type-unverified { background:var(--bg-surface); color:var(--text-muted); border:1px solid var(--border-strong); }
.ev-summary { font-size:0.82rem; color:var(--text-secondary); line-height:1.65; margin-top:6px; }
.ev-weak { font-size:0.76rem; color:var(--status-flag); margin-top:8px; padding-top:8px; border-top:1px dashed var(--border); }
.ev-provisions { font-family:var(--mono); font-size:0.66rem; color:var(--text-muted); margin-top:8px; }

.notes-panel { background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:18px 22px; margin-top:10px; }
.notes-label { font-family:var(--mono); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.07em; color:var(--text-secondary); margin-bottom:12px; }
.oq-item { border-bottom:1px solid var(--border); padding:10px 0; font-size:0.82rem; }
.oq-item:last-child { border-bottom:none; }
.oq-id { font-family:var(--mono); font-size:0.66rem; color:var(--accent); margin-right:8px; }
.oq-priority { font-family:var(--mono); font-size:0.6rem; text-transform:uppercase; padding:2px 7px; border-radius:2px; border:1px solid var(--border-strong); color:var(--text-muted); margin-left:6px; }

.jurisdiction-pill { background:var(--bg-card); border:1px solid var(--border); border-radius:3px; padding:12px 16px; margin-bottom:8px; }
.jurisdiction-name { font-family:var(--mono); font-size:0.72rem; color:var(--accent); margin-bottom:4px; }
.jurisdiction-laws { font-size:0.8rem; color:var(--text-secondary); line-height:1.6; }
.verified-tag { font-family:var(--mono); font-size:0.6rem; padding:2px 8px; border-radius:2px; text-transform:uppercase; }
.verified-yes { background: var(--status-note-dim); color: var(--status-note); }
.verified-no { background: var(--status-flag-dim); color: var(--status-flag); }

.page-footer { border-top:1px solid var(--border); padding:22px 32px; margin-top:36px; }
.page-footer p { font-size:0.72rem; color:var(--text-muted); line-height:1.8; }
.page-footer .mono { font-family:var(--mono); }

table.confidence-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-top:8px; margin-bottom: 28px;}
table.confidence-table th, table.confidence-table td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--border); }
table.confidence-table th { font-family:var(--mono); font-size:0.64rem; text-transform:uppercase; color:var(--text-muted); letter-spacing:0.05em; }

.info-box { background:var(--bg-card); border:1px solid var(--border); border-radius:3px; padding:14px 20px; margin-bottom:24px; font-size:0.84rem; color:var(--text-secondary); }
.info-box b { color: var(--text-primary); }
"""

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def esc(value):
    """HTML-escape any scalar, tolerating None."""
    if value is None:
        return ""
    return html.escape(str(value))


PROOF_STATUS_CLASS = {
    "established": "established",
    "strong": "strong",
    "contested": "contested",
}


def status_class(proof_status):
    return PROOF_STATUS_CLASS.get((proof_status or "").lower(), "missing")


def fmt_offset(seconds):
    if seconds is None:
        return "?"
    seconds = float(seconds)
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def speaker_seg_class(speaker):
    speaker = (speaker or "").lower()
    if speaker == "passenger":
        return "seg-passenger"
    return "seg-other"


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------

def build_masthead(data):
    title = esc(data.get("title") or data.get("violation_id", "Untitled violation"))
    vid = esc(data.get("violation_id", ""))
    severity = esc((data.get("severity") or "UNKNOWN").upper())
    incident = data.get("incident", {}) or {}
    loc = esc(incident.get("location", ""))
    date = esc(incident.get("date", ""))
    flight = esc(incident.get("flight", ""))
    operator = esc(incident.get("operator", ""))

    sub_bits = [b for b in [loc, date, flight, operator] if b]
    sub = " · ".join(sub_bits)

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


def build_stats(data):
    confidence = data.get("confidence", {}) or {}
    conf_val = confidence.get("value")
    conf_str = f"{conf_val:.2f} / 1.00" if isinstance(conf_val, (int, float)) else "n/a"

    n_articles = len(data.get("established_articles", []) or [])
    n_segments = len(data.get("segments", []) or [])
    n_open = len(data.get("open_questions", []) or [])
    authorities = data.get("authorities", []) or []
    n_auth = len(authorities)
    n_auth_verified = sum(1 for a in authorities if a.get("verified") is True)

    items = [
        (conf_str, "Confidence Score"),
        (str(n_articles), "Established Articles"),
        (str(n_segments), "Evidence Segments"),
        (str(n_open), "Open Questions"),
        (f"{n_auth_verified} / {n_auth}", "Authorities Verified"),
    ]
    cells = "".join(
        f'<div class="stat-item"><div class="stat-val">{esc(v)}</div><div class="stat-label">{esc(l)}</div></div>'
        for v, l in items
    )
    return f'<div class="stats-bar"><div class="stats-inner">{cells}</div></div>'


def build_incident_box(data):
    incident = data.get("incident", {}) or {}
    if not incident:
        return ""
    rows = "".join(
        f"<div><b>{esc(k)}:</b> {esc(v)}</div>"
        for k, v in incident.items()
    )
    return f"""
<div class="section-head"><h2>1. Incident</h2></div>
<div class="info-box">{rows}</div>
"""


def build_established_articles(data):
    articles = data.get("established_articles", []) or []
    if not articles:
        return ""

    cards = []
    for art in articles:
        aid = esc(art.get("article_id", ""))
        name = esc(art.get("article_name", art.get("article_id", "")))
        excerpt = esc(art.get("verbatim_excerpt", ""))
        duty = esc(art.get("duty_bearer", ""))
        applic = esc(art.get("applicability", ""))
        framework = esc(art.get("framework_code", ""))
        cache_status = esc(art.get("framework_cache_status", ""))
        cards.append(f"""
    <div class="evidence-card status-strong">
      <div class="ev-head">
        <div class="ev-body">
          <h3>{name}</h3>
          <div class="ev-sub">Sujeto obligado: {duty} · Framework: {framework} · Aplicabilidad: {applic}</div>
        </div>
      </div>
      <div class="ev-summary">{excerpt}</div>
      <div class="ev-provisions">{aid} · framework_cache: {cache_status}</div>
    </div>""")

    return f"""
<div class="section-head">
  <h2>2. Base normativa — artículos establecidos</h2>
  <p>Artículos que alcanzan el estado "established" en el expediente.</p>
</div>
<div class="evidence-grid" style="margin-bottom:24px;">{''.join(cards)}</div>
"""


def build_element_grids(data):
    grids = data.get("element_grids", []) or []
    if not grids:
        return ""

    cards = []
    for grid in grids:
        for elem in grid.get("elements", []) or []:
            label = esc(elem.get("label", elem.get("element_id", "")))
            status = elem.get("proof_status", "missing")
            cls = status_class(status)
            argument = esc(elem.get("argument_es") or elem.get("argument_en") or "")
            weaknesses = elem.get("weaknesses") or []
            oqs = elem.get("open_questions") or []

            weak_html = ""
            if weaknesses:
                weak_text = " · ".join(esc(w) for w in weaknesses)
                weak_html = f'<div class="ev-weak">Debilidad señalada: {weak_text}</div>'

            oq_html = ""
            if oqs:
                oq_html = f'<div class="ev-provisions">Preguntas abiertas: {esc(", ".join(oqs))}</div>'

            cards.append(f"""
    <div class="evidence-card status-{cls}">
      <div class="ev-head">
        <h3>{label}</h3>
        <span class="ev-type type-{cls}">{esc(status)}</span>
      </div>
      <div class="ev-summary">{argument}</div>
      {weak_html}
      {oq_html}
    </div>""")

    return f"""
<div class="section-head">
  <h2>3. Análisis elemento por elemento</h2>
  <p>Estado de prueba por elemento típico. "Established"/"strong" indica respaldo documental directo;
     "contested" indica que la calificación jurídica final permanece abierta.</p>
</div>
<div class="evidence-grid" style="margin-bottom:24px;">{''.join(cards)}</div>
"""


def build_transcript(data, max_segments=60):
    segments = data.get("segments", []) or []
    if not segments:
        return ""

    shown = segments[:max_segments]
    note = ""
    if len(segments) > max_segments:
        note = f'<p>Mostrando {max_segments} de {len(segments)} segmentos citados en el expediente.</p>'

    rows = []
    for seg in shown:
        speaker = seg.get("speaker", "")
        cls = speaker_seg_class(speaker)
        t0 = fmt_offset(seg.get("audio_offset_start"))
        t1 = fmt_offset(seg.get("audio_offset_end"))
        seg_id = esc(seg.get("segment_id", ""))
        verbatim = esc(seg.get("verbatim_es", ""))
        translation = esc(seg.get("translation_en", ""))
        rows.append(f"""
    <div class="transcript-segment {cls}">
      <div class="seg-time">{esc(speaker)} · {t0}–{t1} · {seg_id}</div>
      <div class="seg-text">"{verbatim}"</div>
      <div class="seg-text-en">{translation}</div>
    </div>""")

    return f"""
<div class="section-head">
  <h2>4. Evidencia de la transcripción</h2>
  {note}
</div>
<div class="transcript-list" style="margin-bottom:24px;">{''.join(rows)}</div>
"""


def build_confidence(data):
    confidence = data.get("confidence", {}) or {}
    if not confidence:
        return ""
    components = confidence.get("components", {}) or {}
    factor = confidence.get("authorities_verification_factor")
    value = confidence.get("value")

    rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in components.items()
    )
    factor_row = f"<tr><td>Authorities verification factor</td><td>{esc(factor)}</td></tr>" if factor is not None else ""
    total_row = f"<tr><td><strong>Confianza global del expediente</strong></td><td><strong>{esc(value)}</strong></td></tr>" if value is not None else ""

    return f"""
<div class="section-head"><h2>5. Puntaje de confianza</h2></div>
<table class="confidence-table">
  <tr><th>Componente</th><th>Valor</th></tr>
  {rows}
  {factor_row}
  {total_row}
</table>
"""


def build_open_questions(data):
    oqs = data.get("open_questions", []) or []
    if not oqs:
        return ""

    items = []
    for oq in oqs:
        oid = esc(oq.get("id", ""))
        question = esc(oq.get("question", ""))
        priority = esc(oq.get("priority", ""))
        items.append(
            f'<div class="oq-item"><span class="oq-id">{oid}</span>{question}'
            f'<span class="oq-priority">{priority}</span></div>'
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


def build_authorities(data):
    authorities = data.get("authorities", []) or []
    if not authorities:
        return ""

    n_verified = sum(1 for a in authorities if a.get("verified") is True)

    pills = []
    for a in authorities:
        aid = esc(a.get("authority_id", ""))
        verified = a.get("verified") is True
        tag_cls = "verified-yes" if verified else "verified-no"
        tag_text = "verificado" if verified else "no verificado"
        instrument = a.get("instrument") or a.get("work") or ""
        detail = esc(a.get("proposition_to_verify") or a.get("fabrication_risk_note") or instrument)
        pills.append(f"""
    <div class="jurisdiction-pill">
      <div class="jurisdiction-name">{aid} <span class="verified-tag {tag_cls}">{tag_text}</span></div>
      <div class="jurisdiction-laws">{detail}</div>
    </div>""")

    return f"""
<div class="section-head">
  <h2>7. Autoridades citadas</h2>
  <p><strong>{n_verified} de {len(authorities)}</strong> autoridades listadas están verificadas. Las autoridades
     no verificadas no deben citarse como texto confirmado.</p>
</div>
<div style="margin-bottom:16px;">{''.join(pills)}</div>
"""


def build_footer(data):
    vid = esc(data.get("violation_id", ""))
    schema = esc(data.get("schema_version", ""))
    xrefs = data.get("cross_references", []) or []
    xref_str = ", ".join(esc(x.get("ref", "")) for x in xrefs) if xrefs else ""
    xref_line = f" Referencias cruzadas: {xref_str}." if xref_str else ""

    return f"""
<div class="page-footer">
  <p><span class="mono">{vid} · schema_version {schema}</span> — Documento generado automáticamente a partir del
  expediente de análisis de cumplimiento. Este archivo organiza evidencia y calificaciones jurídicas preliminares
  con fines de trabajo interno; los elementos "contested" y las autoridades "no verificadas" no deben presentarse
  como hechos probados o citas confirmadas.{xref_line}</p>
</div>
"""


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_html(data):
    body = "".join([
        build_masthead(data),
        build_stats(data),
        '<div class="main">',
        build_incident_box(data),
        build_established_articles(data),
        build_element_grids(data),
        build_transcript(data),
        build_confidence(data),
        build_open_questions(data),
        build_authorities(data),
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


def generate(input_path, output_path):
    input_path = Path(input_path)
    data = json.loads(input_path.read_text(encoding="utf-8"))

    html_str = build_html(data)
    html_path = input_path.with_suffix(".report.html")
    html_path.write_text(html_str, encoding="utf-8")

    weasyprint.HTML(string=html_str, base_url=str(input_path.parent)).write_pdf(str(output_path))
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else str(Path(in_path).with_suffix(".pdf"))
    generate(in_path, out_path)