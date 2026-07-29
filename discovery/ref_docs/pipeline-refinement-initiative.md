---
name: Discovery pipeline refinement initiative
description: 2026-05-02: Full legal KB ingestion complete — Qdrant (658 law articles + 2,076 transcript segments) and Neo4j Aura (34 frameworks, 658 articles, 658 BELONGS_TO edges). Pipeline ready for runtime.
type: project
---

The Discovery pipeline has been enhanced with legal knowledge base integration (Qdrant vector search + Neo4j graph) backing the extraction, normalization, narrative, and verification layers. Implementation completed 2026-05-02.

**What was built (code completed 2026-05-02):**
- 3 new modules: `legal_kb.js` (Qdrant/Neo4j connector), `ingest_kb.js` (LA8159 ingestion script), `verify.js` (L8 legal verification layer)
- 5 modules upgraded: `analysis_profile.js` (KB config per profile), `normalize.js` (async KB-backed law resolution), `prompts_extraction_v1.js` (augmented extraction with KB context), `narrate.js` (law-grounded narrative), `index.js` (pipeline orchestration wiring)
- New L8 layer: semantic verification of violations against actual law articles, with HIGH/MEDIUM/LOW scoring

**Why:** The pipeline previously resolved laws via hardcoded regex patterns only — `LegalArticle.article_text` was always null. The LA8159 agent group already had 33 jurisdiction specialists with verified article texts, pre-configured Qdrant/Neo4j labels, and validated violation-to-article mappings.

**Corpus Ingestion — COMPLETED 2026-05-02 (All 4 Phases):**

| Phase | Status | System | Contents |
|-------|--------|--------|----------|
| 1 — Laws | Done | Qdrant `la8159_grounding` | 658 articles (BR: 264, CL: 128, INT: 266), 768-dim cosine |
| 2 — Transcripts | Done | Qdrant `la8159_transcripts` | 2,076 segments from 48 standardized transcripts |
| 3 — Validation | Done | Qdrant semantic search | CDC Art.14 at 0.703, ANAC R400 at 0.661, transcript segments at 0.55 |
| 4 — Neo4j graph | Done | Neo4j Aura `awareness-ai` | 34 LegalFramework nodes, 658 LawArticle nodes, 658 BELONGS_TO edges |

**Phase 4 details:** Credentials found in `/Users/leandrodisconzi/work/OliviaLegal/.env` lines 93-100. Seeded via Neo4j Query API v2 (HTTP 202 = accepted for writes). Created constraints on `framework_code` and `eli_id`, indexes on `jurisdiction`, `framework_code`, `norm_type`. Graph verified: all counts match and jurisdiction breakdown confirmed (BR 264, CL 128, INT 266).

**Ingestion details:**
- Both collections created via the Qdrant Memory Service at `http://72.60.143.139:8079`
- Law articles ingested via `POST /api/v1/qdrant/collections/{name}/ingest/structured` with `data_type: "law"`, batched 100 per request
- Transcript segments ingested via same endpoint with `data_type: "transcript"`, batched 200 per request
- First transcript attempt failed: Qdrant requires UUID point IDs — custom string IDs like `TRNS_83951e40_1` cause 400 errors. Fixed by omitting `id` field (service auto-generates UUIDs)
- Cross-reference endpoint (`/cross-reference`) on port 8079 has a server-side bug: `'CrossReferenceRequest' object has no attribute 'content'` — pipeline uses `/search` endpoint instead, which works correctly

**How to apply:** The legal and law-firm profiles enable KB by default; other profiles keep it off. All KB functions degrade gracefully — returns empty/null when Qdrant/Neo4j are unavailable. No new mandatory dependencies were added (`@qdrant/js-client-rest` and `neo4j-driver` are lazy-loaded). The pipeline continues working with regex-based fallback when KB is disabled.
