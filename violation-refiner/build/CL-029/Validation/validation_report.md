# Validation Report CL-029

Total: 18  
Pass: 13  
Warn: 5  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 4 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 4 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework L16752 declares source SHA 5ccad211… (cache bytes: 4a87dd4a…). INFO: framework L20285 declares source SHA b96e4db1… (cache bytes: 4e6f01df…).
- **V04 article_exists_in_framework_cache**: pass - All 6 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 30 cross-references resolve.
- **V06 element_coverage**: warn - 11 uncovered: ['CL.LEY16752.Art.3.j.elem.actividad_aviacion_civil: status=strong but no nexus_matrix entry', 'CL.LEY16752.Art.3.j.elem.resguardo_seguridad_vuelo: status=weak but no nexus_matrix entry', 'CL.LEY16752.Art.3.r.elem.sujeto_activo_dgac: status=strong but no nexus_matrix entry', 'CL.LEY16752.Art.3.z.elem.sujeto_activo_dgac: status=strong but no nexus_matrix entry', 'CL.LEY20285.Art.3.elem.conocimiento_contenidos: status=weak but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.sujeto_activo_proveedor: status=weak but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.informacion_oportuna: status=weak but no nexus_matrix entry', 'CL.LPDC.Art.3.b.elem.deber_de_informarse: status=contested but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.proveedor: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.venta_o_prestacion: status=strong but no nexus_matrix entry', 'CL.LPDC.Art.23.elem.falla_calidad: status=contested but no nexus_matrix entry']
- **V07 authorities_verification**: warn - 10/10 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.28 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 4 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 20 nexus row(s) checked; 8 cite a segment their element does not list as evidence. ['CL.LEY16752.Art.3.elem.dolo_o_negligencia_funcionaria <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11', 'CL.LEY16752.Art.3.j.elem.instrucciones_general_aplicacion <- I-002_17_NAR-21_STG_29.seg-24', 'CL.LEY16752.Art.3.r.elem.actuacion_reglada <- I-002_17_NAR-21_STG_29.seg-24', 'CL.LEY16752.Art.3.elem.dolo_o_negligencia_funcionaria <- I-002_17_NAR-21_STG_29.seg-59', 'CL.LEY20285.Art.3.elem.conocimiento_decisiones <- I-002_17_NAR-21_STG_29.seg-24', 'CL.LPDC.Art.3.b.elem.informacion_veraz <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11', 'CL.LPDC.Art.23.elem.negligencia <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11', 'CL.LPDC.Art.23.elem.negligencia <- I-002_17_NAR-21_STG_29.seg-59']
- **V14 dead_weight_articles**: warn - 2 established article(s) score 0 and only dilute the weighted mean: ['CL.LEY16752.Art.1 (score 0.0 over 4 element(s))', 'CL.LEY20285.Art.14 (score 0.0 over 3 element(s))']. Demote to a candidate or record as an open question.
- **V15 verbatim_hash_integrity**: pass - 4 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 10 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 22 open question(s) and 30 cross-reference(s) (52 item(s) compared). Contract-only related_violations: 0 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: warn - 34 grid pair(s) and 20 nexus row(s) checked; 6 warning(s): CL.LPDC.Art.3.b.elem.sujeto_activo_proveedor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.sujeto_pasivo_consumidor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.informacion_veraz: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.informacion_oportuna: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.condiciones_de_contratacion: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.deber_de_informarse: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient
