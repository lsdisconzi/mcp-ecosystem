# Validation Report CL-005

Total: 11  
Pass: 9  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 10 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 10 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CHIPENCOD self-reported SHA in metadata header (509efbf4…) does not match actual content SHA (5e189a4a…).
- **V04 article_exists_in_framework_cache**: pass - All 2 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 46 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.67 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
