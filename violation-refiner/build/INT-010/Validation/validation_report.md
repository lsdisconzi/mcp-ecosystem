# Validation Report INT-010

Total: 18  
Pass: 13  
Warn: 2  
Fail: 3

## Checks

- **V01 segment_resolution**: pass - 428 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 428 quote(s) checked against their cited segment.
- **V03 article_text_hash**: fail - FAIL: INT.ACHR.Art.1.1 excerpt not present in framework cache as quoted.
- **V04 article_exists_in_framework_cache**: fail - ['INT.ACHR.Art.1.1: not present in framework cache']
- **V05 cross_references_resolve**: pass - All 9 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: fail - 1 error(s), 0 warning(s). E_ARTICLE_BODY_MISSING@INT.ACHR.Art.1.1: framework ACHR returned no body for 'INT.ACHR.Art.1.1'
- **V12 speaker_attribution**: warn - 428 cited segment(s) had a declarable source; 21 with an undeclared speaker. ["I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-284: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-285: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-292: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-294: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-297: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-302: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-313: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-328: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-344: speaker 'multi_party_audio' is not declared by 'I-002_04_NAR-06_STG_6_jetbridge_standoff'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-41: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-43: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-44: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-46: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-47: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-48: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-49: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-50: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-67: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-84: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-93: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-114: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'"]
- **V13 evidence_nexus_coherence**: pass - 0 nexus row(s) checked; 0 cite a segment their element does not list as evidence.
- **V14 dead_weight_articles**: pass - No established article scores 0 over 0 grid(s).
- **V15 verbatim_hash_integrity**: pass - 428 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 0 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 3 open question(s) and 9 cross-reference(s) (12 item(s) compared). Contract-only related_violations: 0 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: pass - 0 element(s) shaped and closed; 0 nexus row(s) reference a declared pair; templates conform where present.
