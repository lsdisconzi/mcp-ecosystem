# Validation Report CL-030

Total: 18  
Pass: 16  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 40 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 40 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework CONST declares source SHA 26b530c1… (cache bytes: a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 3 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 79 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - 14/16 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.58 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 40 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 52 nexus row(s) checked; 26 cite a segment their element does not list as evidence. ['CL.CPCL.C1.Art.255.elem.sujeto_activo_empleado_publico <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.C1.Art.255.elem.sujeto_activo_empleado_publico <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.CPCL.C1.Art.255.elem.acto_del_servicio <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.C1.Art.255.elem.acto_del_servicio <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-284', 'CL.CPCL.C1.Art.255.elem.vejacion_injusta <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.C1.Art.255.elem.sujeto_pasivo_personas <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.C1.Art.255.elem.dolo <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.C1.Art.255.elem.dolo <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-300', 'CL.CPCL.C1.Art.255.elem.dolo <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-301', 'CL.CPCL.C1.Art.255.elem.dolo <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-302', 'CL.CPCL.C1.Art.269_ter.elem.sujeto_activo_funcionario_policial <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-141', 'CL.CPCL.C1.Art.269_ter.elem.sujeto_activo_funcionario_policial <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-143', 'CL.CPCL.C1.Art.269_ter.elem.ocultamiento_o_alteracion <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-149', 'CL.CPCL.C1.Art.269_ter.elem.ocultamiento_o_alteracion <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-167', 'CL.LPDC.Art.23.elem.proveedor <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.23.elem.proveedor <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.LPDC.Art.23.elem.venta_o_prestacion <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.23.elem.venta_o_prestacion <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-73', 'CL.LPDC.Art.23.elem.venta_o_prestacion <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11', 'CL.LPDC.Art.23.elem.negligencia <- I-002_01_NAR-01_STG_1_pre_boarding.seg-4', 'CL.LPDC.Art.23.elem.negligencia <- I-002_01_NAR-01_STG_1_pre_boarding.seg-3', 'CL.LPDC.Art.23.elem.menoscabo <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-36', 'CL.LPDC.Art.23.elem.menoscabo <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-58', 'CL.LPDC.Art.23.elem.menoscabo <- I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-284', 'CL.LPDC.Art.23.elem.falla_calidad <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.23.elem.falla_calidad <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11']
- **V14 dead_weight_articles**: pass - No established article scores 0 over 3 grid(s).
- **V15 verbatim_hash_integrity**: pass - 40 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 16 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 20 open question(s) and 79 cross-reference(s) (99 item(s) compared). Contract-only related_violations: 12 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: pass - 13 element(s) shaped and closed; 52 nexus row(s) reference a declared pair; templates conform where present.
