# Intelligence Pipeline — Integration Guide

> Discovery · Layers L5–L7 · Ontology v2.4
> Drop these files into `case-server/pipeline/`

---

## Files

| File | Layer | Description |
|------|-------|-------------|
| `dedup.js` | L5 | Exact + near-duplicate detection (Jaccard shingles) |
| `prompts_extraction_v1.js` | L5b | Ontology v2.4 extraction prompt template |
| `llm_extract.js` | L5b | LLM call → Action/Evidence/Violation/ActorRole nodes |
| `normalize.js` | L6 | ELI resolution, Case graph assembly, actor dedup |
| `narrate.js` | L7 | Chronological narrative, timeline, gap report |
| `index.js` | All | Updated orchestrator — replaces existing `pipeline/index.js` |
| `server_routes_to_add.js` | API | New routes to paste into `auto_server_builder.js` |

---

## Installation

```bash
# 1. Copy into your pipeline directory
cp dedup.js llm_extract.js prompts_extraction_v1.js normalize.js narrate.js \
  /path/to/Discovery/case-server/pipeline/

# 2. Replace the pipeline orchestrator
cp index.js /path/to/Discovery/case-server/pipeline/index.js

# 3. Add server routes
# Paste the contents of server_routes_to_add.js into auto_server_builder.js
# after the existing /api/pipeline/* routes

# 4. Add two methods to store.js (if not already there)
# store.setDedupResults(results)
# store.setExtractionResults(results)
```

---

## Running the Pipeline

### Via API (recommended)

```bash
# Trigger full L5–L7 run
curl -X POST http://localhost:3010/api/intelligence/run \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-ant-YOUR_KEY", "concurrency": 3}'

# Check results
curl http://localhost:3010/api/intelligence/summary
curl http://localhost:3010/api/intelligence/violations?severity=high
curl http://localhost:3010/api/intelligence/narrative
curl http://localhost:3010/api/intelligence/gap-report
curl http://localhost:3010/api/intelligence/law-registry?needs_argus=true
```

### Via Node (programmatic)

```javascript
const { runPipeline, runIntelligencePipeline, extendStore } = require('./pipeline');
const fs   = require('fs');
const path = require('path');

// Step 1: L0–L4 (already running on server start)
const { store } = runPipeline(files, rootDir, { incremental: true });

// Step 2: L5–L7
extendStore(store);
const result = await runIntelligencePipeline(store, rootDir, {
  apiKey:     process.env.ANTHROPIC_API_KEY,
  model:      'deepseek-v4-pro',
  outputDir:  path.join(rootDir, '_intelligence'),
  concurrency: 3
});

console.log('Narrative written to:', result.output_files.narrative);
console.log('Violations:', result.stats.total_violations);
console.log('Gaps:', result.stats.gap_count);
```

---

## Output Files

All written to `{rootDir}/_intelligence/`:

| File | Description |
|------|-------------|
| `dedup_report.json` | Exact/near-dup clusters, canonical file map |
| `extraction_results.json` | Raw L5b output per file (LLM nodes) |
| `case_graph.json` | Full ontology v2.4 graph (Case → Violation → Action → Evidence → SourceFile) |
| `violations.json` | Article-mapped violations with confidence |
| `law_registry.json` | All law refs — resolved ELI IDs + unresolved |
| `timeline.json` | Chronological event sequence |
| `narrative.md` | Human-readable case narrative |
| `gap_report.json` | Ontology invariant violations + recommendations |
| `pipeline_summary.json` | Run stats + all output file paths |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/intelligence/run` | Trigger full L5–L7 run |
| GET  | `/api/intelligence/run-stream` | SSE streaming run |
| GET  | `/api/intelligence/summary` | Run stats + file paths |
| GET  | `/api/intelligence/case-graph` | Full v2.4 graph |
| GET  | `/api/intelligence/violations?severity=high&min_confidence=0.7` | Filtered violations |
| GET  | `/api/intelligence/timeline` | Chronological events |
| GET  | `/api/intelligence/narrative?format=md` | Case narrative |
| GET  | `/api/intelligence/gap-report` | Invariant gaps |
| GET  | `/api/intelligence/law-registry?needs_argus=true` | Law references |
| GET  | `/api/intelligence/dedup-report?summary=true` | Dedup stats |

---

## Traceability Path (Ontology v2.4)

Every violation is fully traceable:

```
Violation
  └─ GROUNDED_IN_ACTION → Action
       └─ SUPPORTS_ACTION ← Evidence
            └─ _source_file_id → SourceFile
                 └─ (in) SourcePack
```

And every LLM call is audited:
```
LLMRun {
  model:          "deepseek-v4-pro"
  prompt_version: "legal-extraction-v1.0"
  pipeline_stage: "extraction"
  timestamp:      "2026-03-09T..."
}
```

---

## Next Step: Argus Enrichment

After running the pipeline, law references marked `needs_argus: true` in
`law_registry.json` should be enriched with full article text:

```bash
# For each eli_id in law_registry where needs_argus = true:
curl http://localhost:8029/api/law/articles/BR.CDC.Art.14
```

This populates `article_text` on LegalArticle stub nodes,
completing the traceability chain to the actual legal text.

---

*Discovery Intelligence Pipeline · Ontology v2.4 · Awareness-AI*
