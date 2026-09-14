# Validation Report CL-010

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 5 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 5 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CONST self-reported SHA in metadata header (26b530c1…) does not match actual content SHA (a42140a7…). | WARN: framework L20285 self-reported SHA in metadata header (b96e4db1…) does not match actual content SHA (4e6f01df…).
- **V04 article_exists_in_framework_cache**: pass - All 5 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 11 cross-references resolve.
- **V06 element_coverage**: warn - 5 uncovered: ['CL.CONST.T1.C1.Art.1.5.elem.igualdad_oportunidades: status=strong but no nexus_matrix entry', 'CL.CONST.T1.C1.Art.1.4.elem.condiciones_sociales_realizacion: status=contested but no nexus_matrix entry', 'CL.CONST.Art.19.1.elem.denegacion_sistematica_derechos: status=strong but no nexus_matrix entry', 'CL.L20285.Art.3.elem.deber_de_conocimiento: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.veracidad: status=strong but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.7 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
