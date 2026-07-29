/**
 * Pipeline Layer 6 — Normalization
 * 
 * Takes raw extraction results from L5b and produces a fully
 * ontology v2.4 compliant case graph:
 * 
 *   1. ELI Resolution   — map raw law references to canonical ELI IDs
 *                         by querying Argus /api/law/articles or matching
 *                         against the local known-frameworks registry.
 *   2. Actor Dedup      — merge ActorRole nodes with same function across files
 *   3. Entity Dedup     — consolidate identical Actions/Violations across chunks
 *   4. Case Assembly    — build Case, SourcePack, SourceFile, ApplicabilityBasis
 *   5. Graph Export     — emit case_graph.json  (full v2.4 compliant graph)
 *                         violations.json       (article-mapped violation list)
 * 
 * Single Responsibility: structure and validate the graph.
 * Narrative synthesis is Layer 7's job.
 */

'use strict';

const crypto = require('crypto');
const path   = require('path');
const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  getKbConfig
} = require('./analysis_profile');
const {
  lookupArticleByELI,
  searchLawArticles,
  persistCaseGraph,
  isAvailable: kbIsAvailable
} = require('./legal_kb');

// ─── ELI Resolution ───────────────────────────────────────────────────────────

/**
 * Known framework patterns for fast local resolution.
 * Maps text patterns → { framework_code, jurisdiction, eli_prefix }
 * 
 * Extend this as new frameworks are added to Argus.
 */
const FRAMEWORK_PATTERNS = [
  // Brazil
  { pattern: /\bCDC\b|C[oó]digo de Defesa do Consumidor/i,       code: 'CDC',   jur: 'BR', name: 'Código de Defesa do Consumidor' },
  { pattern: /\bCBA\b|C[oó]digo Brasileiro de Aeron[aá]utica/i,  code: 'CBA',   jur: 'BR', name: 'Código Brasileiro de Aeronáutica' },
  { pattern: /Resolu[çc][aã]o[^0-9]*400|Res\.?\s*400\b/i,        code: 'ANAC400', jur: 'BR', name: 'Resolução ANAC nº 400' },
  { pattern: /Resolu[çc][aã]o[^0-9]*280|Res\.?\s*280\b/i,        code: 'ANAC280', jur: 'BR', name: 'Resolução ANAC nº 280' },
  { pattern: /Lei[^0-9]*7\.?565|7\.?565\/1986/i,                  code: 'LEI7565', jur: 'BR', name: 'Lei nº 7.565/1986' },
  { pattern: /Lei[^0-9]*8\.?078|8\.?078\/1990/i,                  code: 'LEI8078', jur: 'BR', name: 'Lei nº 8.078/1990 (CDC)' },
  { pattern: /\bANAC\b.*resolu/i,                                 code: 'ANAC',  jur: 'BR', name: 'Regulamentação ANAC' },
  // Chile
  { pattern: /\bDGAC\b|Direcci[oó]n General de Aeron[aá]utica/i, code: 'DGAC',  jur: 'CL', name: 'Regulamentação DGAC Chile' },
  { pattern: /D\.?F\.?L\.?\s*[Nn]o?\.?\s*221/i,                  code: 'DFL221', jur: 'CL', name: 'DFL Nº 221 Ley de Navegación Aérea' },
  // International
  { pattern: /Conven[çc][aã]o de Montreal|Montreal Convention/i,  code: 'MC99',  jur: 'INT', name: 'Montreal Convention 1999' },
  { pattern: /Conven[çc][aã]o de Varsóvia|Warsaw Convention/i,    code: 'WC29',  jur: 'INT', name: 'Warsaw Convention 1929' },
  { pattern: /\bICAO\b|OACI/i,                                    code: 'ICAO',  jur: 'INT', name: 'ICAO Standards' },
  { pattern: /Regulamento[^0-9]*261|EC\s*261|EU\s*261/i,          code: 'EC261', jur: 'EU',  name: 'EC Regulation 261/2004' },
];

/**
 * Attempt to extract article number from raw law reference text.
 */
function extractArticleHint(rawText) {
  const m = rawText.match(/Art\.?\s*(\d+[\w°]*)|§\s*(\d+)|artigo\s+(\d+)/i);
  if (m) return normalizeArticleHint(m[1] || m[2] || m[3]);
  return null;
}

function normalizeArticleHint(value) {
  if (value === undefined || value === null) return null;

  const raw = String(value).trim();
  if (!raw) return null;

  const compact = raw
    .replace(/^art(?:\.|igo)?\s*/i, '')
    .replace(/^§\s*/i, '')
    .replace(/[°º]/g, '')
    .replace(/\.$/, '')
    .trim();

  const token = compact.match(/(\d+[A-Za-z-]*)/);
  if (token && token[1]) return token[1];

  return compact || null;
}

/**
 * Resolve a raw law reference to a structured law ref object.
 * Tries local pattern matching first; marks unresolved ones for Argus lookup.
 */
function resolveLocalLawRef(rawRef) {
  const text = rawRef.raw_text || rawRef.framework_hint || '';

  for (const pat of FRAMEWORK_PATTERNS) {
    if (pat.pattern.test(text)) {
      const articleHint = normalizeArticleHint(rawRef.article_hint || extractArticleHint(text));
      const eliBase     = `${pat.jur}.${pat.code}`;
      const eli         = articleHint
        ? `${eliBase}.Art.${articleHint}`
        : eliBase;

      return {
        raw_text:       text,
        framework_code: pat.code,
        framework_name: pat.name,
        jurisdiction:   pat.jur,
        article_hint:   articleHint,
        eli_id:         eli,
        resolved:       true,
        needs_argus:    !!articleHint // detailed article lookup via Argus
      };
    }
  }

  // Unresolved — flag for manual review or Argus lookup
  return {
    raw_text:       text,
    framework_code: rawRef.framework_hint || 'UNKNOWN',
    jurisdiction:   rawRef.jurisdiction || 'other',
    article_hint:   rawRef.article_hint || null,
    eli_id:         null,
    resolved:       false,
    needs_argus:    true
  };
}

/**
 * Deduplicate resolved law refs by ELI ID (or raw text if unresolved).
 */
function deduplicateLawRefs(refs) {
  const seen = new Map();
  for (const ref of refs) {
    const key = ref.eli_id || `RAW_${ref.raw_text.slice(0, 50)}`;
    if (!seen.has(key)) {
      seen.set(key, { ...ref, file_count: 1 });
    } else {
      seen.get(key).file_count++;
    }
  }
  return Array.from(seen.values()).sort((a, b) => b.file_count - a.file_count);
}

// ─── KB Enrichment ──────────────────────────────────────────────────────────

/**
 * Enrich resolved law refs with article text from the knowledge base.
 * Attempts ELI lookup first, then falls back to semantic search for unresolved refs.
 *
 * @param {Array} resolvedRefs - From deduplicateLawRefs
 * @param {Object} kbConfig
 * @returns {Promise<Array>} Enriched refs with article_text populated where possible
 */
async function enrichLawRefsWithKB(resolvedRefs, kbConfig = {}) {
  if (!kbConfig.enabled) return resolvedRefs;

  const enriched = [];
  for (const ref of resolvedRefs) {
    let articleText = null;
    let enrichedFrom = null;

    // Try exact ELI lookup for resolved refs
    if (ref.resolved && ref.eli_id) {
      const article = await lookupArticleByELI(ref.eli_id, kbConfig);
      if (article?.article_text) {
        articleText = article.article_text;
        enrichedFrom = 'kb_eli_lookup';
      }
    }

    // For unresolved refs, try semantic search
    if (!articleText && !ref.resolved) {
      const searchResults = await searchLawArticles(
        ref.raw_text,
        ref.jurisdiction || null,
        3,
        kbConfig
      );
      if (searchResults.length > 0 && searchResults[0].score > 0.7) {
        const top = searchResults[0];
        articleText = top.article_text || null;
        enrichedFrom = 'kb_semantic_search';
        // Update resolution based on semantic match
        if (!ref.resolved && top.eli_id) {
          ref.resolved = true;
          ref.eli_id = top.eli_id;
          ref.framework_code = top.framework_code || ref.framework_code;
          ref.framework_name = top.framework_name || ref.framework_name;
          ref.jurisdiction = top.jurisdiction || ref.jurisdiction;
          ref.needs_argus = false;
        }
      }
    }

    // Some refs are marked resolved from regex but still have no text.
    // Retry semantic search and prefer same-framework same-article candidates.
    if (!articleText && ref.resolved) {
      const articleHint = normalizeArticleHint(ref.article_hint);
      const searchQuery = [
        ref.raw_text,
        ref.framework_name,
        articleHint ? `Art. ${articleHint}` : null
      ].filter(Boolean).join(' ');

      const searchResults = await searchLawArticles(
        searchQuery,
        ref.jurisdiction || null,
        5,
        kbConfig
      );

      if (searchResults.length > 0) {
        const preferred = searchResults.find((item) => {
          const sameFramework = !ref.framework_code || item.framework_code === ref.framework_code;
          const sameArticle = !articleHint || normalizeArticleHint(item.article_number) === articleHint;
          return sameFramework && sameArticle;
        }) || searchResults[0];

        if (preferred && preferred.score >= 0.45) {
          articleText = preferred.article_text || null;
          enrichedFrom = 'kb_semantic_search';

          if (preferred.eli_id) {
            ref.eli_id = preferred.eli_id;
            ref.framework_code = preferred.framework_code || ref.framework_code;
            ref.framework_name = preferred.framework_name || ref.framework_name;
            ref.jurisdiction = preferred.jurisdiction || ref.jurisdiction;
            ref.needs_argus = false;
          }
        }
      }
    }

    enriched.push({
      ...ref,
      article_text: articleText || ref.article_text || null,
      enriched_from: enrichedFrom || ref.enriched_from || 'regex_only'
    });
  }

  return enriched;
}

/**
 * Enrich LegalArticle nodes with full text from the knowledge base.
 *
 * @param {Array} legalArticleNodes - From build step
 * @param {Object} kbConfig
 * @returns {Promise<Array>} Enriched nodes
 */
async function enrichLegalArticleNodes(legalArticleNodes, kbConfig = {}) {
  if (!kbConfig.enabled) return legalArticleNodes;

  const enriched = [];
  for (const node of legalArticleNodes) {
    if (node.article_text && !node._needs_argus_enrichment) {
      enriched.push(node);
      continue;
    }

    const article = await lookupArticleByELI(node.node_id, kbConfig);
    if (article?.article_text) {
      enriched.push({
        ...node,
        article_text: article.article_text,
        _needs_argus_enrichment: false,
        _enriched_from_kb: true
      });
    } else {
      enriched.push(node);
    }
  }

  return enriched;
}

// ─── Actor Role Deduplication ─────────────────────────────────────────────────

/**
 * Merge ActorRole nodes across all files by function.
 * One canonical ActorRole node per function in the case graph.
 */
function mergeActorRoles(allActors) {
  const byFunction = {};
  for (const actor of allActors) {
    if (!byFunction[actor.function]) {
      byFunction[actor.function] = {
        ...actor,
        _source_node_ids: [actor.node_id]
      };
    } else {
      byFunction[actor.function]._source_node_ids.push(actor.node_id);
    }
  }
  return Object.values(byFunction);
}

// ─── Case Graph Assembly ──────────────────────────────────────────────────────

/**
 * Build a SourcePack node from folder metadata.
 */
function buildSourcePackNode(folderPath, files) {
  // Integrity hash = SHA-256 of all file SHA-256 hashes concatenated (sorted)
  const fileHashes = files
    .map(f => f.layers?.L0?.sha256 || '')
    .filter(Boolean)
    .sort()
    .join('');

  const packHash = crypto
    .createHash('sha256')
    .update(fileHashes)
    .digest('hex');

  return {
    node_id:        `PACK_${packHash.slice(0, 8)}`,
    type:           'SourcePack',
    created_at:     new Date().toISOString(),
    integrity_hash: packHash,
    _folder_path:   folderPath,
    _file_count:    files.length
  };
}

/**
 * Build SourceFile nodes from L0 pipeline data.
 */
function buildSourceFileNodes(files) {
  return files.map(f => ({
    node_id:  f.layers?.L0?.file_node_id || `FILE_${crypto.createHash('md5').update(f.file_ref).digest('hex').slice(0, 8)}`,
    type:     'SourceFile',
    path:     f.file_ref,
    sha256:   f.layers?.L0?.sha256 || '',
    file_type: f.layers?.L0?.mime_type || 'application/octet-stream'
  }));
}

/**
 * Infer jurisdiction from extracted entities and law references.
 */
function inferJurisdiction(allLawRefs, allContexts) {
  const jurCount = {};
  for (const ref of allLawRefs) {
    const j = ref.jurisdiction || 'other';
    jurCount[j] = (jurCount[j] || 0) + 1;
  }
  for (const ctx of allContexts) {
    const j = ctx.jurisdiction_hint;
    if (j) jurCount[j] = (jurCount[j] || 0) + 1;
  }
  // Return the most frequent jurisdiction
  const sorted = Object.entries(jurCount).sort((a, b) => b[1] - a[1]);
  return sorted[0]?.[0] || 'BR'; // default to BR
}

/**
 * Build ApplicabilityBasis nodes for cross-jurisdictional cases.
 */
function buildApplicabilityBasisNodes(jurisdictions) {
  const basisTypeMap = {
    BR:  'brazilian_operator',
    CL:  'registration_jurisdiction',
    INT: 'treaty_obligation',
    EU:  'treaty_obligation'
  };

  return jurisdictions
    .filter(j => j !== 'other')
    .map(j => ({
      node_id:    `APPL_${crypto.randomBytes(4).toString('hex')}`,
      type:       'ApplicabilityBasis',
      basis_type: basisTypeMap[j] || 'treaty_obligation'
    }));
}

/**
 * Build a Case node title from folder name and detected context.
 */
function buildCaseTitle(folderPath, allContexts) {
  const folderName = path.basename(folderPath);
  // Look for a subject matter in contexts
  const subject = allContexts
    .map(c => c.subject_matter)
    .filter(Boolean)[0];

  if (subject) return `${subject.slice(0, 80)} [${folderName}]`;
  return `Case Analysis — ${folderName}`;
}

// ─── Main Normalization Function ──────────────────────────────────────────────

/**
 * Normalize all extraction results into an ontology v2.4 compliant case graph.
 * 
 * @param {Object} extractionResults - Map of file_ref → L5b extraction result
 * @param {Array}  allFiles          - All pipeline store file objects
 * @param {string} folderPath        - Root folder path
 * @returns {Object} {
 *   case_graph: { ... },      // Full v2.4 graph
 *   violations: [ ... ],      // Article-mapped violations
 *   law_registry: [ ... ],    // All resolved law refs
 *   stats: { ... }
 * }
 */
async function normalizeExtractionResults(extractionResults, allFiles, folderPath, options = {}) {
  const profile = normalizeAnalysisProfile(options.analysisProfile || ANALYSIS_PROFILE_DEFAULT);
  const profileMeta = getAnalysisProfileMeta(profile);
  const kbConfig = options.kbConfig || getKbConfig(profile);

  // Collect all nodes across files
  const allActions    = [];
  const allViolations = [];
  const allActors     = [];
  const allSegments   = [];
  const allEvidences  = [];
  const allLLMRuns    = [];
  const allLawRefs    = [];
  const allContexts   = [];

  for (const [fileRef, result] of Object.entries(extractionResults)) {
    if (!result.nodes || result.skipped) continue;
    const n = result.nodes;

    if (n.evidence)   allEvidences.push(n.evidence);
    if (n.actions)    allActions.push(...n.actions);
    if (n.actors)     allActors.push(...n.actors);
    if (n.segments)   allSegments.push(...n.segments);
    if (n.violations) allViolations.push(...n.violations);
    if (n.llm_runs)   allLLMRuns.push(...n.llm_runs);
    if (n.contexts)   allContexts.push(...n.contexts);

    // Collect raw law refs from violations
    for (const viol of (n.violations || [])) {
      for (const lawRef of (viol._law_references || [])) {
        allLawRefs.push(resolveLocalLawRef(lawRef));
      }
    }
  }

  // ── ELI Resolution ──────────────────────────────────────────────────────────
  const rawLawRefs = deduplicateLawRefs(allLawRefs);

  // Enrich with knowledge base (populates article_text, resolves some unresolved refs)
  const resolvedLawRefs = await enrichLawRefsWithKB(rawLawRefs, kbConfig);

  const lawRefByEli     = {};
  for (const ref of resolvedLawRefs) {
    if (ref.eli_id) lawRefByEli[ref.eli_id] = ref;
  }

  // Build LegalArticle stub nodes for resolved refs
  let legalArticleNodes = resolvedLawRefs
    .filter(r => r.resolved && r.article_hint)
    .map(r => ({
      node_id:           r.eli_id,
      type:              'LegalArticle',
      article_number:    r.article_hint,
      article_reference: `${r.framework_name}, Art. ${r.article_hint}`,
      article_text:      r.article_text || null,
      framework_code:    r.framework_code,
      jurisdiction:      r.jurisdiction,
      _needs_argus_enrichment: !r.article_text,
      _enriched_from:    r.enriched_from || 'regex'
    }));

  // Enrich article nodes with full text from KB
  legalArticleNodes = await enrichLegalArticleNodes(legalArticleNodes, kbConfig);

  // Build LegalFramework stub nodes
  const frameworkNodeMap = {};
  for (const ref of resolvedLawRefs.filter(r => r.resolved)) {
    if (!frameworkNodeMap[ref.framework_code]) {
      frameworkNodeMap[ref.framework_code] = {
        node_id:      `${ref.jurisdiction}.${ref.framework_code}`,
        type:         'LegalFramework',
        name:         ref.framework_name,
        jurisdiction: ref.jurisdiction
      };
    }
  }
  const legalFrameworkNodes = Object.values(frameworkNodeMap);

  // ── Actor Deduplication ─────────────────────────────────────────────────────
  const canonicalActors = mergeActorRoles(allActors);
  // Build mapping old_node_id → canonical_node_id
  const actorIdMap = {};
  for (const actor of canonicalActors) {
    for (const srcId of (actor._source_node_ids || [])) {
      actorIdMap[srcId] = actor.node_id;
    }
  }

  // Update action _performed_by_role_id references
  for (const action of allActions) {
    if (action._performed_by_role_id && actorIdMap[action._performed_by_role_id]) {
      action._performed_by_role_id = actorIdMap[action._performed_by_role_id];
    }
  }

  // ── Violation → Article Linking ─────────────────────────────────────────────
  const violationNodes = allViolations.map(viol => {
    const articleIds = (viol._law_references || [])
      .map(r => resolveLocalLawRef(r))
      .filter(r => r.eli_id)
      .map(r => r.eli_id);

    return {
      ...viol,
      _violates_article_ids: articleIds,
      _law_references:       undefined  // clean internal field
    };
  });

  // ── Source Provenance ──────────────────────────────────────────────────────
  const sourcePack       = buildSourcePackNode(folderPath, allFiles);
  const sourceFileNodes  = buildSourceFileNodes(allFiles);
  const jurisdiction     = inferJurisdiction(resolvedLawRefs, allContexts);
  const applicabilityBases = buildApplicabilityBasisNodes(
    [...new Set(resolvedLawRefs.map(r => r.jurisdiction).filter(Boolean))]
  );

  // ── Case Node ──────────────────────────────────────────────────────────────
  // One LLMRun node represents the extraction pipeline as a whole
  const primaryRunId = allLLMRuns[0]?.node_id || `RUN_${crypto.randomBytes(4).toString('hex')}`;

  const caseNode = {
    node_id:      `CASE_${crypto.randomBytes(4).toString('hex')}`,
    type:         'Case',
    title:        buildCaseTitle(folderPath, allContexts),
    created_date: new Date().toISOString(),
    jurisdiction,
    description:  `Auto-generated case from ${allFiles.length} files via Discovery pipeline v1.0`,
    // Relationships
    _has_provenance_id:          sourcePack.node_id,
    _scopes_violation_ids:       violationNodes.map(v => v.node_id),
    _has_applicability_basis_ids: applicabilityBases.map(b => b.node_id),
    _generated_by_run_id:        primaryRunId
  };

  // ── Violations Summary (for violations.json) ───────────────────────────────
  const violationsSummary = violationNodes.map(v => {
    const groundingActions = (v._grounded_in_action_ids || [])
      .map(id => allActions.find(a => a.node_id === id))
      .filter(Boolean);

    const articles = (v._violates_article_ids || []).map(eli => ({
      eli_id:         eli,
      ...lawRefByEli[eli]
    }));

    return {
      violation_id:  v.node_id,
      category:      v.category,
      description:   v.description,
      severity:      v.severity,
      confidence:    v.confidence,
      articles,
      grounding_actions: groundingActions.map(a => ({
        action_id:   a.node_id,
        description: a.description,
        timestamp:   a.timestamp,
        location:    a.location
      }))
    };
  });

  // ── Full Case Graph ────────────────────────────────────────────────────────
  const caseGraph = {
    _meta: {
      ontology_version: '2.4',
      generated_at:     new Date().toISOString(),
      pipeline_version: 'discovery-pipeline-v1.0',
      analysis_profile: profile,
      analysis_profile_label: profileMeta.label,
      folder:           folderPath
    },
    nodes: {
      case:               [caseNode],
      source_pack:        [sourcePack],
      source_files:       sourceFileNodes,
      legal_frameworks:   legalFrameworkNodes,
      legal_articles:     legalArticleNodes,
      applicability_bases: applicabilityBases,
      violations:         violationNodes,
      actions:            allActions,
      actor_roles:        canonicalActors,
      evidence:           allEvidences,
      segments:           allSegments,
      llm_runs:           allLLMRuns
    },
    // Summary stats
    stats: {
      files_processed:     Object.keys(extractionResults).length,
      files_with_nodes:    allEvidences.length,
      total_actions:       allActions.length,
      total_violations:    violationNodes.length,
      total_actors:        canonicalActors.length,
      total_law_refs:      resolvedLawRefs.length,
      resolved_law_refs:   resolvedLawRefs.filter(r => r.resolved).length,
      unresolved_law_refs: resolvedLawRefs.filter(r => !r.resolved).length,
      needs_argus_lookup:  resolvedLawRefs.filter(r => r.needs_argus).length,
      frameworks_detected: legalFrameworkNodes.length,
      // KB enrichment stats
      kb_enriched_refs:    resolvedLawRefs.filter(r => r.enriched_from === 'kb_eli_lookup' || r.enriched_from === 'kb_semantic_search').length,
      kb_articles_with_text: legalArticleNodes.filter(a => a.article_text).length,
      kb_articles_missing_text: legalArticleNodes.filter(a => !a.article_text).length,
      kb_enabled:          kbConfig.enabled,
      jurisdiction
    }
  };

  // ── Optional Neo4j persistence ───────────────────────────────────────────
  let neo4jResult = { ok: false, reason: 'not_attempted' };
  if (kbConfig.enabled && kbConfig.persist_graph) {
    neo4jResult = await persistCaseGraph(caseGraph, kbConfig);
    caseGraph._meta.neo4j_persisted = neo4jResult.ok;
    caseGraph._meta.neo4j_summary = neo4jResult;
  }

  return {
    case_graph:    caseGraph,
    violations:    violationsSummary,
    law_registry:  resolvedLawRefs,
    stats:         caseGraph.stats,
    neo4j:         neo4jResult
  };
}

module.exports = {
  normalizeExtractionResults,
  resolveLocalLawRef,
  deduplicateLawRefs,
  enrichLawRefsWithKB,
  enrichLegalArticleNodes,
  buildSourcePackNode,
  buildSourceFileNodes,
  FRAMEWORK_PATTERNS
};
