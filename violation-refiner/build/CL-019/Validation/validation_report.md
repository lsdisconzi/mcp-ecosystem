# Validation Report CL-019

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 1 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 1 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHIPENCOD self-reported SHA in metadata header (509efbf4…) does not match actual content SHA (5e189a4a…). | WARN: framework CONST self-reported SHA in metadata header (26b530c1…) does not match actual content SHA (a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 5 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 2 cross-references resolve.
- **V06 element_coverage**: warn - 16 uncovered: ['CL.CHIPENCOD.Art.211.elem.sujeto_activo: status=strong but no nexus_matrix entry', 'CL.CHIPENCOD.Art.211.elem.resultado_perjuicio: status=strong but no nexus_matrix entry', 'CL.CHIPENCOD.Art.212.elem.objeto_material: status=weak but no nexus_matrix entry', 'CL.CHIPENCOD.Art.212.elem.resultado_perjuicio: status=strong but no nexus_matrix entry', 'CL.CONST.Art.19.4.elem.sujeto_activo: status=strong but no nexus_matrix entry', 'CL.CONST.Art.19.4.elem.acto_ilicito_coaccion: status=strong but no nexus_matrix entry', 'CL.CONST.Art.19.4.elem.ilegitimidad: status=strong but no nexus_matrix entry', 'CL.CONST.Art.19.4.elem.nexo_causal: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.relacion_de_consumo: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.deber_informacion_veraz: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.oportunidad_informacion: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.intimidacion_como_obstaculo_informativo: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.sujeto_activo_proveedor: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.venta_o_prestacion_servicio: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.negligencia: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.nexo_causal: status=contested but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.56 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
