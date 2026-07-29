/**
 * Pipeline Layer 7 — Narrative Synthesis
 * 
 * Takes the normalized case graph (L6 output) and produces:
 * 
 *   narrative.md      — Human-readable chronological story
 *   timeline.json     — Machine-readable ordered event sequence
 *   gap_report.json   — What's missing, unresolved refs, weak evidence
 * 
 * Two modes:
 *   - LLM mode:   sends structured graph to LLM for synthesis (rich narrative)
 *   - Static mode: template-based narrative without LLM (fast, offline)
 * 
 * Single Responsibility: synthesize meaning. Does not modify the graph.
 */

'use strict';

const crypto            = require('crypto');
const { callLLM }       = require('./llm_client');
const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile,
  getKbConfig
} = require('./analysis_profile');
const {
  lookupArticleByELI,
  searchLawArticles,
  getRelatedArticles
} = require('./legal_kb');

const NARRATE_PROMPT_VERSION = 'narrative-v2.0-profile-aware';

// ─── Narrative LLM Prompt ────────────────────────────────────────────────────

function buildNarrativeSystemPrompt(profile = ANALYSIS_PROFILE_DEFAULT) {
  const normalized = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalized);
  const legalMode = isLegalProfile(normalized);

  const title = legalMode ? 'Case Narrative' : meta.narrative_title;
  const summaryTitle = legalMode ? 'Case Summary' : meta.summary_title;
  const findingsTitle = legalMode ? 'Violations Analysis' : meta.findings_title;

  return `You are an intelligence synthesis engine.
Produce a clear, evidence-grounded, chronological narrative from structured data.

Active profile: ${meta.label}
Profile scope: ${meta.scope}

RULES:
1. Base every statement on the provided actions and findings - no invention
2. Reference evidence sources (file paths) where relevant
3. Use functional roles only - ZERO personal names
4. Do not conclude guilt, liability, or legal outcome
5. Flag gaps: missing evidence, unresolved references, contradictions
6. Write in a neutral, professional tone
7. Structure: ${summaryTitle} -> Chronological Timeline -> ${findingsTitle} -> Gaps
8. If a complete source file list is provided, do not claim files are missing or unavailable

Return a single markdown document with these exact sections:
# ${title}
## ${summaryTitle}
## Chronological Timeline
## ${findingsTitle}
## Evidence Assessment
## Gaps and Recommendations`;
}

/**
 * Build a "Legal Basis" section by retrieving full article texts
 * for all unique articles cited across violations.
 */
async function buildLegalBasisSection(violationsSummary, kbConfig) {
  if (!kbConfig || !kbConfig.enabled) return 'No knowledge base configured. Legal basis text is unavailable.';

  // Collect unique article IDs
  const articleIds = new Set();
  for (const v of violationsSummary) {
    for (const a of (v.articles || [])) {
      if (a.eli_id) articleIds.add(a.eli_id);
    }
  }

  if (articleIds.size === 0) return 'No articles cited by violations.';

  var lines = [];
  for (const eliId of articleIds) {
    const article = await lookupArticleByELI(eliId, kbConfig);
    if (article && article.article_text) {
      lines.push('- **' + (article.article_reference || eliId) + '** [' + (article.jurisdiction || '?') + ']: ' + article.article_text.slice(0, 500));
    } else {
      lines.push('- **' + eliId + '**: Text not available in knowledge base.');
    }
  }

  return lines.length > 0 ? lines.join('\n') : 'No article texts available.';
}

async function buildNarrativeUserMessage(caseGraph, violationsSummary, profile = ANALYSIS_PROFILE_DEFAULT, kbConfig = null) {
  const normalized = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalized);
  const { nodes, stats, _meta } = caseGraph;
  const caseNode = nodes.case?.[0];

  // Build a compact representation for the LLM — no need to send all raw segments
  const actionsForPrompt = (nodes.actions || [])
    .sort((a, b) => {
      const ta = a.timestamp || '';
      const tb = b.timestamp || '';
      if (ta && tb) return ta.localeCompare(tb);
      return (a.sequence_index || 0) - (b.sequence_index || 0);
    })
    .map(a => ({
      seq:         a.sequence_index,
      type:        a.action_type,
      description: a.description,
      timestamp:   a.timestamp,
      location:    a.location,
      actor:       a._performed_by_role_id
    }));

  const violsForPrompt = violationsSummary.map(v => ({
    id:          v.violation_id,
    category:    v.category,
    description: v.description,
    severity:    v.severity,
    confidence:  v.confidence,
    articles:    v.articles.map(a => `${a.eli_id || a.raw_text} (${a.framework_name || ''})`).join('; '),
    grounded_in: v.grounding_actions.map(a => a.description).join(' | ')
  }));

  const lawRegistry = (nodes.legal_frameworks || []).map(f => f.name).join(', ');
  const sourceFiles = (nodes.source_files || []).map(f => `- ${f.path} [${f.file_type}]`);

  return `CASE: ${caseNode?.title || 'Unknown'}
JURISDICTION: ${caseNode?.jurisdiction || 'Unknown'}
FOLDER: ${_meta?.folder || 'Unknown'}
GENERATED: ${_meta?.generated_at}
PROFILE: ${meta.label}

STATISTICS:
- Files processed: ${stats.files_processed}
- Actions extracted: ${stats.total_actions}
- Findings identified: ${stats.total_violations}
- Legal frameworks: ${lawRegistry || 'None resolved'}
- Unresolved law references: ${stats.unresolved_law_refs}

CHRONOLOGICAL ACTIONS (${actionsForPrompt.length}):
${JSON.stringify(actionsForPrompt, null, 2)}

FINDINGS (${violsForPrompt.length}):
${JSON.stringify(violsForPrompt, null, 2)}

EVIDENCE SOURCES (${sourceFiles.length} files with extracted content):
${sourceFiles.length ? sourceFiles.join('\n') : '- none'}

LEGAL BASIS (retrieved from knowledge base):
${await buildLegalBasisSection(violationsSummary, kbConfig)}

Generate the full profile-aware narrative following the required structure.`;
}

// ─── Static Narrative (no LLM) ───────────────────────────────────────────────

/**
 * Generate a structured narrative without LLM — template-based.
 * Used when no API key is available or for a quick first pass.
 */
function generateStaticNarrative(caseGraph, violationsSummary, lawRegistry, profile = ANALYSIS_PROFILE_DEFAULT) {
  const normalized = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalized);
  const legalMode = isLegalProfile(normalized);
  const findingsPlural = legalMode ? 'violations' : meta.finding_plural;
  const findingsTitle = legalMode ? 'Violations Analysis' : meta.findings_title;
  const { nodes, stats, _meta } = caseGraph;
  const caseNode = nodes.case?.[0];

  const date   = new Date(_meta?.generated_at || Date.now());
  const dateStr = date.toISOString().split('T')[0];

  // Sort actions chronologically
  const sortedActions = (nodes.actions || [])
    .slice()
    .sort((a, b) => {
      if (a.timestamp && b.timestamp) return a.timestamp.localeCompare(b.timestamp);
      return (a.sequence_index || 0) - (b.sequence_index || 0);
    });

  // Group violations by severity
  const highViolations   = violationsSummary.filter(v => v.severity === 'high');
  const medViolations    = violationsSummary.filter(v => v.severity === 'medium');
  const lowViolations    = violationsSummary.filter(v => v.severity === 'low');

  // Resolved vs unresolved law refs
  const resolvedRefs   = lawRegistry.filter(r => r.resolved);
  const unresolvedRefs = lawRegistry.filter(r => !r.resolved);

  const lines = [];

  // ── Header ──────────────────────────────────────────────────────────────────
  lines.push(`# ${legalMode ? 'Case Narrative' : meta.narrative_title}`);
  lines.push(`\n> Generated by Discovery Intelligence Pipeline v1.0`);
  lines.push(`> Ontology: v2.4 · Date: ${dateStr}`);
  lines.push(`> This document is an analytical extraction - not a legal conclusion.\n`);
  lines.push('---\n');

  // ── Case Summary ────────────────────────────────────────────────────────────
  lines.push(`## ${legalMode ? 'Case Summary' : meta.summary_title}\n`);
  lines.push(`**${legalMode ? 'Case' : 'Workspace'}:** ${caseNode?.title || 'Untitled Case'}`);
  lines.push(`**Jurisdiction:** ${caseNode?.jurisdiction || 'Undetermined'}`);
  lines.push(`**Source:** ${_meta?.folder || 'Unknown folder'}`);
  lines.push(`**Analysis Date:** ${dateStr}\n`);
  lines.push(`This case was assembled from **${stats.files_processed} source files**, ` +
    `of which **${stats.files_with_nodes}** contained extractable content. ` +
    `The pipeline identified **${stats.total_actions} discrete actions**, ` +
    `**${stats.total_violations} potential ${findingsPlural}**, and references to ` +
    `**${stats.resolved_law_refs} legal provisions** across ` +
    `**${stats.frameworks_detected} frameworks**.\n`);

  if (highViolations.length > 0) {
    lines.push(`⚠️  **${highViolations.length} high-severity ${legalMode ? 'violation' : 'finding'}${highViolations.length > 1 ? 's' : ''} detected** - review priority.\n`);
  }

  // ── Chronological Timeline ───────────────────────────────────────────────────
  lines.push('---\n');
  lines.push(`## Chronological Timeline\n`);

  if (sortedActions.length === 0) {
    lines.push('*No dated actions were extracted. Manual review required.*\n');
  } else {
    let currentDate = null;

    for (const action of sortedActions) {
      const ts       = action.timestamp || null;
      const dateOnly = ts ? ts.split('T')[0] : null;

      if (dateOnly && dateOnly !== currentDate) {
        currentDate = dateOnly;
        lines.push(`\n### ${dateOnly}\n`);
      } else if (!dateOnly && !currentDate) {
        currentDate = 'undated';
        lines.push(`\n### Undated Events\n`);
      }

      const actor    = action._performed_by_role_id
        ? `[${action._performed_by_role_id.replace(/ROLE_\w+/, action.actor_function || 'actor')}]`
        : '';
      const location = action.location ? ` at ${action.location}` : '';

      lines.push(`- **[${action.action_type.replace(/_/g, ' ')}]** ${action.description}${location}`);
    }
    lines.push('');
  }

  // ── Violations Analysis ──────────────────────────────────────────────────────
  lines.push('---\n');
  lines.push(`## ${findingsTitle}\n`);
  lines.push(`${stats.total_violations} potential ${findingsPlural} were identified across the extracted content.\n`);

  const violGroups = [
    { label: legalMode ? '🔴 High Severity Violations' : '🔴 High Priority Findings', items: highViolations },
    { label: legalMode ? '🟡 Medium Severity Violations' : '🟡 Medium Priority Findings', items: medViolations },
    { label: legalMode ? '🟢 Low Severity Violations' : '🟢 Low Priority Findings',  items: lowViolations }
  ];

  for (const group of violGroups) {
    if (group.items.length === 0) continue;
    lines.push(`### ${group.label}\n`);
    for (const v of group.items) {
      lines.push(`#### ${v.category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}`);
      lines.push(`> ${v.description}`);
      lines.push(`- **Confidence:** ${Math.round(v.confidence * 100)}%`);
      if (v.articles.length > 0) {
        lines.push('- **' + (legalMode ? 'Legal Basis' : 'Policy/Regulatory References') + ':**');
        for (const a of v.articles) {
          var textSnippet = a.article_text
            ? ' — "' + a.article_text.slice(0, 150) + (a.article_text.length > 150 ? '...' : '') + '"'
            : '';
          lines.push('  - ' + (a.eli_id || a.raw_text) + ' — ' + (a.framework_name || a.jurisdiction || '') + textSnippet);
        }
      } else {
        lines.push(`- **${legalMode ? 'Legal Basis' : 'Reference Basis'}:** *Unresolved - requires enrichment lookup*`);
      }
      if (v.grounding_actions.length > 0) {
        lines.push(`- **Grounded in:**`);
        for (const a of v.grounding_actions.slice(0, 3)) {
          lines.push(`  - ${a.description}${a.timestamp ? ` (${a.timestamp.split('T')[0]})` : ''}`);
        }
      }
      lines.push('');
    }
  }

  // ── Evidence Assessment ──────────────────────────────────────────────────────
  lines.push('---\n');
  lines.push(`## Evidence Assessment\n`);
  lines.push(`| File | Type | Extracted Actions | Status |`);
  lines.push(`|------|------|-------------------|--------|`);

  const sourceFiles = nodes.source_files || [];
  for (const sf of sourceFiles.slice(0, 30)) {
    const ext    = sf.path.split('.').pop() || '—';
    const status = sf.sha256 ? '✓ Hashed' : '⚠ No hash';
    lines.push(`| \`${sf.path}\` | ${ext} | — | ${status} |`);
  }
  if (sourceFiles.length > 30) {
    lines.push(`| *...and ${sourceFiles.length - 30} more files* | | | |`);
  }
  lines.push('');

  // ── Gaps and Recommendations ─────────────────────────────────────────────────
  lines.push('---\n');
  lines.push(`## Gaps and Recommendations\n`);

  const gaps = [];

  if (unresolvedRefs.length > 0) {
    gaps.push({
      type:        'unresolved_law_refs',
      severity:    'medium',
      description: `${unresolvedRefs.length} law reference(s) could not be resolved to ELI IDs.`,
      items:       unresolvedRefs.map(r => r.raw_text).slice(0, 5),
      action:      'Run Argus article matching to resolve these references.'
    });
  }

  const violsWithoutArticles = violationsSummary.filter(v => v.articles.length === 0);
  if (violsWithoutArticles.length > 0) {
    gaps.push({
      type:        'violations_without_articles',
      severity:    'high',
      description: `${violsWithoutArticles.length} violation(s) have no linked legal articles.`,
      items:       violsWithoutArticles.map(v => v.description).slice(0, 3),
      action:      legalMode
        ? 'These violations cannot be used as legal allegations without article links.'
        : 'These findings should be reviewed with supporting references before escalation.'
    });
  }

  const actionsWithoutEvidence = (nodes.actions || []).filter(a => !a._evidence_id);
  if (actionsWithoutEvidence.length > 0) {
    gaps.push({
      type:        'actions_without_evidence',
      severity:    'high',
      description: `${actionsWithoutEvidence.length} action(s) lack evidence links (violates Invariant IX-1).`,
      action:      'These actions fail the v2.4 Evidence Requirement invariant.'
    });
  }

  if (stats.files_processed - stats.files_with_nodes > 0) {
    const skipped = stats.files_processed - stats.files_with_nodes;
    gaps.push({
      type:        'unenriched_files',
      severity:    'low',
      description: `${skipped} file(s) were not enriched (binary, too short, or extraction failed).`,
      action:      'Check binary files for media content that may need transcription.'
    });
  }

  if (gaps.length === 0) {
    lines.push('No significant gaps detected. Proceed to legal review.\n');
  } else {
    for (const gap of gaps) {
      const icon = gap.severity === 'high' ? '🔴' : gap.severity === 'medium' ? '🟡' : '🟢';
      lines.push(`### ${icon} ${gap.type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}\n`);
      lines.push(`**Issue:** ${gap.description}`);
      if (gap.items?.length) {
        lines.push(`**Examples:** ${gap.items.map(i => `\`${i.slice(0, 60)}\``).join(', ')}`);
      }
      lines.push(`**Recommended Action:** ${gap.action}\n`);
    }
  }

  lines.push('---\n');
  lines.push(`*End of Case Narrative — Discovery Intelligence Pipeline*  `);
  lines.push(`*Ontology v2.4 · Awareness-AI*`);

  return lines.join('\n');
}

// ─── Timeline JSON ────────────────────────────────────────────────────────────

/**
 * Build machine-readable timeline.json from actions + violations.
 */
function buildTimeline(caseGraph, violationsSummary) {
  const actions = (caseGraph.nodes.actions || [])
    .slice()
    .sort((a, b) => {
      if (a.timestamp && b.timestamp) return a.timestamp.localeCompare(b.timestamp);
      return (a.sequence_index || 0) - (b.sequence_index || 0);
    });

  // Map violation by action id for fast lookup
  const violsByAction = {};
  for (const v of violationsSummary) {
    for (const a of v.grounding_actions) {
      if (!violsByAction[a.action_id]) violsByAction[a.action_id] = [];
      violsByAction[a.action_id].push({
        violation_id: v.violation_id,
        category:     v.category,
        severity:     v.severity,
        confidence:   v.confidence
      });
    }
  }

  const events = actions.map((action, idx) => ({
    index:          idx + 1,
    action_id:      action.node_id,
    action_type:    action.action_type,
    description:    action.description,
    timestamp:      action.timestamp || null,
    location:       action.location || null,
    actor_role:     action._performed_by_role_id,
    violations:     violsByAction[action.node_id] || [],
    findings:       violsByAction[action.node_id] || [],
    evidence_id:    action._evidence_id || null
  }));

  return {
    case_id:       caseGraph.nodes.case?.[0]?.node_id,
    generated_at:  new Date().toISOString(),
    event_count:   events.length,
    events
  };
}

// ─── Gap Report JSON ──────────────────────────────────────────────────────────

function buildGapReport(caseGraph, violationsSummary, lawRegistry, profile = ANALYSIS_PROFILE_DEFAULT) {
  const normalized = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalized);
  const legalMode = isLegalProfile(normalized);
  const gaps = [];

  // Invariant IX-1: every Action must have Evidence
  const actionsWithoutEvidence = (caseGraph.nodes.actions || []).filter(a => !a._evidence_id);
  if (actionsWithoutEvidence.length > 0) {
    gaps.push({
      invariant:   'IX-1',
      severity:    'high',
      description: 'Actions without Evidence links',
      count:       actionsWithoutEvidence.length,
      node_ids:    actionsWithoutEvidence.map(a => a.node_id)
    });
  }

  // Invariant IX-2: violations should have confidence scores
  const violsWithoutConf = violationsSummary.filter(v => !v.confidence);
  if (violsWithoutConf.length > 0) {
    gaps.push({
      invariant:   'IX-2',
      severity:    'medium',
      description: `${legalMode ? 'Violations' : meta.finding_plural} without confidence scores`,
      count:       violsWithoutConf.length,
      node_ids:    violsWithoutConf.map(v => v.violation_id)
    });
  }

  // Violations without article links
  const violsWithoutArticles = violationsSummary.filter(v => v.articles.length === 0);
  if (violsWithoutArticles.length > 0) {
    gaps.push({
      invariant:   'VIOL-NO-ARTICLE',
      severity:    'high',
      description: `${legalMode ? 'Violations' : meta.finding_plural} without linked reference nodes`,
      count:       violsWithoutArticles.length,
      resolution:  legalMode
        ? 'Run L6 Argus enrichment to resolve article ELI IDs'
        : 'Run enrichment to resolve policy/regulatory references'
    });
  }

  // Unresolved law refs
  const unresolvedRefs = lawRegistry.filter(r => !r.resolved);
  if (unresolvedRefs.length > 0) {
    gaps.push({
      invariant:   'LAW-UNRESOLVED',
      severity:    'medium',
      description: 'Law references that could not be matched to known frameworks',
      count:       unresolvedRefs.length,
      items:       unresolvedRefs.map(r => ({ raw: r.raw_text, hint: r.framework_code }))
    });
  }

  // Needs Argus enrichment
  const needsArgus = lawRegistry.filter(r => r.needs_argus);
  if (needsArgus.length > 0) {
    gaps.push({
      invariant:   'ARGUS-NEEDED',
      severity:    'low',
      description: 'Law references that need Argus article text enrichment',
      count:       needsArgus.length,
      resolution:  legalMode
        ? 'Call GET /api/law/articles/<eli_id> on Argus for each entry'
        : 'Run reference enrichment for unresolved controls and policies',
      items:       needsArgus.slice(0, 10).map(r => r.eli_id || r.raw_text)
    });
  }

  return {
    generated_at:        new Date().toISOString(),
    ontology_version:    '2.4',
    total_gaps:          gaps.length,
    high_priority_gaps:  gaps.filter(g => g.severity === 'high').length,
    gaps
  };
}

// ─── LLM Narrative Call ──────────────────────────────────────────────────────

async function generateLLMNarrative(caseGraph, violationsSummary, options = {}) {
  const {
    apiKey,
    model = 'deepseek-v4-pro',
    analysisProfile = ANALYSIS_PROFILE_DEFAULT,
    kbConfig = null
  } = options;

  if (!apiKey) {
    return {
      ok:        false,
      fallback:  true,
      message:   'No API key — using static narrative'
    };
  }

  const profile = normalizeAnalysisProfile(analysisProfile);
  const systemPrompt = buildNarrativeSystemPrompt(profile);
  const userMessage  = await buildNarrativeUserMessage(caseGraph, violationsSummary, profile, kbConfig);

  try {
    const text = await callLLM(systemPrompt, userMessage, { apiKey, model, maxTokens: 4096 });
    return { ok: true, fallback: false, narrative: text };
  } catch (err) {
    return {
      ok:       false,
      fallback: true,
      error:    err.message
    };
  }
}

// ─── Main Export ──────────────────────────────────────────────────────────────

/**
 * Run L7 narrative synthesis.
 * 
 * @param {Object} caseGraph         - L6 normalized graph
 * @param {Array}  violationsSummary - L6 violations array
 * @param {Array}  lawRegistry       - L6 law registry
 * @param {Object} options           - { apiKey, model, useLLM }
 * @returns {Promise<Object>} { narrative_md, timeline, gap_report, llm_used }
 */
async function runNarrative(caseGraph, violationsSummary, lawRegistry, options = {}) {
  const {
    apiKey,
    useLLM = true,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT,
    kbConfig = null
  } = options;

  const profile = normalizeAnalysisProfile(analysisProfile);

  // Always build static outputs
  const timeline   = buildTimeline(caseGraph, violationsSummary);
  const gap_report = buildGapReport(caseGraph, violationsSummary, lawRegistry, profile);

  let narrative_md;
  let llm_used = false;

  if (useLLM && apiKey) {
    const llmResult = await generateLLMNarrative(caseGraph, violationsSummary, {
      ...options,
      analysisProfile: profile,
      kbConfig: kbConfig
    });
    if (llmResult.ok) {
      narrative_md = llmResult.narrative;
      llm_used     = true;
    } else {
      // Fallback to static
      narrative_md = generateStaticNarrative(caseGraph, violationsSummary, lawRegistry, profile);
    }
  } else {
    narrative_md = generateStaticNarrative(caseGraph, violationsSummary, lawRegistry, profile);
  }

  return {
    narrative_md,
    timeline,
    gap_report,
    llm_used
  };
}

module.exports = {
  runNarrative,
  generateStaticNarrative,
  buildTimeline,
  buildGapReport,
  NARRATE_PROMPT_VERSION
};
