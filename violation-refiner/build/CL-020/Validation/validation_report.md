# Validation Report CL-020

Total: 11  
Pass: 7  
Warn: 4  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 7 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 7 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHIPENCOD self-reported SHA in metadata header (509efbf4…) does not match actual content SHA (5e189a4a…). | WARN: framework CONST self-reported SHA in metadata header (26b530c1…) does not match actual content SHA (a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 5 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 18 cross-references resolve.
- **V06 element_coverage**: warn - 2 uncovered: ['CL.CONST.Art.19.4.elem.ausencia_justificacion_legitima: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.prestacion_servicio: status=established but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.64 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 22 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-CL020-IMPUTADOR-IDENTIDAD: blocks_element 'Art. 211 sujeto activo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-IMPUTACION-DELITO-FORMAL: blocks_element 'Art. 211 acto imputación' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-OBJETO-MATERIAL-TIPO-PENAL: blocks_element 'Art. 211 objeto material' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-RAZON-FORMAL-DESEMBARCO: blocks_element 'Art. 211 falsedad' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-PARTE-DGAC-ART212: blocks_element 'Art. 212 objeto material' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-JUSTIFICACION-FORMAL-LATAM-CONST: blocks_element 'Art. 19.4 narrativa cambiante' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-RAZON-FORMAL-LPDC-VERACIDAD: blocks_element 'LPDC 3.b información veraz' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-COMUNICACIONES-INTERNAS-DOLO: blocks_element 'Art. 211 dolo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-DECLARACION-PERSONAL-DGAC: blocks_element 'Art. 211 dolo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL020-ARTICULO-APLICABLE-212: blocks_element 'Art. 212 adecuación global' is not
