# Validation Report CL-021

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 3 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 3 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHIPENCOD self-reported SHA in metadata header (509efbf4…) does not match actual content SHA (5e189a4a…). | WARN: framework CONST self-reported SHA in metadata header (26b530c1…) does not match actual content SHA (a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 5 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 20 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.6 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 24 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-CL021-AUTOR-IMPUTACION: blocks_element 'Art. 211 sujeto activo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-PARTE-FORMAL: blocks_element 'Art. 212 objeto material (parte/denuncia)' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-CONTENIDO-COMUNICACION-SEGURIDAD: blocks_element 'Art. 211 acto imputación' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-TIPO-PENAL-INVOCADO: blocks_element 'Art. 211 objeto material' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-IDENTIDAD-PASAJERO: blocks_element 'Art. 211 sujeto pasivo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-PREGUNTA-PASAJERO: blocks_element 'Art. 19.4 acto desencadenante' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-SEGMENTOS-NO-RECUPERADOS: blocks_element 'Art. 19.4 nexo causal' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-INSTRUCCION-PILOTO: blocks_element 'Art. 19.4 sujeto activo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-COMUNICACIONES-INTERNAS-TRIPULACION: blocks_element 'Art. 211 dolo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL021-HABILITACION-REGLAMENTARIA: blocks_element 'Art. 19.4 ilegitimidad' is not a 
