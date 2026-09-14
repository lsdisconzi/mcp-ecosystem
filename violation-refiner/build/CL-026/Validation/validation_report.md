# Validation Report CL-026

Total: 11  
Pass: 7  
Warn: 4  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 7 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 7 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CDC self-reported SHA in metadata header (92a00d2f…) does not match actual content SHA (8e34dae2…). | WARN: framework CBA self-reported SHA in metadata header (38f7b071…) does not match actual content SHA (4ed35a5b…). | WARN: framework CONST self-reported SHA in metadata header (de946205…) does not match actual content SHA (b0b99bed…).
- **V04 article_exists_in_framework_cache**: pass - All 2 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 8 cross-references resolve.
- **V06 element_coverage**: warn - 1 uncovered: ['CL.LPDC.Art.23.1.elem.sujeto_activo_proveedor: status=established but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.7 matches recomputed formula.
- **V11 enrichment_integrity**: warn - 0 errors, 11 warning(s). W_OQ_BLOCKS_UNKNOWN@OQ-CL026-TICKET-CONTRACT: blocks_element 'BR.CONST.Art.5.XXXV.elem.titularidade_do_direito' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-PROTOCOL-DOCS: blocks_element 'BR.CONST.Art.5.XXXV.elem.obstaculo_al_acceso_jurisdiccional' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-FORMAL-DENIAL: blocks_element 'BR.CONST.Art.5.XXXV.elem.obstaculo_al_acceso_jurisdiccional' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-TICKET-COUNT: blocks_element 'BR.CONST.Art.5.XXXV.elem.fragmentacion_documental_como_medio' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-SYSTEM-EVIDENCE: blocks_element 'BR.CONST.Art.5.XXXV.elem.fragmentacion_documental_como_medio' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-ACCEPT-CONTENT: blocks_element 'BR.CONST.Art.5.XXXV.elem.conducta_coercitiva_que_inhibe_reclamo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-WAIVER-CLAUSE: blocks_element 'BR.CONST.Art.5.XXXV.elem.conducta_coercitiva_que_inhibe_reclamo' is not a known element_id; W_OQ_BLOCKS_UNKNOWN@OQ-CL026-DERIVATION-COUNT: blocks_element 'BR.CONST.Art.5.XXXV.elem.derivacion_burocratica_sistematica' is not a known element_id; W_OQ_BLOCK
