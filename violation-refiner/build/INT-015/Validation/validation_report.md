# Validation Report INT-015

Total: 18  
Pass: 16  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 158 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 158 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework CONST declares source SHA 26b530c1… (cache bytes: b07956bc…). INFO: framework AN9 declares source SHA 3cedf261… (cache bytes: 57c4f76b…).
- **V04 article_exists_in_framework_cache**: pass - All 0 established articles present in cache.
- **V05 cross_references_resolve**: pass - No cross-references declared.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: warn - 158 cited segment(s) had a declarable source; 12 with an undeclared speaker. ["I-002_05_NAR-07_STG_7_post_removal_investigation.seg-41: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-43: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-44: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-46: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-47: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-48: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-49: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-50: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-67: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-84: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-93: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'", "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-114: speaker 'multi_party_audio' is not declared by 'I-002_05_NAR-07_STG_7_post_removal_investigation'"]
- **V13 evidence_nexus_coherence**: pass - 0 nexus row(s) checked; 0 cite a segment their element does not list as evidence.
- **V14 dead_weight_articles**: pass - No established article scores 0 over 0 grid(s).
- **V15 verbatim_hash_integrity**: pass - 158 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 0 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 0 open question(s) and 0 cross-reference(s) (0 item(s) compared). Contract-only related_violations: 0 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: pass - 0 element(s) shaped and closed; 0 nexus row(s) reference a declared pair; templates conform where present.
