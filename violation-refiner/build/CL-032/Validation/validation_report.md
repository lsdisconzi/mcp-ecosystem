# Validation Report CL-032

Total: 18  
Pass: 15  
Warn: 2  
Fail: 1

## Checks

- **V01 segment_resolution**: pass - 4 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 4 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework CONST declares source SHA 26b530c1… (cache bytes: b07956bc…).
- **V04 article_exists_in_framework_cache**: pass - All 2 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 13 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.64 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 4 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 20 nexus row(s) checked; 7 cite a segment their element does not list as evidence. ['CL.LPDC.Art.3.b.elem.proveedor_servicios <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-36', 'CL.LPDC.Art.3.b.elem.relacion_consumo <- I-002_18_NAR_LATAM_STG_2.seg-1', 'CL.LPDC.Art.3.b.elem.deber_informacion <- I-002_18_NAR_LATAM_STG_2.seg-24', 'CL.LPDC.Art.23.elem.proveedor <- I-002_18_NAR_LATAM_STG_2.seg-24', 'CL.LPDC.Art.23.elem.contexto_venta_servicio <- I-002_18_NAR_LATAM_STG_2.seg-1', 'CL.LPDC.Art.23.elem.fallas_deficiencias <- I-002_18_NAR_LATAM_STG_2.seg-24', 'CL.LPDC.Art.23.elem.relacion_causal <- I-002_18_NAR_LATAM_STG_2.seg-24']
- **V14 dead_weight_articles**: pass - No established article scores 0 over 2 grid(s).
- **V15 verbatim_hash_integrity**: pass - 4 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 0 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 10 open question(s) and 13 cross-reference(s) (23 item(s) compared). Contract-only related_violations: 0 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: fail - 1 issue(s): CL.LPDC.Art.23: template requires element(s) ['falla_calidad', 'venta_o_prestacion'] not present in the grid | warnings: CL.LPDC.Art.3.b.elem.calidad_de_consumidor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.proveedor_servicios: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.relacion_consumo: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.deber_informacion: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.solicitud_informacion: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.infraccion_informacion: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.perjuicio: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.23: grid has element(s) ['contexto_venta_servicio', 'fallas_deficiencias', 'relacion_causal'] outside its template
