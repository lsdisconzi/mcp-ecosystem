# Validation Report BR-005

Total: 11  
Pass: 8  
Warn: 3  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 47 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 47 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CDC self-reported SHA in metadata header (92a00d2f…) does not match actual content SHA (8e34dae2…). | WARN: framework R400 self-reported SHA in metadata header (89c4af2f…) does not match actual content SHA (3a6cbfdd…).
- **V04 article_exists_in_framework_cache**: pass - All 4 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 10 cross-references resolve.
- **V06 element_coverage**: warn - 22 uncovered: ['BR.CDC.T5.C4.Art.39.VII.elem.sujeto_ativo_fornecedor: status=strong but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.VII.elem.sujeto_pasivo_consumidor: status=strong but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.VII.elem.modalidade_repassar: status=contested but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.VII.elem.objeto_informacao_depreciativa: status=strong but no nexus_matrix entry', 'BR.CDC.T5.C4.Art.39.VII.elem.circunstancia_exercicio_direitos: status=strong but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.relacao_consumo: status=strong but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.pratica_abusiva: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.potencial_prejuizo: status=strong but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.dever_reprimido_eficaz: status=contested but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.subjetivo_dolo_ou_culpa: status=established but no nexus_matrix entry', 'BR.CDC.T2.Art.4.VI.elem.nexo_causal: status=strong but no nexus_matrix entry', 'BR.CDC.Art.14.elem.fornecedor_servicos: status=established but no nexus_matrix entry', 'BR.CDC.Art.14.elem.consumidor: status=established but no nexus_matrix entry', 'BR.CDC.Art.14.elem.defeito_servico: status=established but no nexus_matrix entry', 'BR.CDC.Art.14.elem.dano: status=strong but no nexus_matrix entry', 'BR.CDC.Art.14.elem.nexo_causal: status=strong but no nexus_matrix entry', 'BR.CDC.Art.14.elem.informacao_insuficiente: status=weak but no nexus_matrix entry', 'BR.R400.C2.S2.Art.22.elem.sujeito_ativo_transportador: status=established but no nexus_matrix entry', 'BR.R400.C2.S2.Art.22.elem.sujeito_passivo_passageiro: status=established but no nexus_matrix entry', 'BR.R400.C2.S2.Art.22.elem.apresentacao_para_embarque: status=strong but no nexus_matrix entry', 'BR.R400.C2.S2.Art.22.elem.voo_originalmente_contratado: status=strong but no nexus_matrix entry', 'BR.R400.C2.S2.Art.22.elem.deixar_de_transportar: status=strong but no nexus_matrix entry']
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.67 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
