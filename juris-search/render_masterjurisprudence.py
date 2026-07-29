"""
Render `master_index/master_index.json` into:

  1. `masterjurisprudence.jx`  — expanded & updated master index (JSON superset)
  2. `masterjurisprudence.md`  — rendered Markdown companion

The `.jx` keeps the aggregates carried from master_index.json plus an
*expanded catalog*: every supported court (module/class/status), the full API
route map, the frontend panels and the extracted-document schema. It does NOT
embed the raw per-document records — those remain in master_index.json.

Both files are regenerated from the live master index + court config + route
decorators so they stay wired to the codebase. Called from
`juris_indexer.MasterIndexer.rebuild()` after the base .json/.md are written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
COURTS_PY = ROOT / "modules" / "courts.py"

ROUTE_FILES = [
    "routes_master.py", "routes_search.py", "routes_download.py",
    "routes_storage.py", "routes_chat.py", "routes_health.py",
    "routes_frontend.py",
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "doc"


def parse_courts() -> List[Dict[str, Any]]:
    """Parse SUPPORTED_COURTS + COURT_NAMES from modules/courts.py."""
    if not COURTS_PY.is_file():
        return []
    src = COURTS_PY.read_text(encoding="utf-8")
    block = re.search(r"SUPPORTED_COURTS\s*=\s*\{(.*?)\n\}", src, re.S)
    if not block:
        return []
    block = block.group(1)
    courts: List[Dict[str, Any]] = []
    for m in re.finditer(r'"(?P<key>TJ[A-Z0-9]+|STF|CL)":\s*\{(.*?)\}', block, re.S):
        key = m.group("key")
        body = m.group(2)
        name = re.search(r'"name":\s*"([^"]+)"', body)
        module = re.search(r'"scraper_module":\s*"([^"]+)"', body)
        cls = re.search(r'"scraper_class":\s*"([^"]+)"', body)
        category = "esaj" if (module and "esaj" in module.group(1)) else (
            "stf" if key == "STF" else ("chile" if key == "CL" else "custom-portal")
        )
        courts.append({
            "key": key,
            "name": name.group(1) if name else key,
            "scraper_module": module.group(1) if module else "",
            "scraper_class": cls.group(1) if cls else "",
            "category": category,
        })
    names = dict(re.findall(r'"(TJ[A-Z0-9]+|STF|CL)":\s*"([^"]+)"', src))
    for c in courts:
        if c["key"] in names:
            c["name"] = names[c["key"]]
    return courts


def api_routes() -> List[Dict[str, str]]:
    routes: List[Dict[str, str]] = []
    for fn in ROUTE_FILES:
        path = ROOT / "modules" / fn
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.search(r'@(?:router|app)\.(get|post|put|delete|patch)\("([^"]+)"', line)
            if m:
                routes.append({"method": m.group(1).upper(),
                               "path": m.group(2), "module": fn})
    return routes


def frontend_panels() -> List[Dict[str, str]]:
    return [
        {"id": "dashboard", "label": "Dashboard", "icon": "fa-chart-pie",
         "purpose": "Estatísticas, gráficos de distribuição de resultados, "
                    "assuntos, relatores, câmaras e mapa de divergência."},
        {"id": "pesquisa", "label": "Pesquisa", "icon": "fa-search",
         "purpose": "Busca textual/filtros (relator, assunto, resultado, lei) "
                    "com export CSV/Excel/PDF e highlight de termos."},
        {"id": "analises", "label": "Análises", "icon": "fa-chart-bar",
         "purpose": "Evolução temporal, leis e artigos mais citados."},
        {"id": "biblioteca", "label": "Biblioteca", "icon": "fa-bookmark",
         "purpose": "Decisões favoritadas/pessoais (localStorage jrLibrary)."},
        {"id": "alertas", "label": "Alertas", "icon": "fa-bell",
         "purpose": "Alertas inteligentes por query (localStorage jrAlerts)."},
        {"id": "admin", "label": "Admin", "icon": "fa-cog",
         "purpose": "Pipeline de coleta/indexação, logs e auditoria."},
    ]


def extracted_schema_example() -> Optional[Dict[str, Any]]:
    import glob
    sample = ROOT / "extracted_documents" / "TJSP_inteiro_teor_20684393.json"
    if not sample.is_file():
        files = sorted(glob.glob(str(ROOT / "extracted_documents" / "*.json")))
        sample = Path(files[0]) if files else None
    if not sample or not Path(sample).is_file():
        return None
    d = json.loads(Path(sample).read_text(encoding="utf-8"))
    return {"sample_source_file": Path(sample).name, "top_level_keys": list(d.keys())}


def build_payload(master_path: Path, courts: List[Dict[str, Any]],
                  routes: List[Dict[str, str]]) -> Dict[str, Any]:
    data = json.loads(master_path.read_text(encoding="utf-8"))
    by_tribunal = data.get("by_tribunal", {})
    for c in courts:
        c["documents_indexed"] = by_tribunal.get(c["key"], 0)
        c["operational"] = c["key"] in by_tribunal
    return {
        "schema_version": 2,
        "generated_at": data.get("generated_at"),
        "file_extension_note": ".jsx is a JSON superset of master_index.json; "
                               "aggregates + expanded catalog (courts, API, "
                               "frontend). Raw document records live in "
                               "master_index.json (documents[]).",
        "base_dir": data.get("base_dir"),
        "dirs": {
            "downloads": data.get("downloads_dir"),
            "json": data.get("json_dir"),
            "docx": data.get("docx_dir"),
            "history": data.get("history_dir"),
            "extracted_documents": str(ROOT / "extracted_documents"),
            "frontend_src": str(ROOT / "tjrs-frontend" / "src"),
        },
        "totals": {
            "documents": data.get("total_documents"),
            "search_jobs": data.get("search_jobs_count"),
        },
        "by_tribunal": by_tribunal,
        "by_year": data.get("by_year"),
        "by_outcome": data.get("by_outcome"),
        "top_relators": data.get("top_relators"),
        "top_comarcas": data.get("top_comarcas"),
        "qdrant": data.get("qdrant"),
        "awareness": data.get("awareness"),
        "courts": {
            "supported_count": len(courts),
            "operational_count": sum(1 for c in courts if c["operational"]),
            "list": courts,
        },
        "api": {
            "base_path_note": "All /api/* routes are FastAPI. Frontend "
                              "proxies via /juris in production.",
            "route_count": len(routes),
            "routes": routes,
        },
        "frontend": {
            "view_file": "tjrs-frontend/src/jurisprudence.html",
            "react_app": "tjrs-frontend/src/App.jsx",
            "master_index_views": [
                "tjrs-frontend/src/MasterIndexView.jsx",
                "tjrs-frontend/src/MasterIndexDetailView.jsx",
                "tjrs-frontend/src/AdminView.jsx",
            ],
            "panels": frontend_panels(),
            "global_search_filters": ["Tribunal", "Ano"],
            "frontend_supported_tribunals": [
                "TJSP", "TJMS", "TJRS", "TJCE", "TJAL", "TJAM"],
        },
        "extracted_document_schema": extracted_schema_example(),
        "sources": [
            {"role": "master_index", "path": "master_index/master_index.json"},
            {"role": "master_markdown", "path": "master_index/master_index.md"},
            {"role": "court_config", "path": "modules/courts.py"},
            {"role": "api_routes_master", "path": "modules/routes_master.py"},
            {"role": "api_routes_search", "path": "modules/routes_search.py"},
            {"role": "api_routes_download", "path": "modules/routes_download.py"},
            {"role": "api_routes_storage", "path": "modules/routes_storage.py"},
            {"role": "api_routes_chat", "path": "modules/routes_chat.py"},
            {"role": "api_routes_health", "path": "modules/routes_health.py"},
            {"role": "api_routes_frontend", "path": "modules/routes_frontend.py"},
            {"role": "frontend_view", "path": "tjrs-frontend/src/jurisprudence.html"},
            {"role": "extracted_docs_dir", "path": "extracted_documents/"},
            {"role": "scraper_chile", "path": "chile_scraper.py"},
            {"role": "extractor", "path": "court_extractor.py"},
            {"role": "indexer", "path": "juris_indexer.py"},
            {"role": "ingest_qdrant", "path": "ingest_to_qdrant.py"},
        ],
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    out: List[str] = []
    out.append('<a id="topo"></a>')
    out.append("")
    out.append("# Juris-Search · Master Jurisprudence (índice expandido)")
    out.append("")
    out.append(f"_Gerado em **{payload.get('generated_at')}**_")
    out.append("")
    totals = payload.get("totals", {})
    out.append(f"- **Documentos indexados:** {totals.get('documents')}")
    out.append(f"- **Jobs de busca:** {totals.get('search_jobs')}")
    out.append(f"- **Tribunais suportados:** {payload['courts']['supported_count']} "
               f"(operacionais: {payload['courts']['operational_count']})")
    out.append(f"- **Rotas de API:** {payload['api']['route_count']}")
    out.append("")
    out.append("> Companhia renderizada de `masterjurisprudence.jsx` (JSON) e de "
               "`master_index` (dados por documento). Agregações + catálogo "
               "expandido; registros brutos ficam em `master_index/master_index.json`.")
    out.append("")

    # Pipeline status
    q = payload.get("qdrant") or {}
    a = payload.get("awareness") or {}
    out.append("## Estado das pipelines")
    out.append("")
    out.append("| Pipeline | Habilitada | OK | Observação |")
    out.append("| --- | :-: | :-: | --- |")
    out.append(f"| Qdrant | {q.get('enabled')} | {q.get('ok')} | "
               f"{_esc(q.get('error'))} |")
    out.append(f"| Awareness | {a.get('enabled')} | {a.get('ok')} | "
               f"{_esc(a.get('error'))} |")
    out.append("")

    # Courts catalog
    out.append("## Catálogo de Tribunais")
    out.append("")
    out.append("| Chave | Nome | Categoria | Scraper | Docs | Status |")
    out.append("| --- | --- | --- | --- | ---: | --- |")
    for c in payload["courts"]["list"]:
        status = "✅ operacional" if c["operational"] else "⚪ configurado"
        out.append(f"| {c['key']} | {_esc(c['name'])} | {c['category']} | "
                   f"`{_esc(c['scraper_class'])}` | {c['documents_indexed']} | {status} |")
    out.append("")

    # Aggregates
    out.append("## Agregações")
    out.append("")
    _kv(out, "Por tribunal", payload.get("by_tribunal"))
    _kv(out, "Por ano", payload.get("by_year"))
    _kv(out, "Por resultado / outcome", payload.get("by_outcome"))
    _kv(out, "Top relatores", payload.get("top_relators"), limit=15)
    _kv(out, "Top comarcas", payload.get("top_comarcas"), limit=15)

    # API routes grouped by module
    out.append("## Superfície de API")
    out.append("")
    out.append(f"_{payload['api']['base_path_note']}_")
    out.append("")
    by_mod: Dict[str, List[Dict[str, str]]] = {}
    for r in payload["api"]["routes"]:
        by_mod.setdefault(r["module"], []).append(r)
    for mod in sorted(by_mod):
        out.append(f"### {mod}")
        out.append("")
        out.append("| Método | Rota |")
        out.append("| --- | --- |")
        for r in sorted(by_mod[mod], key=lambda x: (x["path"], x["method"])):
            out.append(f"| {r['method']} | `{_esc(r['path'])}` |")
        out.append("")

    # Frontend panels
    out.append("## Painéis do Frontend")
    out.append("")
    out.append("Fonte: `tjrs-frontend/src/jurisprudence.html` (view) e React "
               "`MasterIndexView`/`App.jsx`.")
    out.append("")
    out.append("| Painel | Ícone | Finalidade |")
    out.append("| --- | --- | --- |")
    for p in payload["frontend"]["panels"]:
        out.append(f"| {p['label']} (`{p['id']}`) | `{p['icon']}` | {_esc(p['purpose'])} |")
    out.append("")
    out.append(f"Filtros de busca global: "
               f"{', '.join(payload['frontend']['global_search_filters'])}.")
    out.append("")

    # Extracted schema
    sch = payload.get("extracted_document_schema")
    if sch:
        out.append("## Schema do Documento Extraído")
        out.append("")
        out.append(f"Amostra: `{sch['sample_source_file']}`")
        out.append("")
        out.append("Campos de nível superior: " +
                   ", ".join(f"`{k}`" for k in sch["top_level_keys"]))
        out.append("")

    # Sources
    out.append("## Fontes / Proveniência")
    out.append("")
    out.append("| Papel | Caminho |")
    out.append("| --- | --- |")
    for s in payload["sources"]:
        out.append(f"| {s['role']} | `{_esc(s['path'])}` |")
    out.append("")
    out.append("[⤴ topo](#topo)")
    return "\n".join(out)


def _esc(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace("|", "\\|").replace("\n", " ")


def _kv(out: List[str], title: str, mapping: Optional[Dict[str, Any]], limit: int = 0) -> None:
    if not mapping:
        return
    out.append(f"### {title}")
    out.append("")
    out.append("| Chave | Total |")
    out.append("| --- | ---: |")
    items = sorted(mapping.items(), key=lambda kv: (-(kv[1] or 0), kv[0]))
    if limit:
        items = items[:limit]
    for k, v in items:
        out.append(f"| {_esc(k)} | {v} |")
    out.append("")


def render(master_index_path: Path,
           jx_path: Optional[Path] = None,
           md_path: Optional[Path] = None) -> Dict[str, Path]:
    """Generate both masterjurisprudence.jx and .md from the master index."""
    if not master_index_path.is_file():
        raise FileNotFoundError(f"master_index.json not found at {master_index_path}")
    courts = parse_courts()
    routes = api_routes()
    payload = build_payload(master_index_path, courts, routes)

    if jx_path is None:
        jx_path = master_index_path.parent / "masterjurisprudence.jsx"
    if md_path is None:
        md_path = master_index_path.parent / "masterjurisprudence.md"

    jx_path.parent.mkdir(parents=True, exist_ok=True)
    jx_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"jx": jx_path, "md": md_path}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Render master jurisprudence .jx + .md")
    parser.add_argument(
        "--input",
        default=str(ROOT / "master_index" / "master_index.json"),
    )
    args = parser.parse_args()
    written = render(Path(args.input))
    print(f"Wrote {written['jx']}")
    print(f"Wrote {written['md']}")


if __name__ == "__main__":
    main()
