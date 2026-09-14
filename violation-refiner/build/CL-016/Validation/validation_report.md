# Validation Report CL-016

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 10 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 10 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache.
- **V04 article_exists_in_framework_cache**: pass - All 1 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 16 cross-references resolve.
- **V06 element_coverage**: warn - 10 uncovered: ['CL.CACH.Art.133.1.elem.omision_opcion_reembarque: status=strong but no nexus_matrix entry', 'CL.CACH.Art.133.1.elem.omision_opcion_reembolso: status=strong but no nexus_matrix entry', 'CL.CACH.Art.133.2.elem.omision_compensacion: status=strong but no nexus_matrix entry', ': status=strong but no nexus_matrix entry', ': status=strong but no nexus_matrix entry', ': status=strong but no nexus_matrix entry', ': status=strong but no nexus_matrix entry', ': status=established but no nexus_matrix entry', ': status=established but no nexus_matrix entry', ': status=established but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.76 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 8 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-016-CAUSAL: blocks_element 'denegacion_involuntaria' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-BOARDINGPASS: blocks_element 'sujeto_obligado' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-FLUJO-INTERNO: blocks_element 'fabricacion_fraudulenta' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-CCTV: blocks_element 'denegacion_involuntaria' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-PDI-ACTA: blocks_element 'denegacion_involuntaria' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-IMPUTACION-PJ: blocks_element 'dolo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-DISTANCIA: blocks_element 'omision_compensacion' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-016-REEMBARQUE-POSTERIOR: blocks_element 'omision_reembarque, omision_reembolso' is not a known element_id
