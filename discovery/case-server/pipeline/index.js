/**
 * Pipeline Orchestrator — All Layers
 * 
 * Layer sequence:
 *   L0  ingest.js      — SHA-256, filesystem stats, ingestion manifest
 *   L1  extract.js     — encoding, line/word counts, text preview
 *   L2  classify.js    — language, domain, auto-tags
 *   L3  analyze.js     — regex entity extraction (fast, offline)
 *   L4  relate.js      — cross-file relationship graph, temporal clusters
 *   ── new layers ──
 *   L5  dedup.js       — exact + near-duplicate detection
 *   L5b llm_extract.js — LLM extraction → ontology v2.4 nodes
 *   L6  normalize.js   — ELI resolution, Case graph assembly
 *   L7  narrate.js     — chronological narrative, timeline, gap report
 * 
 * L5–L7 are optional and require an API key.
 * L0–L4 always run (fast, offline).
 * 
 * Usage:
 *   const { runPipeline, runIntelligencePipeline } = require('./pipeline');
 *   
 *   // Basic (L0–L4, no LLM)
 *   const { store, stats } = runPipeline(files, rootDir, options);
 *   
 *   // Full (L0–L7, with LLM)
 *   const result = await runIntelligencePipeline(files, rootDir, {
 *     apiKey: 'sk-ant-...',
 *     model:  'deepseek-v4-pro',
 *     outputDir: './output'
 *   });
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const crypto = require('crypto');

// L0–L4 (existing)
const { createStore }   = require('./store');
const { processFile: ingestFile } = require('./ingest');
const { processFile: extractMeta } = require('./extract');
const { processFile: classifyFile } = require('./classify');
const { processFile: analyzeContent } = require('./analyze');
const { processAll: processRelationships } = require('./relate');

// Layer C — Corpus Comprehension
const { runComprehension }            = require('./comprehend');

// L5–L7 (new intelligence layers)
const { runDedup }                    = require('./dedup');
const { extractBatch }                = require('./llm_extract');
const { normalizeExtractionResults }  = require('./normalize');
const { runNarrative }                = require('./narrate');

// Layer E — Event Formalization + Case State Engine
const { formalizeEvents }             = require('./events');
const { evaluateCaseState }           = require('./case_state');
const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile,
  getKbConfig
} = require('./analysis_profile');

// Layer K — Knowledge Base Integration
const { isAvailable: kbIsAvailable }   = require('./legal_kb');

// Layer L8 — Legal Verification
const { verifyAllViolations, generateVerificationReport, renderVerificationMarkdown } = require('./verify');

const MIME_TYPE_BY_EXTENSION = {
  '.csv': 'text/csv',
  '.eml': 'message/rfc822',
  '.env': 'text/plain',
  '.gif': 'image/gif',
  '.htm': 'text/html',
  '.html': 'text/html',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.md': 'text/markdown',
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.py': 'text/x-python',
  '.sh': 'application/x-sh',
  '.sql': 'application/sql',
  '.svg': 'image/svg+xml',
  '.ts': 'application/typescript',
  '.tsv': 'text/tab-separated-values',
  '.txt': 'text/plain',
  '.xml': 'application/xml',
  '.yaml': 'text/yaml',
  '.yml': 'text/yaml'
};

function buildFileNodeId(fileRef, sha256) {
  const seed = sha256 || fileRef;
  return `FILE_${crypto.createHash('md5').update(seed).digest('hex').slice(0, 8)}`;
}

function normalizeL0(filePath, rootDir, ingestionId) {
  const ingested = ingestFile(filePath, rootDir, ingestionId);
  const data = ingested.data || {};
  const extension = data.extension || path.extname(filePath).toLowerCase();
  const sha256 = ingested.hash || data.hash_sha256 || null;

  return {
    ...data,
    file_ref: data.relative_path,
    sha256,
    mime_type: MIME_TYPE_BY_EXTENSION[extension] || 'application/octet-stream',
    file_node_id: buildFileNodeId(data.relative_path, sha256)
  };
}

// ─── L0–L4 Pipeline (unchanged, fast, offline) ────────────────────────────────

function runPipeline(files, rootDir, options = {}) {
  const {
    storeFile   = path.join(rootDir, 'pipeline_store.json'),
    incremental = true
  } = options;

  const store  = createStore(storeFile);
  const errors = [];
  const ingestionId = `ING_${Date.now().toString(36)}`;
  let processed = 0, cached = 0;

  for (const filePath of files) {
    try {
      // L0 — Ingest
      const L0 = normalizeL0(filePath, rootDir, ingestionId);
      const key = L0.sha256;

      if (!key) {
        throw new Error('file could not be hashed');
      }

      if (incremental && store.hasFile(key)) {
        const existing = store.getFile(key);
        if (existing && existing.file_ref !== L0.file_ref) {
          store.setFile(key, { ...existing, file_ref: L0.file_ref });
        }
        cached++;
        continue;
      }

      // L1 — Extract metadata
      const L1 = extractMeta(filePath, L0.extension);

      // L2 — Classify
      const L2 = classifyFile(L0.file_ref, L0.extension, L1.preview || null);

      // L3 — Analyze content
      const L3 = analyzeContent(L1.preview || '', L0.file_ref);

      // Store L0–L3
      store.setFile(key, {
        file_ref: L0.file_ref,
        layers:   { L0, L1, L2, L3 }
      });

      processed++;
    } catch (err) {
      errors.push({ file: filePath, error: err.message });
    }
  }

  // L4 — Relationships (global pass)
  const L4result = processRelationships(store);
  store.recordRun({
    root_dir: rootDir,
    total_files: files.length,
    processed,
    cached,
    failed: errors.length,
    l4: L4result
  });
  store.save();

  const stats = {
    processed,
    cached,
    skipped: cached,
    failed: errors.length,
    total:  files.length,
    l4: L4result
  };

  return { store, stats, errors };
}

// ─── L5–L7 Intelligence Pipeline ─────────────────────────────────────────────

const CANONICAL_DEEPSEEK_MODELS = new Set(['deepseek-v4-pro', 'deepseek-v4-flash']);

function resolveDeepSeekModelName(model) {
  const raw = String(model || '').trim();
  const normalized = raw.toLowerCase();
  if (!normalized) return 'deepseek-v4-pro';
  if (CANONICAL_DEEPSEEK_MODELS.has(normalized)) return normalized;
  if (normalized === 'v4-pro' || normalized === 'v4-flash' || normalized.startsWith('deepseek-')) {
    throw new Error(
      `Unsupported DeepSeek model "${model}". Use "deepseek-v4-pro" or "deepseek-v4-flash".`
    );
  }
  return raw;
}

function inferProviderFromModel(model) {
  const normalized = resolveDeepSeekModelName(model).toLowerCase();
  return normalized.startsWith('deepseek-') ? 'deepseek' : 'anthropic';
}

function computeEffectiveConcurrency(requested, model, totalFiles, bulkFast) {
  void model;
  void bulkFast;
  const requestedNum = Number.isFinite(Number(requested)) ? Number(requested) : 3;
  const safeRequested = Math.max(1, Math.min(8, Math.trunc(requestedNum)));
  return Math.min(safeRequested, Math.max(1, totalFiles));
}

function buildExtractionCacheByHash(existingExtraction = {}) {
  const byHash = {};
  for (const item of Object.values(existingExtraction || {})) {
    const hash = item?._sha256;
    if (!hash) continue;
    if (item?.error) continue;
    if (Array.isArray(item?.errors) && item.errors.length > 0) continue;
    if (!item?.nodes) continue;
    byHash[hash] = item;
  }
  return byHash;
}

function cloneCachedExtraction(item, fileRef, hash) {
  const cloned = JSON.parse(JSON.stringify(item));
  cloned.file_ref = fileRef;
  cloned._sha256 = hash || cloned._sha256 || null;
  cloned._cached = true;
  return cloned;
}

function buildExtractionStats(results) {
  const stats = {
    total: Object.keys(results || {}).length,
    extracted: 0,
    skipped: 0,
    errors: 0,
    files_with_errors: 0,
    auth_errors: 0,
    total_actions: 0,
    total_violations: 0,
    total_runs: 0,
    cached_reused: 0
  };

  const isAuthFailure = (msg) => {
    const text = String(msg || '').toLowerCase();
    return text.includes('401') ||
      text.includes('authentication') ||
      text.includes('invalid api key') ||
      text.includes('api key required') ||
      text.includes('invalid x-api-key') ||
      text.includes('unauthorized');
  };

  for (const r of Object.values(results || {})) {
    if (r?.skipped) stats.skipped += 1;
    if (r?._cached) stats.cached_reused += 1;

    const topLevelErrors = r?.error ? 1 : 0;
    const chunkErrors = Array.isArray(r?.errors) ? r.errors.length : 0;
    const totalErrorsForFile = topLevelErrors + chunkErrors;

    if (totalErrorsForFile > 0) {
      stats.files_with_errors += 1;
      stats.errors += totalErrorsForFile;
    }

    if (r?.error && isAuthFailure(r.error)) {
      stats.auth_errors += 1;
    }
    if (Array.isArray(r?.errors)) {
      for (const err of r.errors) {
        if (isAuthFailure(err?.error)) {
          stats.auth_errors += 1;
        }
      }
    }

    if (r?.nodes) {
      if ((r.nodes.actions?.length || 0) > 0 || (r.nodes.violations?.length || 0) > 0) {
        stats.extracted += 1;
      }
      stats.total_actions += r.nodes.actions?.length || 0;
      stats.total_violations += r.nodes.violations?.length || 0;
      stats.total_runs += r.run_ids?.length || 0;
    }
  }

  return stats;
}

/**
 * Run the full intelligence pipeline (L5–L7) on already-ingested data.
 * Requires an API key for L5b and L7 LLM calls.
 * 
 * @param {Object} store      - Pipeline store (from runPipeline)
 * @param {string} rootDir    - Source folder path
 * @param {Object} options    - { apiKey, model, outputDir, onProgress, skipDedup }
 * @returns {Promise<Object>} Intelligence results + output file paths
 */
async function runIntelligencePipeline(store, rootDir, options = {}) {
  const {
    apiKey,
    model        = 'deepseek-v4-pro',
    outputDir    = path.join(rootDir, '_intelligence'),
    onProgress   = null,
    skipDedup    = false,
    bulkFast     = false,
    useCache     = true,
    concurrency  = 3,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT,
    // KB options
    kbConfig     = null,
    augmentExtraction,
    persistToGraph,
    skipVerification  = false
  } = options;

  const profile = normalizeAnalysisProfile(analysisProfile);
  const profileMeta = getAnalysisProfileMeta(profile);
  const resolvedModel = resolveDeepSeekModelName(model);
  const findingsLabel = isLegalProfile(profile)
    ? 'violations'
    : profileMeta.finding_plural;

  // Merge KB config from profile defaults + explicit overrides
  const effectiveKbConfig = {
    ...getKbConfig(profile),
    ...(kbConfig || {}),
    enabled: kbConfig?.enabled !== undefined ? kbConfig.enabled : getKbConfig(profile).enabled,
    persist_graph: persistToGraph !== undefined ? persistToGraph : getKbConfig(profile).persist_graph,
    augment_extraction: augmentExtraction !== undefined ? augmentExtraction : getKbConfig(profile).augment_extraction
  };

  const allFiles    = Object.values(store.getAllFiles());
  const effectiveBulkFast = Boolean(bulkFast) || allFiles.length >= 100;
  const resultPaths = {};
  const log         = [];

  function progress(stage, detail) {
    const msg = `[${new Date().toISOString()}] ${stage}: ${detail}`;
    log.push(msg);
    if (onProgress) onProgress(stage, detail);
  }

  // ── KB Health Check ──────────────────────────────────────────────────────────
  let kbHealth = { qdrant: false, neo4j: false, enabled: false };
  if (effectiveKbConfig.enabled) {
    kbHealth = await kbIsAvailable(effectiveKbConfig);
    progress('KB', `Health check: Qdrant=${kbHealth.qdrant}, Neo4j=${kbHealth.neo4j}`);
    if (!kbHealth.qdrant && !kbHealth.neo4j) {
      progress('KB', 'WARNING: KB enabled but neither Qdrant nor Neo4j are reachable. Falling back to regex-only law resolution.');
    }
  }

  // Ensure output directory
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  progress('L5', `Starting deduplication on ${allFiles.length} files`);

  // ── L5: Deduplication ────────────────────────────────────────────────────────
  let dedupResults = {};
  let dedupStats   = {};

  if (!skipDedup) {
    const dedup = runDedup(allFiles, { skipNearDuplicates: effectiveBulkFast });
    dedupResults = dedup.results;
    dedupStats   = dedup.stats;
    store.setDedupResults(dedupResults);
    store.save();

    progress('L5', `Dedup complete: ${dedupStats.canonical_files} canonical, ` +
      `${dedupStats.exact_duplicates} exact dups, ` +
      `${dedupStats.near_duplicates} near dups`);

    // Write dedup report
    const dedupPath = path.join(outputDir, 'dedup_report.json');
    fs.writeFileSync(dedupPath, JSON.stringify({ stats: dedupStats, results: dedupResults }, null, 2));
    resultPaths.dedup_report = dedupPath;
  }

  // ── L5b: LLM Extraction ───────────────────────────────────────────────────────
  if (!apiKey) {
    progress('L5b', 'SKIPPED — no API key provided. Set apiKey in options.');
    return {
      ok:           false,
      skipped_llm:  true,
      message:      'L5b–L7 require an API key. L0–L5 complete.',
      result_paths: resultPaths,
      dedup_stats:  dedupStats,
      log
    };
  }

  // Only extract canonical files (skip duplicates)
  const canonicalFiles = skipDedup
    ? allFiles
    : allFiles.filter(f => dedupResults[f.file_ref]?.canonical !== false);

  const previousExtraction = store.getExtractionResults ? store.getExtractionResults() : {};
  const cachedByHash = useCache ? buildExtractionCacheByHash(previousExtraction) : {};
  const cachedResults = {};
  const filesToExtract = [];

  for (const file of canonicalFiles) {
    const hash = file.layers?.L0?.sha256 || null;
    if (hash && cachedByHash[hash]) {
      cachedResults[file.file_ref] = cloneCachedExtraction(cachedByHash[hash], file.file_ref, hash);
    } else {
      filesToExtract.push(file);
    }
  }

  const effectiveConcurrency = computeEffectiveConcurrency(concurrency, resolvedModel, filesToExtract.length, effectiveBulkFast);

  progress(
    'L5b',
    `Extracting ${filesToExtract.length}/${canonicalFiles.length} canonical files ` +
    `(cached: ${Object.keys(cachedResults).length}, concurrency: ${effectiveConcurrency})`
  );

  let freshResults = {};
  if (filesToExtract.length > 0) {
    const extraction = await extractBatch(filesToExtract, {
      apiKey,
      model: resolvedModel,
      analysisProfile: profile,
      concurrency: effectiveConcurrency,
      maxRetries: 2,
      retryBaseMs: effectiveBulkFast ? 450 : 700,
      onProgress: (done, total, ref) => {
        progress('L5b', `${done}/${total} — ${ref}`);
      }
    });
    freshResults = extraction.results;
  }

  const extractionResults = { ...cachedResults, ...freshResults };
  const extractionStats = buildExtractionStats(extractionResults);

  // Persist extraction results
  store.setExtractionResults(extractionResults);
  store.save();

  const extractPath = path.join(outputDir, 'extraction_results.json');
  fs.writeFileSync(extractPath, JSON.stringify({ stats: extractionStats, results: extractionResults }, null, 2));
  resultPaths.extraction_results = extractPath;

  progress('L5b', `Extraction complete: ${extractionStats.total_actions} actions, ` +
    `${extractionStats.total_violations} ${findingsLabel}, ` +
    `${extractionStats.errors} errors`);

  const firstExtractionError = Object.values(extractionResults)
    .flatMap((item) => {
      const errors = [];
      if (item?.error) errors.push(item.error);
      if (Array.isArray(item?.errors)) {
        for (const err of item.errors) {
          if (err?.error) errors.push(err.error);
        }
      }
      return errors;
    })
    .find(Boolean);

  if (extractionStats.auth_errors > 0) {
    throw new Error(
      `LLM extraction failed due to authentication errors (${extractionStats.auth_errors}). ` +
      `Check provider/model/api_key and rerun. ` +
      `${firstExtractionError ? `First error: ${firstExtractionError}` : ''}`
    );
  }

  if (extractionStats.extracted === 0 && extractionStats.errors > 0) {
    throw new Error(
      `LLM extraction produced no usable output (${extractionStats.errors} error(s)). ` +
      `${firstExtractionError ? `First error: ${firstExtractionError}` : 'Review extraction_results.json for details.'}`
    );
  }

  // ── L6: Normalization ─────────────────────────────────────────────────────────
  progress('L6', 'Building ontology v2.4 case graph');

  const { case_graph, violations, law_registry, stats: normStats, neo4j: neo4jResult } =
    await normalizeExtractionResults(extractionResults, allFiles, rootDir, {
      analysisProfile: profile,
      kbConfig: effectiveKbConfig
    });

  const graphPath      = path.join(outputDir, 'case_graph.json');
  const violsPath      = path.join(outputDir, 'violations.json');
  const lawRegPath     = path.join(outputDir, 'law_registry.json');

  fs.writeFileSync(graphPath,   JSON.stringify(case_graph,   null, 2));
  fs.writeFileSync(violsPath,   JSON.stringify(violations,   null, 2));
  fs.writeFileSync(lawRegPath,  JSON.stringify(law_registry, null, 2));

  resultPaths.case_graph    = graphPath;
  resultPaths.violations    = violsPath;
  resultPaths.law_registry  = lawRegPath;

  progress('L6', `Graph assembled: ${normStats.total_violations} ${findingsLabel}, ` +
    `${normStats.resolved_law_refs} resolved law refs, ` +
    `${normStats.unresolved_law_refs} unresolved` +
    (normStats.kb_enabled ? `, KB enriched: ${normStats.kb_enriched_refs || 0} refs, ${normStats.kb_articles_with_text || 0} articles with text` : '') +
    (neo4jResult?.ok ? `, Neo4j: ${neo4jResult.persisted_violations || 0} violations persisted` : ''));

  // ── L7: Narrative ─────────────────────────────────────────────────────────────
  progress('L7', 'Synthesizing case narrative');

  const { narrative_md, timeline, gap_report, llm_used } =
    await runNarrative(case_graph, violations, law_registry, {
      apiKey,
      model: resolvedModel,
      analysisProfile: profile,
      kbConfig: effectiveKbConfig
    });

  const narrativePath  = path.join(outputDir, 'narrative.md');
  const timelinePath   = path.join(outputDir, 'timeline.json');
  const gapReportPath  = path.join(outputDir, 'gap_report.json');

  fs.writeFileSync(narrativePath, narrative_md);
  fs.writeFileSync(timelinePath,  JSON.stringify(timeline,   null, 2));
  fs.writeFileSync(gapReportPath, JSON.stringify(gap_report, null, 2));

  resultPaths.narrative  = narrativePath;
  resultPaths.timeline   = timelinePath;
  resultPaths.gap_report = gapReportPath;

  progress('L7', `Narrative complete (${llm_used ? 'LLM-synthesized' : 'static template'}), ` +
    `${gap_report.total_gaps} gaps identified`);

  // ── L8: Legal Verification ────────────────────────────────────────────────────
  let verificationReport = null;
  let verificationStats  = { total: 0, verified: 0, high_confidence: 0, medium_confidence: 0, low_confidence: 0 };

  if (!skipVerification && effectiveKbConfig.enabled && violations.length > 0) {
    progress('L8', `Verifying ${violations.length} ${findingsLabel} against legal knowledge base`);

    try {
      const { results: verResults, stats: verStats } = await verifyAllViolations(
        case_graph.nodes.violations || [],
        case_graph,
        { analysisProfile: profile, kbConfig: effectiveKbConfig }
      );

      verificationStats = verStats;

      const report = generateVerificationReport(verResults, verStats, case_graph);
      const reportPath = path.join(outputDir, 'verification_report.json');
      const reportMdPath = path.join(outputDir, 'verification_report.md');

      fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
      fs.writeFileSync(reportMdPath, renderVerificationMarkdown(report));

      resultPaths.verification_report = reportPath;
      resultPaths.verification_report_md = reportMdPath;

      progress('L8', `Verification complete: ${verStats.high_confidence} HIGH, ` +
        `${verStats.medium_confidence} MEDIUM, ${verStats.low_confidence} LOW, ` +
        `${verStats.unverifiable} unverifiable`);
    } catch (err) {
      progress('L8', `Verification error: ${err.message}`);
    }
  } else if (!effectiveKbConfig.enabled) {
    progress('L8', 'Skipped — KB not enabled');
  }

  // ── Layer E: Event Formalization ────────────────────────────────────────────
  progress('E', 'Formalizing events from extraction results');

  const { events: formalEvents, event_graph, stats: eventStats } =
    formalizeEvents(extractionResults, {
      outputDir,
      onProgress,
      analysisProfile: profile
    });

  resultPaths.events      = path.join(outputDir, 'events.json');
  resultPaths.event_graph = path.join(outputDir, 'event_graph.json');

  progress('E', `${eventStats.merged_events} events (${eventStats.corroborated} corroborated), ` +
    `${eventStats.graph_edges} graph edges`);

  // ── Layer S: Case State Engine ──────────────────────────────────────────────
  progress('S', 'Evaluating case state');

  const caseState = evaluateCaseState(formalEvents, {
    outputDir,
    onProgress,
    analysisProfile: profile
  });

  resultPaths.case_state = path.join(outputDir, 'case_state.json');

  progress('S', `Phase: ${caseState.phase.current_phase}, ` +
    `${caseState.findings.length} findings, ${caseState.next_steps.length} recommendations`);

  // ── Summary ───────────────────────────────────────────────────────────────────
  const summaryPath = path.join(outputDir, 'pipeline_summary.json');
  resultPaths.summary = summaryPath;

  const summary = {
    ok:              true,
    generated_at:    new Date().toISOString(),
    folder:          rootDir,
    ontology:        'v2.4',
    analysis_profile: profile,
    analysis_profile_label: profileMeta.label,
    llm_model:       resolvedModel,
    llm_used_for_narrative: llm_used,
    stats: {
      total_files:          allFiles.length,
      canonical_files:      dedupStats.canonical_files || allFiles.length,
      exact_duplicates:     dedupStats.exact_duplicates || 0,
      near_duplicates:      dedupStats.near_duplicates || 0,
      files_extracted:      extractionStats.extracted,
      extraction_cached:    extractionStats.cached_reused,
      total_actions:        extractionStats.total_actions,
      total_violations:     extractionStats.total_violations,
      total_findings:       extractionStats.total_violations,
      resolved_law_refs:    normStats.resolved_law_refs,
      unresolved_law_refs:  normStats.unresolved_law_refs,
      gap_count:            gap_report.total_gaps,
      high_priority_gaps:   gap_report.high_priority_gaps,
      // Event layer
      total_events:        eventStats.merged_events,
      corroborated_events: eventStats.corroborated,
      event_graph_edges:   eventStats.graph_edges,
      // Case state
      case_phase:          caseState.phase.current_phase,
      state_findings:      caseState.findings.length,
      state_next_steps:    caseState.next_steps.length,
      // KB integration
      kb_enabled:           effectiveKbConfig.enabled,
      kb_qdrant_available:  kbHealth.qdrant,
      kb_neo4j_available:   kbHealth.neo4j,
      kb_enriched_refs:     normStats.kb_enriched_refs || 0,
      kb_articles_with_text: normStats.kb_articles_with_text || 0,
      neo4j_persisted_violations: neo4jResult?.persisted_violations || 0,
      // Verification (L8)
      verification_high:    verificationStats.high_confidence || 0,
      verification_medium:  verificationStats.medium_confidence || 0,
      verification_low:     verificationStats.low_confidence || 0
    },
    output_files: resultPaths,
    log
  };

  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));

  return summary;
}

// ─── Store Extensions (add new methods) ──────────────────────────────────────
// These need to be added to store.js if not present

function extendStore(store) {
  const rawData = typeof store.getRawData === 'function' ? store.getRawData() : null;

  if (!store.setDedupResults) {
    store.setDedupResults = function(results) {
      if (rawData) rawData.dedup = results || {};
    };
  }
  if (!store.setExtractionResults) {
    store.setExtractionResults = function(results) {
      if (rawData) rawData.extraction = results || {};
    };
  }
  if (!store.getDedupResults) {
    store.getDedupResults = function() {
      return rawData?.dedup || {};
    };
  }
  if (!store.getExtractionResults) {
    store.getExtractionResults = function() {
      return rawData?.extraction || {};
    };
  }
  return store;
}

function enrichEndpoint(endpoint, store) {
  if (!store) return endpoint;

  const entry = Object.entries(store.getAllFiles()).find(([, record]) => record.file_ref === endpoint.file);
  if (!entry) return endpoint;

  const [hash, record] = entry;

  return {
    ...endpoint,
    pipeline: {
      hash,
      layers: record.layers || {},
      dedup: store.getDedupResults ? store.getDedupResults()[endpoint.file] || null : null,
      extraction: store.getExtractionResults ? store.getExtractionResults()[endpoint.file] || null : null
    }
  };
}

module.exports = {
  runPipeline,
  runIntelligencePipeline,
  runComprehension,
  formalizeEvents,
  evaluateCaseState,
  extendStore,
  enrichEndpoint,
  // KB integration helpers
  getKbConfig,
  getAllKbFunctions: () => ({
    isAvailable: kbIsAvailable,
    verifyAllViolations,
    generateVerificationReport,
    renderVerificationMarkdown
  })
};
