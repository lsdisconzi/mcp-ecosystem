#!/usr/bin/env python3
"""Rebuild Olivia's master_index from extracted_documents + ingestion state."""

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def safe_str(value, default=''):
    """Return a stripped string from value, or default if the value is a dict/list/None."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return default
    return str(value).strip()


def doc_contains_phrase(doc: dict, phrase: str) -> bool:
    """
    Check if a document (as a whole) contains a given phrase case‑insensitively.
    We serialize the entire dict to a string and perform a simple substring search.
    """
    serialized = json.dumps(doc, ensure_ascii=False).lower()
    return phrase.lower() in serialized


# ── Configuration ────────────────────────────────────────────────────────
EXT_DIR = Path('/home/disconzi1986_gmail_com/juris-search-VPS/extracted_documents')
MAINTENANCE_PHRASE = "MANUTENÇÃO NÃO PROGRAMADA DA AERONAVE"

OUT_DIR = Path('/home/disconzi1986_gmail_com/juris-search-VPS/master-indexer-manual')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Load all extraction JSONs ────────────────────────────────────────────
docs = []
for fpath in sorted(EXT_DIR.glob('*.json')):
    try:
        with open(fpath, encoding='utf-8') as f:
            d = json.load(f)
        d['_file'] = fpath.name
        docs.append(d)
    except Exception as e:
        print(f"SKIP {fpath.name}: {e}")

print(f"Loaded {len(docs)} documents")

# ── Aggregates (general) ─────────────────────────────────────────────────
by_tribunal = Counter()
by_year = Counter()
by_outcome = Counter()
by_relator = Counter()
by_comarca = Counter()
by_classe = Counter()
by_assunto = Counter()
maintenance_count = 0  # specific phrase count

for d in docs:
    # Tribunal
    t = d.get('tribunal') or 'UNKNOWN'
    by_tribunal[t] += 1

    # Year
    dj = d.get('data_julgamento', '')
    y = dj[:4] if dj else ''
    if not y:
        proc = d.get('numero_processo', '')
        m = re.search(r'(\d{4})', proc)
        yr = int(m.group(1)) if m else 0
        if 1990 <= yr <= 2030:
            y = str(yr)
    if y and 1990 <= int(y) <= 2030:
        by_year[y] += 1

    # Outcome
    oc = d.get('outcome')
    if isinstance(oc, list):
        for o in oc:
            by_outcome[o] += 1
    elif oc:
        by_outcome[str(oc)] += 1

    # Relator
    rel = safe_str(d.get('relator'))
    if rel and len(rel) > 3:
        by_relator[rel] += 1

    # Comarca
    com = safe_str(d.get('comarca'))
    if com and len(com) > 2:
        by_comarca[com] += 1

    # Classe
    cl = safe_str(d.get('classe'))
    if cl:
        by_classe[cl] += 1

    # Assuntos
    ass = d.get('assuntos')
    if isinstance(ass, list):
        for a in ass:
            by_assunto[a] += 1

    # ── Special maintenance phrase ────────────────────────────────────
    if doc_contains_phrase(d, MAINTENANCE_PHRASE):
        maintenance_count += 1

# ── Court coverage (static, as provided) ─────────────────────────────────
court_coverage = {
    "working": {
        "TJSP": {"docs": by_tribunal.get("TJSP", 0), "status": "extracted + ingested"},
        "TJMS": {"docs": by_tribunal.get("TJMS", 0), "status": "extracted + ingested"},
        "TJCE": {"docs": by_tribunal.get("TJCE", 0), "status": "extracted + ingested"},
        "TJRS": {"docs": by_tribunal.get("TJRS", 0), "status": "extracted + ingested (.doc converted to .docx)"},
    },
    "blocked_captcha": {
        "TJAC": {"docs": 42, "status": "33 CAPTCHA, 9 no-text"},
        "TJAL": {"docs": 39, "status": "38 CAPTCHA, 1 no-text"},
        "TJAM": {"docs": 47, "status": "47 CAPTCHA"},
    },
    "search_ok_no_downloads": {
        "TJMA": 60, "TJBA": 60, "TJPE": 60, "TJPB": 60, "TJRN": 60,
        "TJSE": 60, "TJPI": 60, "TJES": 60, "TJPR": 60, "TJSC": 60,
        "TJMT": 90, "TJPA": 40, "TJRO": 40, "TJGO": 40, "TJDFT": 40,
        "TJTO": 40, "TJRR": 40, "TJAP": 40,
    },
    "search_failed": {
        "TJMG": "6 searches, 0 results",
        "TJRJ": "4 searches, 0 results",
        "STF": "4 searches, 0 results",
    }
}

# ── Master index JSON ────────────────────────────────────────────────────
master = {
    "schema_version": 2,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "extraction_dir": str(EXT_DIR),
    "qdrant_collection": "juris_br_v1",
    "qdrant_vector_size": 768,
    "total_documents": len(docs),
    "total_ingested_qdrant": 706,
    "total_extracted": len(docs),
    "by_tribunal": dict(by_tribunal.most_common()),
    "by_year": dict(sorted(by_year.items())),
    "by_outcome": dict(by_outcome.most_common()),
    "by_classe": dict(by_classe.most_common()),
    "top_relators": dict(by_relator.most_common(25)),
    "top_comarcas": dict(by_comarca.most_common(15)),
    "top_assuntos": dict(by_assunto.most_common(30)),
    "manutencao_nao_programada_aeronave": {
        "phrase": MAINTENANCE_PHRASE,
        "documents_containing_phrase": maintenance_count,
    },
    "court_coverage": court_coverage,
    "documents": [
        {
            "tribunal": d.get("tribunal"),
            "numero_processo": d.get("numero_processo"),
            "classe": d.get("classe"),
            "relator": d.get("relator"),
            "orgao_julgador": d.get("orgao_julgador"),
            "comarca": d.get("comarca"),
            "data_julgamento": d.get("data_julgamento"),
            "ementa": d.get("ementa"),
            "outcome": d.get("outcome"),
            "assuntos": d.get("assuntos"),
            "legislacao_citada": d.get("legislacao_citada"),
            "votacao": d.get("votacao"),
            "partes": d.get("partes"),
            "advogados": d.get("advogados"),
            "court_specific": d.get("court_specific"),
            "texto_length": d.get("texto_length"),
            "source_file": d.get("source_file"),
            "extracted_at": d.get("extracted_at"),
        }
        for d in docs
    ],
}

out_json = OUT_DIR / "master_index.json"
with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(master, f, ensure_ascii=False, indent=2)
print(f"Wrote {out_json} ({os.path.getsize(out_json)} bytes)")

# ── Master index Markdown ───────────────────────────────────────────────
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
lines = []
lines.append('<a id="topo"></a>')
lines.append('')
lines.append('# Juris-Search · Índice Mestre de Jurisprudência')
lines.append('')
lines.append(f'_Atualizado em **{now_str}**_')
lines.append('')
lines.append(f'- **Documentos extraídos:** {len(docs)}')
lines.append(f'- **Ingeridos no Qdrant:** 706 (`juris_br_v1`, 768-dim)')
lines.append(f'- **Tribunais com dados reais:** 4 (TJSP, TJMS, TJCE, TJRS)')
lines.append(f'- **Diretório de extrações:** `{EXT_DIR}`')
lines.append('')

lines.append('## Sumário rápido')
lines.append('')
lines.append('### Por tribunal (extraídos + ingeridos)')
lines.append('')
lines.append('| Tribunal | Documentos |')
lines.append('| --- | ---: |')
for t, c in by_tribunal.most_common():
    lines.append(f'| {t} | {c} |')
lines.append('')

lines.append('### Por ano')
lines.append('')
lines.append('| Ano | Total |')
lines.append('| --- | ---: |')
for y, c in sorted(by_year.items()):
    lines.append(f'| {y} | {c} |')
lines.append('')

lines.append('### Por resultado / outcome')
lines.append('')
lines.append('| Outcome | Total |')
lines.append('| --- | ---: |')
for o, c in by_outcome.most_common():
    lines.append(f'| {o} | {c} |')
lines.append('')

lines.append('### Top relatores')
lines.append('')
lines.append('| Relator | Total |')
lines.append('| --- | ---: |')
for r, c in by_relator.most_common(25):
    lines.append(f'| {r[:60]} | {c} |')
lines.append('')

lines.append('### Top comarcas')
lines.append('')
lines.append('| Comarca | Total |')
lines.append('| --- | ---: |')
for co, c in by_comarca.most_common(15):
    lines.append(f'| {co} | {c} |')
lines.append('')

lines.append('### Top assuntos')
lines.append('')
lines.append('| Assunto | Total |')
lines.append('| --- | ---: |')
for a, c in by_assunto.most_common(20):
    lines.append(f'| {a} | {c} |')
lines.append('')

lines.append('### Classes processuais')
lines.append('')
lines.append('| Classe | Total |')
lines.append('| --- | ---: |')
for cl, c in by_classe.most_common(20):
    lines.append(f'| {cl} | {c} |')
lines.append('')

# ── Special section for "Manutenção Não Programada de Aeronave" ─────
lines.append('## Manutenção Não Programada de Aeronave')
lines.append('')
lines.append(f'- **Frase pesquisada:** `{MAINTENANCE_PHRASE}`')
lines.append(f'- **Documentos que contêm essa frase:** {maintenance_count}')
lines.append('')

lines.append('## Cobertura de tribunais')
lines.append('')
lines.append('### Extraídos e ingeridos (4 tribunais)')
lines.append('')
for trib, info in court_coverage["working"].items():
    lines.append(f'- **{trib}**: {info["docs"]} documentos — {info["status"]}')
lines.append('')
lines.append(f'**Total ingerido**: 706 documentos em `juris_br_v1`')
lines.append('')

lines.append('### CAPTCHA bloqueados (3 tribunais)')
lines.append('')
for trib, info in court_coverage["blocked_captcha"].items():
    lines.append(f'- **{trib}**: {info["docs"]} tentativas — {info["status"]}')
lines.append('')

lines.append('### Busca OK, downloads não disparados (18 tribunais)')
lines.append('')
for trib, results in sorted(court_coverage["search_ok_no_downloads"].items()):
    lines.append(f'- **{trib}**: ~{results} resultados na busca, batch download pendente')
lines.append('')

lines.append('### Busca falhou (3 tribunais)')
lines.append('')
for trib, status in court_coverage["search_failed"].items():
    lines.append(f'- **{trib}**: {status}')
lines.append('')

lines.append('## Qdrant — `juris_br_v1`')
lines.append('')
lines.append('- **Coleção**: `juris_br_v1` (NOVA — separada da `law_br` antiga)')
lines.append('- **Vetores**: 706 (768 dimensões)')
lines.append('- **API de busca**: `POST /v1/qdrant/search`')
lines.append('- **Filtros disponíveis**: `tribunal`, `relator`, `outcome`, `data_julgamento`, `classe`')
lines.append('- **Metadata por documento**: ementa, partes, advogados, assuntos, legislação citada, court_specific')
lines.append('')
lines.append('### Exemplo de busca')
lines.append('')
lines.append('```bash')
lines.append('curl -X POST http://localhost:8066/v1/qdrant/search \\')
lines.append('  -H "Content-Type: application/json" \\')
lines.append('  -d \'{"collection_name":"juris_br_v1","query_text":"tráfico de drogas","limit":5,')
lines.append('       "filter":{"must":[{"key":"tribunal","match":{"value":"TJSP"}}]}}\'')
lines.append('```')
lines.append('')
lines.append('## Pipeline de Extração')
lines.append('')
lines.append('1. **Fontes**: PDFs (TJSP/TJMS/TJCE) + DOCXs (TJRS) em `court_samples/jurisprudence-documents/`')
lines.append('2. **Extração**: `court_extractor.py` — regex mecânico por tribunal')
lines.append('3. **Saída**: `extracted_documents/` — JSON estruturado por documento')
lines.append('4. **Ingestão**: `ingest_to_qdrant.py` — batch via API `structured_ingest`')
lines.append('5. **Coleção**: `juris_br_v1` — 706 vetores, 768-dim, metadata completa')
lines.append('')

out_md = OUT_DIR / "master_index.md"
with open(out_md, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f"Wrote {out_md} ({os.path.getsize(out_md)} bytes)")
print("Done")