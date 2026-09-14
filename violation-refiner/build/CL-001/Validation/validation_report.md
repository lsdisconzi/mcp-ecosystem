# Validation Report CL-001

Total: 11  
Pass: 9  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 10 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 10 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache.
- **V04 article_exists_in_framework_cache**: pass - All 0 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 6 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - 12/12 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 35 warning(s). W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-DENEGACION-JURI: supports entry 'acto_denegacion' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-DENEGACION-JURI: supports entry 'omision_opciones' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-DENEGACION-JURI: supports entry 'omision_compensacion' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-CAUSA-FALSA-JURI: supports entry 'causa_invocada_falsa' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-CAUSA-FALSA-JURI: supports entry 'conocimiento_falsedad' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-CACH133-REGISTRO-FALSO-JURI: supports entry 'persistencia_registro_falso' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-RESPONSABILIDAD-CIVIL-AEROLINEA-JURI: supports entry 'causa_invocada_falsa' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-RESPONSABILIDAD-CIVIL-AEROLINEA-JURI: supports entry 'omision_compensacion' matches neither an article_id nor an element_id; W_AUTH_DANGLING_SUPPORT@AUTH-ELEMENTO-SUB
