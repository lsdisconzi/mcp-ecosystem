"""
Render `master_index/master_index.json` into a navigable Markdown file.

Layout:
  1. Header + summary (counts, by tribunal, year, outcome, classe)
  2. Filter/navigation indices (by tribunal, relator, assunto, outcome, comarca)
  3. Tribunal sections, each with:
       - quick TOC of every document (process number -> anchor)
       - one block per document: metadata table, ementa, outcomes,
         assuntos, legislacao, partes, correlation links
  4. Correlation blocks at each document: links to related docs (same relator,
     same assuntos, same legislacao)

The output is one self-contained `.md` file with intra-document anchors
(`#doc-<numero_processo-slug>`) so it can be opened from any Markdown viewer
(VS Code, Obsidian, GitHub).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


MAX_EMENTA_CHARS = 1500
MAX_EXCERPT_CHARS = 800
MAX_CORRELATION_LINKS = 5

EM_DASH = "\u2014"


def _relator_name(value: Any) -> Optional[str]:
    """Return the relator display name from a string or a dict ({"nome": ...})."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("nome")
    return str(value)


def _name_field(value: Any) -> Optional[str]:
    """Extract a display name from a string or a dict with a "nome" key."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("nome")
    return str(value)



def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s or "doc"


def _md_escape(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _format_outcome(name: str) -> str:
    return name.replace("_", " ")


def _truncate(text: Optional[str], limit: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " \u2026"


def _doc_anchor(doc: Dict[str, Any]) -> str:
    """Generate stable anchor from numero_processo."""
    proc = doc.get("numero_processo") or ""
    return f"doc-{_slug(proc)}"


def _doc_title(doc: Dict[str, Any]) -> str:
    proc = doc.get("numero_processo") or "???"
    tribunal = doc.get("tribunal") or "\u2014"
    return f"[{tribunal}] {proc}"


def _build_correlation_maps(documents: List[Dict[str, Any]]) -> Tuple[
    Dict[str, List[str]], Dict[str, List[str]], Dict[str, List[str]]
]:
    """Pre-compute correlation lookup maps."""
    relator_map: Dict[str, List[str]] = defaultdict(list)
    assunto_map: Dict[str, List[str]] = defaultdict(list)
    legislacao_map: Dict[str, List[str]] = defaultdict(list)

    for doc in documents:
        proc = doc.get("numero_processo") or ""
        if not proc:
            continue
        relator = (_relator_name(doc.get("relator")) or "").strip().lower()
        if relator:
            relator_map[relator].append(proc)
        for a in (doc.get("assuntos") or []):
            assunto_map[a.lower()].append(proc)
        for l in (doc.get("legislacao_citada") or []):
            legislacao_map[l.lower()].append(proc)

    return relator_map, assunto_map, legislacao_map


def _build_doc_section(
    doc: Dict[str, Any],
    relator_map: Dict[str, List[str]],
    assunto_map: Dict[str, List[str]],
    legislacao_map: Dict[str, List[str]],
) -> str:
    lines: List[str] = []
    anchor = _doc_anchor(doc)
    title = _doc_title(doc)
    lines.append(f'### <a id="{anchor}"></a>{title}')
    lines.append("")
    lines.append(f"`tribunal`: `{doc.get('tribunal')}` \u00b7 `extracted_at`: `{doc.get('extracted_at') or 'unknown'}`")
    lines.append("")

    # ── metadata table ─────────────────────────────────────────────────
    rows: List[tuple] = []

    def add(field: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        rows.append((field, _md_escape(value)))

    add("Tribunal", doc.get("tribunal"))
    add("Processo", doc.get("numero_processo"))
    add("Classe", doc.get("classe"))
    add("Relator", _relator_name(doc.get("relator")))
    add("\u00d3rg\u00e3o julgador", _name_field(doc.get("orgao_julgador")))
    add("Comarca", _name_field(doc.get("comarca")))
    add("Julgado em", doc.get("data_julgamento"))
    if doc.get("outcome"):
        add("Resultado / outcome", [_format_outcome(o) for o in doc["outcome"]])
    add("Vota\u00e7\u00e3o", doc.get("votacao"))
    if doc.get("assuntos"):
        add("Assuntos", doc["assuntos"])
    if doc.get("legislacao_citada"):
        add("Legisla\u00e7\u00e3o citada", doc["legislacao_citada"])
    add("Tamanho do texto (chars)", doc.get("texto_length"))
    add("Arquivo fonte", doc.get("source_file"))

    if rows:
        lines.append("| Campo | Valor |")
        lines.append("| --- | --- |")
        for k, v in rows:
            lines.append(f"| **{k}** | {v} |")
        lines.append("")

    # ── Partes ─────────────────────────────────────────────────────────
    partes = doc.get("partes") or {}
    if isinstance(partes, dict):
        apelantes = partes.get("apelantes") or []
        apelados = partes.get("apelados") or []
        if apelantes or apelados:
            lines.append("**Partes:**")
            lines.append("")
            if apelantes:
                lines.append(f"- Apelante(s): {', '.join(_md_escape(a) for a in apelantes)}")
            if apelados:
                if isinstance(apelados, list):
                    ape_text = ", ".join(str(a)[:200] for a in apelados)
                else:
                    ape_text = str(apelados)[:200]
                lines.append(f"- Apelado(s): {_md_escape(ape_text)}")
            lines.append("")

    # ── Advogados ──────────────────────────────────────────────────────
    adv = doc.get("advogados")
    if adv and isinstance(adv, list) and len(adv) > 0:
        lines.append("**Advogados:** " + ", ".join(_md_escape(a) for a in adv))
        lines.append("")

    # ── ementa / excerpt ───────────────────────────────────────────────
    ementa = _truncate(doc.get("ementa"), MAX_EMENTA_CHARS)
    if ementa:
        lines.append("**Ementa / abertura:**")
        lines.append("")
        lines.append("> " + ementa.replace("\n", "\n> "))
        lines.append("")

    # ── Court-specific ─────────────────────────────────────────────────
    cs = doc.get("court_specific")
    if cs and isinstance(cs, dict) and cs:
        lines.append("**Dados espec\u00edficos do tribunal:**")
        lines.append("")
        for k, v in sorted(cs.items()):
            lines.append(f"- **{k}**: {_md_escape(v)}")
        lines.append("")

    # ── Correlations ───────────────────────────────────────────────────
    proc = doc.get("numero_processo")
    relator = (_relator_name(doc.get("relator")) or "").strip().lower()
    assuntos_lc = [a.lower() for a in (doc.get("assuntos") or [])]
    leg_lc = [l.lower() for l in (doc.get("legislacao_citada") or [])]

    if proc:
        lines.append("**Documentos correlacionados:**")
        lines.append("")

        # Same relator
        if relator:
            same = [p for p in relator_map.get(relator, []) if p != proc]
            if same:
                links = [f"[{p}](#doc-{_slug(p)})" for p in same[:MAX_CORRELATION_LINKS]]
                extra = f" (+{len(same) - MAX_CORRELATION_LINKS} mais)" if len(same) > MAX_CORRELATION_LINKS else ""
                lines.append(f"- **Mesmo relator** ({len(same)}): {', '.join(links)}{extra}")

        # Same assuntos
        same_assuntos: set = set()
        for a in assuntos_lc:
            for p in assunto_map.get(a, []):
                if p != proc:
                    same_assuntos.add(p)
        if same_assuntos:
            sp = sorted(same_assuntos)[:MAX_CORRELATION_LINKS]
            links = [f"[{p}](#doc-{_slug(p)})" for p in sp]
            extra = f" (+{len(same_assuntos) - MAX_CORRELATION_LINKS} mais)" if len(same_assuntos) > MAX_CORRELATION_LINKS else ""
            lines.append(f"- **Mesmos assuntos** ({len(same_assuntos)}): {', '.join(links)}{extra}")

        # Same legislacao
        same_leg: set = set()
        for l in leg_lc:
            for p in legislacao_map.get(l, []):
                if p != proc:
                    same_leg.add(p)
        if same_leg:
            sp = sorted(same_leg)[:MAX_CORRELATION_LINKS]
            links = [f"[{p}](#doc-{_slug(p)})" for p in sp]
            extra = f" (+{len(same_leg) - MAX_CORRELATION_LINKS} mais)" if len(same_leg) > MAX_CORRELATION_LINKS else ""
            lines.append(f"- **Mesma legisla\u00e7\u00e3o** ({len(same_leg)}): {', '.join(links)}{extra}")

        if not ((relator and any(p != proc for p in relator_map.get(relator, [])))
                or same_assuntos or same_leg):
            lines.append("*Nenhuma correla\u00e7\u00e3o encontrada.*")
        lines.append("")

    lines.append("[\u2934 topo](#topo) \u00b7 [voltar ao tribunal](#tribunal-" + _slug(doc.get("tribunal") or "unknown") + ")")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_master_markdown(
    master_index_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    if not master_index_path.is_file():
        raise FileNotFoundError(f"master_index.json not found at {master_index_path}")

    data = json.loads(master_index_path.read_text(encoding="utf-8"))
    documents: List[Dict[str, Any]] = data.get("documents", []) or []

    if output_path is None:
        output_path = master_index_path.with_suffix(".md")

    # Group by tribunal
    by_tribunal: Dict[str, List[Dict[str, Any]]] = {}
    for d in documents:
        t = d.get("tribunal") or "Desconhecido"
        by_tribunal.setdefault(t, []).append(d)
    for items in by_tribunal.values():
        items.sort(
            key=lambda d: (
                d.get("data_julgamento") or "",
                d.get("numero_processo") or "",
            ),
            reverse=True,
        )

    # Pre-compute correlation maps
    relator_map, assunto_map, legislacao_map = _build_correlation_maps(documents)

    out: List[str] = []
    out.append('<a id="topo"></a>')
    out.append("")
    out.append("# Juris-Search \u00b7 \u00cdndice Mestre de Jurisprud\u00eancia")
    out.append("")
    out.append(f"_Gerado em **{data.get('generated_at')}**_")
    out.append("")

    # ── Top-level summary ──────────────────────────────────────────────
    total = data.get("total_documents") or len(documents)
    out.append(f"- **Documentos indexados:** {total}")
    out.append(f"- **Jobs de busca:** {data.get('search_jobs_count')}")
    out.append(f"- **Diret\u00f3rio-base:** `{data.get('base_dir')}`")
    out.append("")

    out.append("## Sum\u00e1rio r\u00e1pido")
    out.append("")

    def _kv_table(title: str, mapping: Optional[Dict[str, Any]]) -> None:
        if not mapping:
            return
        out.append(f"### {title}")
        out.append("")
        out.append("| Chave | Total |")
        out.append("| --- | ---: |")
        for k, v in sorted(mapping.items(), key=lambda kv: (-(kv[1] or 0), kv[0])):
            out.append(f"| {_md_escape(k)} | {v} |")
        out.append("")

    _kv_table("Por tribunal", data.get("by_tribunal"))
    _kv_table("Por ano", data.get("by_year"))
    _kv_table("Por resultado / outcome", data.get("by_outcome"))
    _kv_table("Top relatores", data.get("top_relators"))
    _kv_table("Top comarcas", data.get("top_comarcas"))
    _kv_table("Top assuntos", data.get("top_assuntos"))
    _kv_table("Classes processuais", data.get("by_classe"))

    # Pipeline status block
    qdrant = data.get("qdrant") or {}
    awareness = data.get("awareness") or {}
    out.append("### Estado das pipelines de ingest\u00e3o")
    out.append("")
    out.append("| Pipeline | Habilitada | OK | Cole\u00e7\u00e3o | \u00daltima observa\u00e7\u00e3o |")
    out.append("| --- | :-: | :-: | --- | --- |")
    out.append(
        f"| Qdrant ({qdrant.get('collection') or EM_DASH}) "
        f"| {qdrant.get('enabled')} | {qdrant.get('ok')} "
        f"| `{qdrant.get('collection') or EM_DASH}` "
        f"| {_md_escape(_truncate(qdrant.get('error'), 220))} |")
    out.append(
        f"| Awareness memory "
        f"| {awareness.get('enabled')} | {awareness.get('ok')} "
        f"| `{awareness.get('collection') or EM_DASH}` "
        f"| {_md_escape(_truncate(awareness.get('error'), 220))} |"
    )
    out.append("")

    # ── Filter / Navigation indices ────────────────────────────────────
    out.append("## Navega\u00e7\u00e3o por \u00edndices")
    out.append("")

    # By tribunal
    out.append("### Por tribunal")
    out.append("")
    for tribunal in sorted(by_tribunal.keys()):
        anchor = "tribunal-" + _slug(tribunal)
        out.append(f"- [{tribunal} ({len(by_tribunal[tribunal])})](#{anchor})")
    out.append("")

    # By relator
    top_relators = data.get("top_relators") or {}
    if top_relators:
        out.append("### Por relator")
        out.append("")
        for relator, count in sorted(top_relators.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
            # link to first doc by this relator
            first_proc = None
            for d in documents:
                if (_relator_name(d.get("relator")) or "").strip().lower() == relator.strip().lower():
                    first_proc = d.get("numero_processo")
                    break
            if first_proc:
                out.append(f"- [{relator} ({count})](#doc-{_slug(first_proc)})")
            else:
                out.append(f"- {relator} ({count})")
        out.append("")

    # By outcome
    by_outcome = data.get("by_outcome") or {}
    if by_outcome:
        out.append("### Por resultado / outcome")
        out.append("")
        for outcome, count in sorted(by_outcome.items(), key=lambda kv: (-kv[1], kv[0])):
            # find first doc with this outcome
            out_lc = outcome.lower()
            first_proc = None
            for d in documents:
                doc_out = [o.lower() for o in (d.get("outcome") or [])]
                if out_lc in doc_out:
                    first_proc = d.get("numero_processo")
                    break
            label = _format_outcome(outcome)
            if first_proc:
                out.append(f"- [{label} ({count})](#doc-{_slug(first_proc)})")
            else:
                out.append(f"- {label} ({count})")
        out.append("")

    # By assunto
    top_assuntos = data.get("top_assuntos") or {}
    if top_assuntos:
        out.append("### Por assunto")
        out.append("")
        for assunto, count in sorted(top_assuntos.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
            a_lc = assunto.lower()
            first_proc = None
            for d in documents:
                doc_assuntos = [a.lower() for a in (d.get("assuntos") or [])]
                if any(a_lc in a for a in doc_assuntos):
                    first_proc = d.get("numero_processo")
                    break
            if first_proc:
                out.append(f"- [{assunto} ({count})](#doc-{_slug(first_proc)})")
            else:
                out.append(f"- {assunto} ({count})")
        out.append("")

    # By comarca
    top_comarcas = data.get("top_comarcas") or {}
    if top_comarcas:
        out.append("### Por comarca")
        out.append("")
        for comarca, count in sorted(top_comarcas.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
            c_lc = comarca.lower()
            first_proc = None
            for d in documents:
                if c_lc in (_name_field(d.get("comarca")) or "").lower():
                    first_proc = d.get("numero_processo")
                    break
            if first_proc:
                out.append(f"- [{comarca} ({count})](#doc-{_slug(first_proc)})")
            else:
                out.append(f"- {comarca} ({count})")
        out.append("")

    # ── Per-tribunal sections ──────────────────────────────────────────
    for tribunal in sorted(by_tribunal.keys()):
        items = by_tribunal[tribunal]
        anchor = "tribunal-" + _slug(tribunal)
        out.append(f'## <a id="{anchor}"></a>{tribunal} \u2014 {len(items)} documento(s)')
        out.append("")

        # Quick TOC table for this tribunal
        out.append("### \u00cdndice r\u00e1pido")
        out.append("")
        out.append("| Processo | Relator | Comarca | Julgado em | Resultado |")
        out.append("| --- | --- | --- | --- | --- |")
        for d in items:
            proc = d.get("numero_processo") or d.get("source_file") or "???"
            link = f"[{_md_escape(proc)}](#{_doc_anchor(d)})"
            out.append(
                "| {proc} | {rel} | {com} | {dat} | {out} |".format(
                    proc=link,
                    rel=_md_escape(_relator_name(d.get("relator"))) or "\u2014",
                    com=_md_escape(_name_field(d.get("comarca"))) or "\u2014",
                    dat=_md_escape(d.get("data_julgamento")) or "\u2014",
                    out=_md_escape(", ".join(_format_outcome(o) for o in (d.get("outcome") or []))) or "\u2014",
                )
            )
        out.append("")
        out.append("[\u2934 topo](#topo)")
        out.append("")

        # Detail blocks
        for d in items:
            out.append(_build_doc_section(d, relator_map, assunto_map, legislacao_map))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out), encoding="utf-8")
    return output_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Render master_index.json into Markdown")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parent / "master_index" / "master_index.json"),
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else None
    written = render_master_markdown(in_path, out_path)
    print(f"Wrote {written}")


if __name__ == "__main__":
    main()
