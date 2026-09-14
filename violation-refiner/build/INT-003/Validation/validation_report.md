# Validation Report INT-003

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 171 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 171 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHICAGO self-reported SHA in metadata header (8123f746…) does not match actual content SHA (c70710bf…).
- **V04 article_exists_in_framework_cache**: pass - All 1 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 22 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 9 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-003-STATE-REGISTRY: blocks_element 'sujeto_obligado' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-WRITTEN-PROOF: blocks_element 'ausencia_razones_escritas' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-AOC-FLIGHT: blocks_element 'sujeto_obligado' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-GAP-SEGMENTS: blocks_element 'falta_motivación_suficiente' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-DGAC-FOLLOWUP: blocks_element 'deferencia_autoridad_dgac' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-INTERNAL-DOC: blocks_element 'acto_denegación_embarque' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-LANGUAGE-FLUENCY: blocks_element 'confusión_pasajero' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-DGAC-CONTEXT-SEG40: blocks_element 'deferencia_autoridad_dgac' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-003-ECONOMIC-HARM: blocks_element 'perjuicio_pasajero' is not a known element_id
