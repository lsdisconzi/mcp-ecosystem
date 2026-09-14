# Validation Report BR-013

Total: 11  
Pass: 9  
Warn: 2  
Fail: 0

## Checks

- **V01 segment_resolution**: pass - 306 segment(s) checked; 0 unresolved.
- **V02 verbatim_quote_match**: pass - All 306 quote(s) checked against their cited segment.
- **V03 article_text_hash**: warn - WARN: framework CBA self-reported SHA in metadata header (38f7b071…) does not match actual content SHA (4ed35a5b…). | WARN: framework CDC self-reported SHA in metadata header (92a00d2f…) does not match actual content SHA (8e34dae2…). | WARN: framework R400 self-reported SHA in metadata header (89c4af2f…) does not match actual content SHA (3a6cbfdd…). | WARN: framework CONST self-reported SHA in metadata header (de946205…) does not match actual content SHA (b0b99bed…).
- **V04 article_exists_in_framework_cache**: pass - All 2 established articles present in cache.
- **V05 cross_references_resolve**: pass - All 7 cross-references resolve.
- **V06 element_coverage**: pass - Every scored element has at least one nexus_matrix entry.
- **V07 authorities_verification**: warn - No authorities listed. Jurisprudence/doctrine layer not populated.
- **V08 contract_consistency**: pass - Main and contract views agree on all overlapping fields.
- **V09 language_consistency**: pass - Bilingual fields (es/en) present throughout.
- **V10 confidence_derivation**: pass - Confidence 0.0 matches recomputed formula.
- **V11 enrichment_integrity**: pass - Enrichment integrity verified (segments, excerpts, nexus, authorities).
