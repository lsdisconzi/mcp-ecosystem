We need to add a deduplication pass that identifies records referring to the same underlying court decision (by process number, CNJ number, court-specific ID, or content hash) and merges them, keeping the most complete representation.

## Changes to `juris_indexer.py`

1. **Add helper functions** to extract normalized keys from a `DocRecord`.
2. **Add `_deduplicate_records`** method that merges duplicates.
3. **Call `_deduplicate_records`** in `_scan()` after enrichment, before building the final document list.

Below are the exact code additions. Insert them into the existing file at the appropriate locations.

### 1. Normalized key extraction (add to `DocRecord` section or as module-level functions)

```python
def _normalize_process_number(num: Optional[str]) -> Optional[str]:
    """Return digits-only CNJ number for dedup matching."""
    if not num:
        return None
    return re.sub(r"[^0-9]", "", num)

def _record_dedup_keys(rec: DocRecord) -> List[str]:
    """Generate candidate deduplication keys for a record."""
    keys = []
    # e‑SAJ id
    if rec.cdacordao:
        keys.append(f"e-saj:{rec.cdacordao}")
    # Full CNJ number (digits only)
    norm_np = _normalize_process_number(rec.numero_processo)
    if norm_np:
        keys.append(f"cnj:{norm_np}")
        if rec.ano:
            keys.append(f"cnj:{norm_np}|ano:{rec.ano}")
    # TJRS composite key
    if rec.numero_processo and rec.ano and rec.codigo:
        keys.append(f"tjrs:{rec.numero_processo}:{rec.ano}:{rec.codigo}")
    # Content signature (for exact file duplicates)
    if rec.source_signature:
        keys.append(f"hash:{rec.source_signature}")
    return keys
```

### 2. The deduplication and merging logic (add as a new method in `JurisMasterIndexer`)

```python
def _deduplicate_records(self, records: Dict[str, DocRecord]) -> Dict[str, DocRecord]:
    """Merge records that represent the same document, keeping the richest one."""
    # index by dedup keys -> list of record ids
    idx: Dict[str, List[str]] = {}
    for rec_id, rec in records.items():
        for key in _record_dedup_keys(rec):
            idx.setdefault(key, []).append(rec_id)

    # process each group of duplicate keys
    merged_ids = set()
    final_map: Dict[str, DocRecord] = {}
    handled_ids = set()

    for dup_key, rec_ids in idx.items():
        if len(rec_ids) < 2:
            continue
        # choose the best primary record
        group = [records[rid] for rid in rec_ids]
        # prefer 'ready' > anything else; then prefer the one with more fields populated
        primary = max(group, key=lambda r: (
            0 if r.json_status == "ready" else 1,
            bool(r.relator),
            bool(r.ementa),
            bool(r.orgao_julgador),
            bool(r.data_julgamento),
            len(r.outcome),
        ))
        for other in group:
            if other is primary:
                continue
            # merge search metadata
            for job_id in other.search_jobs:
                if job_id not in primary.search_jobs:
                    primary.search_jobs.append(job_id)
            for term in other.search_terms:
                if term not in primary.search_terms:
                    primary.search_terms.append(term)
            for court in other.courts_searched:
                if court not in primary.courts_searched:
                    primary.courts_searched.append(court)
            # fill missing core fields if primary lacks them
            for field in [
                "tribunal", "numero_processo", "cnj_numero", "ano", "codigo",
                "classe", "tipo_processo", "relator", "orgao_julgador", "comarca",
                "data_julgamento", "data_publicacao", "data_registro",
                "ementa", "text_excerpt", "inteiro_url", "download_url",
                "file_size_bytes", "content_type", "parser", "json_status",
                "source_signature",
            ]:
                if not getattr(primary, field) and getattr(other, field):
                    setattr(primary, field, getattr(other, field))
            # merge lists (outcome, monetary_values, cited_processes, etc.)
            for src in other.outcome:
                if src not in primary.outcome:
                    primary.outcome.append(src)
            for val in other.monetary_values:
                if val not in primary.monetary_values:
                    primary.monetary_values.append(val)
            for proc in other.cited_processes:
                if proc not in primary.cited_processes:
                    primary.cited_processes.append(proc)
            # partes, advogados: keep the one that is non-empty
            if not primary.partes and other.partes:
                primary.partes = other.partes
            if not primary.advogados and other.advogados:
                primary.advogados = other.advogados
            if not primary.decisao and other.decisao:
                primary.decisao = other.decisao
            if not primary.legislacao_citada and other.legislacao_citada:
                primary.legislacao_citada = other.legislacao_citada
            if not primary.jurisprudencia_citada and other.jurisprudencia_citada:
                primary.jurisprudencia_citada = other.jurisprudencia_citada
            if not primary.assuntos and other.assuntos:
                primary.assuntos = other.assuntos
            if not primary.court_specific and other.court_specific:
                primary.court_specific = other.court_specific
            if not primary.texto_inteiro and other.texto_inteiro:
                primary.texto_inteiro = other.texto_inteiro
            if not primary.texto_length and other.texto_length:
                primary.texto_length = other.texto_length

        # primary will be kept; mark others as merged
        for rec_id in rec_ids:
            handled_ids.add(rec_id)
        final_map[primary.id] = primary

    # add any records not involved in any duplicate group
    for rec_id, rec in records.items():
        if rec_id not in handled_ids:
            final_map[rec_id] = rec

    return final_map
```

### 3. Integrate into `_scan()` (replace the records dictionary usage)

In the `_scan()` method, after the line:

```python
records[rec.id] = rec
```

and after the enrichment loop, **before** building the `documents` list, add:

```python
# Deduplicate records (merge duplicates by process number/cdacordao/hash)
records = self._deduplicate_records(records)
```

Then replace:

```python
documents = [_build_optimal_document(r) for r in records.values()]
```

The full order inside `_scan` would be:

1. Build `records` from JSON entries.
2. Cross-reference with search history, possibly creating synthetic records and adding to `records`.
3. Enrich from extractions.
4. **Call `_deduplicate_records` to merge duplicates.**
5. Transform to optimal schema and sort.

With these additions, the indexer will automatically consolidate documents that appear under different IDs (e.g., downloaded twice, referenced from multiple search jobs) into a single rich entry in `master_index.json`.