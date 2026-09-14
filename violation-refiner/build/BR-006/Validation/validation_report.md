# Validation Report BR-006

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 47 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 47 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CDC self-reported SHA in metadata header (92a00d2f…) does not match actual content SHA (8e34dae2…). | WARN: framework R400 self-reported SHA in metadata header (89c4af2f…) does not match actual content SHA (3a6cbfdd…).
- **V04 article_exists_in_framework_cache**: pass - All 5 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 4 cross-references resolve.
- **V06 element_coverage**: warn - 24 uncovered: ['BR.CDC.Art.4.elem.sujeto_activo_proveedor: status=established but no nexus_matrix entry', 'BR.CDC.Art.4.elem.sujeto_pasivo_consumidor: status=established but no nexus_matrix entry', 'BR.CDC.Art.4.elem.realizacion_en_el_ejercicio_de_la_actividad: status=established but no nexus_matrix entry', 'BR.CDC.Art.4.elem.modalidad_tipica_violacion_dignidad: status=established but no nexus_matrix entry', 'BR.CDC.Art.4.elem.objeto_material_dignidad: status=established but no nexus_matrix entry', 'BR.CDC.Art.4.elem.resultado_perjuicio_moral: status=strong but no nexus_matrix entry', 'BR.CDC.Art.4.elem.tipicidad_subjetiva_dolo: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.I.elem.condicao_de_consumidor: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.I.elem.condicao_de_fornecedor: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.I.elem.relacao_de_consumo: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.I.elem.vulnerabilidade_factual: status=strong but no nexus_matrix entry', 'BR.CDC.Art.42.elem.sujeito_passivo_consumidor: status=established but no nexus_matrix entry', 'BR.CDC.Art.42.elem.conduta_proibida_ridiculo_constrangimento_ameaca: status=strong but no nexus_matrix entry', 'BR.CDC.Art.42.elem.sujeito_ativo_fornecedor: status=established but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.elem.relacao_consumo: status=established but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.elem.pratica_abusiva_generica: status=strong but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.elem.prevalecer_fraqueza: status=contested but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.elem.dano_moral: status=strong but no nexus_matrix entry', 'BR.R400.Art.26.elem.evento_qualificador: status=strong but no nexus_matrix entry', 'BR.R400.Art.26.elem.qualidade_passageiro: status=established but no nexus_matrix entry', 'BR.R400.Art.26.elem.obrigacao_assistencia: status=weak but no nexus_matrix entry', 'BR.R400.Art.26.elem.oferecimento_assistencia: status=established but no nexus_matrix entry', 'BR.R400.Art.26.elem.adequacao_assistencia: status=strong but no nexus_matrix entry', 'BR.R400.Art.26.elem.responsabilidade_transportador: status=established but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.66 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
