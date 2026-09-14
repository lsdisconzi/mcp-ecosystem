# Validation Report INT-016

Total: 11  
Pass: 9  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 195 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 195 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework UNCRC self-reported SHA in metadata header (10b90d8f…) does not match actual content SHA (546b20d9…). | WARN: framework HAGUE1980 self-reported SHA in metadata header (1251031e…) does not match actual content SHA (5f4eb226…). | WARN: framework ACHR self-reported SHA in metadata header (5e4270a2…) does not match actual content SHA (0208ba5c…).
- **V04 article_exists_in_framework_cache**: pass - All 0 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 5 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
