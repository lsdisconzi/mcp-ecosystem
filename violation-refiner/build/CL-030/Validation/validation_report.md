# Validation Report CL-030

Total: 18  
Pass: 15  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 5 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 5 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache.
- **V04 article_exists_in_framework_cache**: pass - All 3 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 79 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - 9/9 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.31 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 5 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 31 nexus row(s) checked; 15 cite a segment their element does not list as evidence. ['CL.CPCL.T4.Art.255.elem.sujeto_activo_empleado_publico <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.T4.Art.255.elem.sujeto_activo_empleado_publico <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.CPCL.T4.Art.255.elem.acto_del_servicio <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.T4.Art.255.elem.acto_del_servicio <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.CPCL.T4.Art.255.elem.sujeto_pasivo_personas <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.CPCL.T4.Art.255.elem.sujeto_pasivo_personas <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.LPDC.Art.3.b.elem.sujeto_titular_consumidor <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.LPDC.Art.3.b.elem.calidad_veraz <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.3.b.elem.calidad_veraz <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.LPDC.Art.3.b.elem.calidad_oportuna <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.3.b.elem.calidad_oportuna <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11', 'CL.LPDC.Art.23.elem.negligencia <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-1', 'CL.LPDC.Art.23.elem.negligencia <- I-002_03_NAR-05_STG_5_aircraft_removal.seg-11']
- **V14 dead_weight_articles**: pass - No established article scores 0 over 3 grid(s). Marginally scored (<= 0.2): ['CL.LPDC.Art.23 (score 0.200)'].
- **V15 verbatim_hash_integrity**: pass - 5 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 9 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 18 open question(s) and 79 cross-reference(s) (97 item(s) compared). Contract-only related_violations: 0 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: warn - 17 grid pair(s) and 31 nexus row(s) checked; 7 warning(s): CL.LPDC.Art.3.b.elem.sujeto_titular_consumidor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.sujeto_obligado_proveedor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.calidad_veraz: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.calidad_oportuna: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.deber_informarse_responsablemente: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.perjuicio_consumidor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient
