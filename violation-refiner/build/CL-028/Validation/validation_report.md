# Validation Report CL-028

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 5 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 5 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CDC self-reported SHA in metadata header (92a00d2f…) does not match actual content SHA (8e34dae2…). | WARN: framework CONST self-reported SHA in metadata header (de946205…) does not match actual content SHA (b0b99bed…).
- **V04 article_exists_in_framework_cache**: pass - All 3 established articles present in cache.
- **V05 cross_references_resolve**: pass - No cross-references declared.
- **V06 element_coverage**: warn - 16 uncovered: ['CL.CPCL.Art.416.elem.sujeto_activo: status=established but no nexus_matrix entry', 'CL.CPCL.Art.416.elem.sujeto_pasivo: status=established but no nexus_matrix entry', 'CL.CPCL.Art.416.elem.modalidad_tipica_expresion: status=established but no nexus_matrix entry', 'CL.CPCL.Art.416.elem.deshonra_descredito_menosprecio: status=weak but no nexus_matrix entry', 'CL.CPCL.Art.416.elem.dolo: status=weak but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.sujeto_activo: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.sujeto_pasivo: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.relacion_consumo: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.servicio_transporte: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.falta_informacion_veraz_oportuna: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.sujeto_activo_proveedor: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.contexto_comercial: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.deficiencia_calidad_servicio: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.negligencia: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.menoscabo_consumidor: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.relacion_causal: status=strong but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.72 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
