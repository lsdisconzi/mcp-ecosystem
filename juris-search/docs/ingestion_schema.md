# Ingestion Schema — juris-search

Canonical payload structures for all data types ingested and indexed by the juris-search pipeline.

---

## 1. Jurisprudence Document (Master Index Record)

Each jurisprudence decision is indexed as a flat document record. This is the primary retrieval payload.

```json
{
  "id": "tjrs_70084126507_2020_649456",
  "tribunal": "TJRS",
  "numero_processo": "70084126507",
  "cnj_numero": "0027812-80.2013.4.01.3400",
  "ano": "2020",
  "codigo": "649456",
  "cdacordao": null,
  "classe": "Apelação Cível",
  "tipo_processo": "Recurso Especial",
  "assunto": "Transporte Aéreo",
  "relator": "Daniel Henrique Dummer",
  "orgao_julgador": "18ª Câmara de Direito Privado",
  "comarca": "PORTO ALEGRE",
  "data_julgamento": "2020-03-15",
  "data_publicacao": "2020-03-20",
  "downloaded_at": "2026-05-02T19:29:49Z",
  "ementa": "Transporte aéreo. Atraso de voo. Dano moral...",
  "outcomes": ["negado_provimento", "unanime"],
  "monetary_values": ["R$ 5.000,00"],
  "cited_processes": ["0027812-80.2013.4.01.3400"],
  "co_relators": ["Henrique Rodriguero Clavisio"],
  "file_size_bytes": 302844,
  "content_type": "application/pdf",
  "parser": "pdf",
  "text_chars": 44518,
  "text_excerpt": "PODER JUDICIÁRIO...",
  "raw_source_path": "corpus_flat/tjrs/inteiro_teor_70084126507_2020_649456.pdf",
  "json_path": "corpus_flat/tjrs/inteiro_teor_70084126507_2020_649456.json",
  "docx_path": "corpus_flat/tjrs/inteiro_teor_70084126507_2020_649456.docx",
  "sidecar_path": "corpus_flat/tjrs/inteiro_teor_70084126507_2020_649456.pdf.metadata.json",
  "source_signature": "302844:1777730001508874170",
  "search_jobs": ["juris_20260502_192857"],
  "search_terms": ["dano moral", "transporte aereo"],
  "courts_searched": ["TJRS", "TJSP"],
  "indexed_at": "2026-05-06T12:00:00Z"
}
```

### ID Conventions

| Pattern | Example | Tribunal |
|---------|---------|----------|
| `tjrs_{numero}_{ano}_{codigo}` | `tjrs_70084126507_2020_649456` | TJRS |
| `tjsp_{cdacordao}` | `tjsp_19436885` | TJSP |
| `{esaj_court}_{cdacordao}` | `tjsc_12345678`, `tjba_87654321` | Any e-SAJ court (TJSC, TJBA, TJPR, TJPE, etc.) |
| `tjmg_{numero}` | `tjmg_12345678901234` | TJMG |
| `tjrj_{numero}` | `tjrj_98765432109876` | TJRJ |
| `cnj_{digits}` | `cnj_00278128020134013400` | Any (CNJ format) |

### Outcome Values

- `negado_provimento` — appeal denied
- `dado_provimento` — appeal granted
- `provimento_parcial` — partially granted
- `reformada` — sentence reformed
- `mantida` — sentence maintained
- `procedente` — claim upheld
- `improcedente` — claim dismissed
- `unanime` — unanimous decision

---

## 2. Per-Document JSON (Extracted Text)

Each source document (PDF/DOCX) is converted to a structured JSON with full text for embedding.

```json
{
  "id": "7c5c69bcdaa74e61",
  "generated_at": "2026-05-02T13:53:25.099129Z",
  "source_path": "/Users/dev/services/juris-search/corpus_flat/tjsp/inteiro_teor_19436885.pdf",
  "source_relative": "corpus_flat/tjsp/inteiro_teor_19436885.pdf",
  "source_signature": "302844:1777730001508874170",
  "source_metadata": {
    "downloaded_at": "2026-05-02T13:53:21.509015Z",
    "download_url": "https://esaj.tjsp.jus.br/cjsg/getArquivo.do?cdAcordao=19436885&cdForo=0",
    "cdacordao": "19436885",
    "content_type": "application/pdf",
    "file_size_bytes": 302844,
    "tribunal": "TJSP",
    "numero_processo": "1028537-43.2024.8.26.0003",
    "search_params": { "tribunal": "TJSP", "mode": "batch" },
    "download_timestamp": "20260502_105318"
  },
  "content_type": "application/pdf;charset=utf-8",
  "parser": "pdf",
  "text": "PODER JUDICIÁRIO\nTRIBUNAL DE JUSTIÇA DO ESTADO DE SÃO PAULO\n...",
  "text_chars": 44518
}
```

### Parsing Pipeline

```
PDF/DOCX → text extraction (pdfplumber/python-docx) → JSON → Master Index → Qdrant
```

- **Parser**: `pdf` (PDF source) or `docx` (DOCX source)
- **text_chars**: Character count of extracted text
- **source_signature**: `{file_size}:{mtime_ns}` for change detection

---

## 3. Source Sidecar Metadata (.metadata.json)

Each downloaded file has a sidecar with download provenance.

```json
{
  "downloaded_at": "2026-05-02T13:53:21.509015Z",
  "download_url": "https://esaj.tjsp.jus.br/cjsg/getArquivo.do?cdAcordao=19436885&cdForo=0",
  "source_url": "https://esaj.tjsp.jus.br/cjsg/resultadoCompleta.do",
  "cdacordao": "19436885",
  "content_type": "application/pdf;charset=utf-8",
  "file_size_bytes": 302844,
  "tribunal": "TJSP",
  "numero_processo": "1028537-43.2024.8.26.0003",
  "agent_id": "juris-search",
  "search_params": { "tribunal": "TJSP", "mode": "batch" },
  "result_description": "Processo 1028537-43.2024.8.26.0003 | Tipo: Apelação Cível | Relator: Henrique Rodriguero Clavisio | Comarca: de Origem: São Paulo"
}
```

---

## 4. Search History Record

Each search session produces a history file.

```json
{
  "job_id": "dfcc3341",
  "saved_at": "2026-05-02T09:05:30Z",
  "fields": {
    "search_text": "dano moral transporte aereo",
    "tribunal": "TJSP",
    "courts": ["TJSP"],
    "search_index": "inteiro_teor",
    "max_results": 50
  },
  "total": 42,
  "results": [
    {
      "cdacordao": "19436885",
      "numero_processo": "1028537-43.2024.8.26.0003",
      "relator": "Henrique Rodriguero Clavisio",
      "comarca": "São Paulo",
      "data_julgamento": "06/07/2025",
      "ementa": "Transporte aéreo público internacional...",
      "tribunal": "TJSP"
    }
  ]
}
```

---

## 5. Corpus Flat Structure

After flattening, all unique files are organized as:

```
corpus_flat/
  tjrs/           # 167 docs — TJRS decisions (inteiro_teor_<numero>_<ano>_<codigo>)
  tjsp/           # 2,485 files — TJSP decisions + sidecars (inteiro_teor_<cdacordao>)
  stf/            # 119 files — STF decisions (downloadPeca, paginador, numbered PDFs)
  cl/             # 11 files — Consumer Law reference materials (PDFs, markdown)
  _meta/          # 56 files — Infrastructure metadata (search_metadata.json, index.json)
```

### Storage Backends

| Backend | Collection | Port | Status |
|---------|-----------|------|--------|
| Master Index (JSON) | `master_index/master_index.json` | — | 885 docs |
| Qdrant (vectors) | `law_br` | 6333/6334 | Needs server install |
| Awareness (memory) | `juris_search_memory` | 8066 | Disabled by default |

### Retrieval Paths

1. **Filtered listing**: `/api/master-index/documents?tribunal=TJSP&year=2020&outcome=dado_provimento`
2. **Single document**: `/api/master-index/document/tjsp_19436885`
3. **Semantic search**: `/api/master-index/search` (POST `{"query": "dano moral em atraso de voo"}`) — requires Qdrant
4. **Full corpus stats**: `/api/master-index/stats`
5. **Citation network**: `/api/master-index/document/tjsp_19436885` → `cited_processes` + `co_relators`
