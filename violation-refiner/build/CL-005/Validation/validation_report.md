# Validation Report CL-005

Total: 18  
Pass: 16  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 10 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 10 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework CHIPENCOD declares source SHA 509efbf4… (cache bytes: 5e189a4a…).
- **V04 article_exists_in_framework_cache**: pass - All 2 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 116 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - 9/9 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.53 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 10 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: warn - 7 nexus row(s) checked; 1 cite a segment their element does not list as evidence. ['CL.CHIPENCOD.T4.C3.Art.193.8.elem.abuso_del_oficio <- I-002_05_NAR-07_STG_7_post_removal_investigation.seg-18']
- **V14 dead_weight_articles**: pass - No established article scores 0 over 1 grid(s).
- **V15 verbatim_hash_integrity**: pass - 10 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 9 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 25 open question(s) and 116 cross-reference(s) (141 item(s) compared). Contract-only related_violations: 3 (not asserted against cross_references; reciprocity is a graph-level audit).
- **V21 element_id_closure**: pass - 7 element(s) shaped and closed; 7 nexus row(s) reference a declared pair; templates conform where present.
