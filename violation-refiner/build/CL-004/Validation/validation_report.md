# Validation Report CL-004

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 9 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 9 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHIPENCOD self-reported SHA in metadata header (509efbf4…) does not match actual content SHA (5e189a4a…). | WARN: framework L20285 self-reported SHA in metadata header (b96e4db1…) does not match actual content SHA (4e6f01df…).
- **V04 article_exists_in_framework_cache**: pass - All 7 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 25 cross-references resolve.
- **V06 element_coverage**: warn - 12 uncovered: ['CL.CHIPENCOD.Art.193.8.elem.perjuicio: status=established but no nexus_matrix entry', 'CL.CHIPENCOD.Art.194.elem.sujeto_pasivo: status=strong but no nexus_matrix entry', 'CL.CHIPENCOD.Art.194.elem.resultado_perjuicio: status=established but no nexus_matrix entry', 'CL.CHIPENCOD.Art.255.elem.sujeto_pasivo: status=established but no nexus_matrix entry', 'CL.CHIPENCOD.Art.255.elem.resultado_perjuicio: status=established but no nexus_matrix entry', 'CL.CPCL.Art.17.elem.resultado_perjuicio: status=established but no nexus_matrix entry', 'CL.L20285.Art.5.elem.perjuicio_al_afectado: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.relacion_de_consumo: status=established but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.perjuicio_al_consumidor: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.calidad_consumidor: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.prestacion_servicio: status=established but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.menoscabo_consumidor: status=established but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.72 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
