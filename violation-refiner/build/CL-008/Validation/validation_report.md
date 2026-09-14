# Validation Report CL-008

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 5 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 5 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework L16752 self-reported SHA in metadata header (5ccad211…) does not match actual content SHA (4a87dd4a…). | WARN: framework CONST self-reported SHA in metadata header (26b530c1…) does not match actual content SHA (a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 6 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 30 cross-references resolve.
- **V06 element_coverage**: warn - 6 uncovered: ['CL.L16752.T1.Art.1.elem.sujeto_obligado: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.sujeto_obligado: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.omision_impropia: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.tipicidad_subjetiva: status=contested but no nexus_matrix entry', 'CL.CONST.T1.C1.Art.6.elem.garantia_orden_institucional: status=contested but no nexus_matrix entry', 'CL.CONST.T1.C1.Art.5.elem.organo_estatal_obligado: status=strong but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.62 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
