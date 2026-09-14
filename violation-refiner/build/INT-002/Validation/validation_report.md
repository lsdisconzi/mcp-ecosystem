# Validation Report INT-002

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 160 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 160 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHICAGO self-reported SHA in metadata header (8123f746…) does not match actual content SHA (c70710bf…). | WARN: framework VCLT self-reported SHA in metadata header (f01906ba…) does not match actual content SHA (7f74e729…).
- **V04 article_exists_in_framework_cache**: pass - All 3 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 25 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 17 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-INT002-DGAC-ROLE: blocks_element 'Art. 37 sujeto activo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-ANNEX9-TEXT: blocks_element 'Art. 38 estándar OACI' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-ICAO-NOTIF: blocks_element 'Art. 38 omisión notificación' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-CHICAGO-RATIF: blocks_element 'VCLT 26 tratado en vigor' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-DOC-IDENTITY: blocks_element 'Art. 37 objeto material' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-CAUSAL-FLIGHT: blocks_element 'Art. 37 nexo causal' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-DGAC-ADMINACT: blocks_element 'Art. 38 conocimiento estatal' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-LATAM-INTERNAL: blocks_element 'VCLT 26 mala fe' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-LATAM-ATTRIBUTION: blocks_element 'Art. 38 incumplimiento' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-DGAC-TRAINING: blocks_element 'Art. 37 conocimiento incumplimiento' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-INT002-ICAO-COMPARATIVE: blocks_element 'Art. 
