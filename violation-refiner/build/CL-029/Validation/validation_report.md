# Validation Report CL-029

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 4 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 4 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework L16752 self-reported SHA in metadata header (5ccad211…) does not match actual content SHA (4a87dd4a…). | WARN: framework L20285 self-reported SHA in metadata header (b96e4db1…) does not match actual content SHA (4e6f01df…).
- **V04 article_exists_in_framework_cache**: pass - All 6 established articles present in cache.
- **V05 cross_references_resolve**: pass - No cross-references declared.
- **V06 element_coverage**: warn - 17 uncovered: ['CL.LEY16752.Art.3.elem.deber_fiscalizacion: status=strong but no nexus_matrix entry', 'CL.LEY16752.Art.3.elem.incumplimiento_por_omision: status=contested but no nexus_matrix entry', 'CL.LEY16752.Art.3.elem.perjuicio_al_pasajero: status=established but no nexus_matrix entry', 'CL.LEY20285.Art.3.elem.sujeto_activo: status=established but no nexus_matrix entry', 'CL.LEY20285.Art.3.elem.ejercicio_funcion_publica: status=established but no nexus_matrix entry', 'CL.LEY20285.Art.3.elem.incumplimiento: status=contested but no nexus_matrix entry', 'CL.LEY20285.Art.3.elem.perjuicio: status=weak but no nexus_matrix entry', 'CL.LEY20285.Art.14.elem.sujeto_activo: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.sujeto_activo_proveedor: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.sujeto_pasivo_consumidor: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.perjuicio: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.calidad_proveedor: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.relacion_consumo: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.actuacion_negligente: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.menoscabo_consumidor: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.nexo_causal: status=weak but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.anormalidad_servicio: status=contested but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.39 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
