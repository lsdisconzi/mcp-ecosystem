# Validation Report CL-030

Total: 17  
Pass: 16  
Warn: 1  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 40 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 40 quote(s) checked against their cited segment.
- **V03 article_text_hash**: pass - All article-text hashes and excerpts match the framework cache. INFO: framework CONST declares source SHA 26b530c1… (cache bytes: a42140a7…).
- **V04 article_exists_in_framework_cache**: pass - All 3 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 12 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - 6/8 authorities pending verification. None auto-populated with rol numbers (correct: prevents fabrication). External verification pass required before legal-filing use.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.72 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
- **V12 speaker_attribution**: pass - 40 cited segment(s) had a declarable source; 0 with an undeclared speaker.
- **V13 evidence_nexus_coherence**: pass - 50 nexus row(s) checked; 0 cite a segment their element does not list as evidence.
- **V14 dead_weight_articles**: pass - No established article scores 0 over 3 grid(s).
- **V15 verbatim_hash_integrity**: pass - 40 verbatim hash(es) recomputed; 0 mismatch.
- **V16 authority_verification_coherence**: pass - 8 authorit(ies) coherent with the stored verification factor; every unverified stub states what would settle it and every verified authority names its protocol.
- **V17 cross_view_consistency**: pass - Bundle and contract agree on 7 open question(s) and 12 cross-reference(s) (19 item(s) compared). Contract-only related_violations: 12 (not asserted against cross_references; reciprocity is a graph-level audit).
