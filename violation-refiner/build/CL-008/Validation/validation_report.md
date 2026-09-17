# Validation Report CL-008

Total: 18  
Pass: 14  
Warn: 3  
Fail: 1

## Checks

- **V01 segment_resolution**: pass - 5 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 5 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework L16752 declares source SHA 5ccad211… (cache bytes: 4a87dd4a…). INFO: framework CONST declares source SHA 26b530c1… (cache bytes: b07956bc…).
- **V04 article_exists_in_framework_cache**: pass - All 6 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 30 cross-references resolve.
- **V06 element_coverage**: warn - 6 uncovered: ['CL.L16752.T1.Art.1.elem.sujeto_obligado: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.sujeto_obligado: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.omision_impropia: status=strong but no nexus_matrix entry', 'CL.L16752.T2.Art.3.j.elem.tipicidad_subjetiva: status=contested but no nexus_matrix entry', 'CL.CONST.T1.C1.Art.6.elem.garantia_orden_institucional: status=contested but no nexus_matrix entry', 'CL.CONST.T1.C1.Art.5.elem.organo_estatal_obligado: status=strong but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.62 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 5 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 37 nexus row(s) checked; 4 cite a segment their element does not list as evidence. ['CL.L16752.T2.Art.3.j.elem.objeto_material <- I-002_24_NAR-19_STG_12.seg-69', 'CL.CONST.T1.C1.Art.5.elem.fuente_normativa_derechos <- I-002_10A_NAR-19_STG_19_counter_escalation.seg-13', 'CL.LPDC.Art.3.b.elem.bien_o_servicio_ofrecido <- I-002_24_NAR-19_STG_12.seg-14', 'CL.LPDC.Art.23.elem.sujeto_activo_proveedor <- I-002_24_NAR-19_STG_12.seg-69']
- **V14 dead_weight_articles**: pass - No established article scores 0 over 6 grid(s).
- **V15 verbatim_hash_integrity**: pass - 5 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 0 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 26 open question(s) and 30 cross-reference(s) (56 item(s) compared). Contract-only related_violations: 2 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: fail - 1 issue(s): CL.LPDC.Art.23: template requires element(s) ['falla_calidad', 'menoscabo', 'proveedor', 'venta_o_prestacion'] not present in the grid | warnings: CL.LPDC.Art.3.b.elem.relacion_de_consumo: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.bien_o_servicio_ofrecido: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.informacion_veraz: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.informacion_oportuna: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.sujeto_obligado_proveedor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.contenido_informativo_omitido: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.perjuicio_al_consumidor: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.3.b.elem.deber_informarse_responsablemente: article prefix drops hierarchy segments of CL.LPDC.Art.3.b; migrate when convenient; CL.LPDC.Art.23: grid has element(s) ['falla_deficiencia_servicio', 'menoscabo_consumidor', 'nexo_causal', 'sujeto_activo_proveedor', 'sujeto_pasivo_consumidor', 'venta_bien_o_prestacion_servicio'] outside its template
