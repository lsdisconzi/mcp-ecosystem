# Validation Report CL-018

Total: 11  
Pass: 9  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 4 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 4 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache.
- **V04 article_exists_in_framework_cache**: pass - All 1 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 45 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.56 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 8 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-018-COMP-OFFER: blocks_element 'compensacion_incumplida' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-COMP-RECORDS: blocks_element 'compensacion_incumplida' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-INTERNAL-DOCS: blocks_element 'objeto_material_documentacion' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-CORP-POLICY: blocks_element 'dolo_institucional' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-PNR-TITLE: blocks_element 'sujeto_pasivo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-PAX-RESPONSE: blocks_element 'denegacion_involuntaria' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-SYSTEMIC-PATTERN: blocks_element 'evasion_documental' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-018-ALT-FLIGHT: blocks_element 'resultado_perjuicio' is not a known element_id
