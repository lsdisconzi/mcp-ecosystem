/**
 * Pipeline Layer L8 — Legal Verification
 *
 * Runs after L6 normalization. Takes each violation and verifies it
 * against actual law articles in the knowledge base (Qdrant + Neo4j).
 *
 * Verification scoring:
 *   HIGH   — violation's claimed articles match top semantic search results
 *   MEDIUM — partial overlap between claimed and semantic matches
 *   LOW    — no overlap; violation may be misclassified or needs manual review
 *
 * Outputs:
 *   verification_report.json — per-violation scores, matched articles, flags
 *   Augments violation nodes with _verification_score and _verified_articles
 */

'use strict';

const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  getKbConfig,
  isLegalProfile
} = require('./analysis_profile');

const {
  searchLawArticles,
  lookupArticleByELI,
  getRelatedArticles,
  isAvailable
} = require('./legal_kb');

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

  const match = compact.match(/(\d+[A-Za-z-]*)/);
  return match && match[1] ? match[1] : (compact || null);
}

function normalizeClaimedArticleId(value) {
  if (value === undefined || value === null) return null;
  const raw = String(value).trim();
  if (!raw) return null;

  const compact = raw.replace(/\s+/g, '').replace(/\.Art\.Art\./i, '.Art.').replace(/\.$/, '');
  const full = compact.match(/^([A-Za-z]{2})\.([A-Za-z0-9]+)\.Art\.([A-Za-z0-9.-]+)$/i);

  if (full) {
    const jur = full[1].toUpperCase();
    const framework = full[2].toUpperCase();
    const hint = normalizeArticleHint(full[3]);
    if (hint) return `${jur}.${framework}.Art.${hint}`;
  }

  return compact;
}

function parseClaimedArticleId(value) {
  const normalized = normalizeClaimedArticleId(value);
  if (!normalized) return null;

  const full = normalized.match(/^([A-Za-z]{2})\.([A-Za-z0-9]+)\.Art\.([A-Za-z0-9-]+)$/i);
  if (!full) return null;

  return {
    normalized,
    jurisdiction: full[1].toUpperCase(),
    framework_code: full[2].toUpperCase(),
    article_hint: normalizeArticleHint(full[3])
  };
}

function buildCaseGraphArticleIndex(caseGraph) {
  const byId = {};
  const byFrameworkArticle = {};

  function assignPreferred(target, key, candidate) {
    if (!key || !candidate) return;
    const current = target[key];
    if (!current) {
      target[key] = candidate;
      return;
    }

    const currentHasText = !!current.article_text;
    const candidateHasText = !!candidate.article_text;
    if (!currentHasText && candidateHasText) {
      target[key] = candidate;
    }
  }

  for (const article of (caseGraph?.nodes?.legal_articles || [])) {
    const articleId = normalizeClaimedArticleId(article?.node_id || article?.eli_id || null);
    if (articleId) {
      assignPreferred(byId, articleId.toLowerCase(), article);
    }

    const framework = String(article?.framework_code || '').toUpperCase();
    const articleHint = normalizeArticleHint(article?.article_number || article?.article_reference || articleId);
    if (framework && articleHint) {
      assignPreferred(byFrameworkArticle, `${framework}:${articleHint}`.toLowerCase(), article);
    }
  }

  return { byId, byFrameworkArticle };
}

function findCaseGraphArticle(claimedId, articleIndex) {
  if (!articleIndex) return null;

  const parsed = parseClaimedArticleId(claimedId);
  if (!parsed) return null;

  const byId = articleIndex.byId[parsed.normalized.toLowerCase()] || null;
  const byFramework = articleIndex.byFrameworkArticle[`${parsed.framework_code}:${parsed.article_hint}`.toLowerCase()] || null;

  if (byId && byId.article_text) return byId;
  if (byFramework && byFramework.article_text) return byFramework;

  return byId || byFramework || null;
}

// ─── Verification logic ────────────────────────────────────────────────────

/**
 * Verify a single violation against the knowledge base.
 *
 * @param {Object} violation   - Violation node from case graph
 * @param {Object} options     - { kbConfig }
 * @returns {Promise<Object>}  Verification result
 */
async function verifyViolation(violation, options = {}) {
  const kbConfig = options.kbConfig || getKbConfig(ANALYSIS_PROFILE_DEFAULT);
  const jurisdiction = options.jurisdiction || null;

  const result = {
    violation_id:    violation.node_id,
    category:        violation.category,
    description:     violation.description,
    severity:        violation.severity,
    claimed_articles: violation._violates_article_ids || [],
    verification_score: null,
    matched_articles: [],
    semantic_matches: [],
    flags: []
  };

  // Build search query: category + description for better semantic matching
  const searchQuery = `${violation.category || ''} ${violation.description || ''}`.trim();
  if (!searchQuery || searchQuery.length < 10) {
    result.verification_score = 'INSUFFICIENT_TEXT';
    result.flags.push('description_too_short_for_verification');
    return result;
  }

  // Search Qdrant for top semantically similar law articles
  const topK = kbConfig.top_k_articles_search || 5;
  const semanticMatches = await searchLawArticles(searchQuery, jurisdiction, topK, kbConfig);

  result.semantic_matches = semanticMatches.map(m => ({
    eli_id:         m.eli_id,
    article_reference: m.article_reference,
    score:          m.score,
    framework_code: m.framework_code
  }));

  // Match claimed articles against semantic results
  const claimedSet = new Set(
    result.claimed_articles
      .map(id => normalizeClaimedArticleId(id))
      .filter(Boolean)
      .map(id => id.toLowerCase())
  );
  const semanticSet = new Set(
    semanticMatches
      .map(m => normalizeClaimedArticleId(m.eli_id))
      .filter(Boolean)
      .map(id => id.toLowerCase())
  );

  if (claimedSet.size === 0 && semanticMatches.length === 0) {
    result.verification_score = 'NO_MATCH';
    result.flags.push('no_articles_claimed_or_found');
    return result;
  }

  if (claimedSet.size === 0) {
    // No articles claimed, but semantic matches found — suggest articles
    result.verification_score = 'SUGGESTED';
    result.matched_articles = semanticMatches.slice(0, 3).map(m => ({
      eli_id:            m.eli_id,
      article_reference: m.article_reference,
      article_text:      m.article_text,
      match_type:        'semantic_only',
      score:             m.score
    }));
    result.flags.push('no_articles_claimed_by_violation');
    return result;
  }

  // Check overlap between claimed and semantic matches
  let overlapCount = 0;
  const matchedArticles = [];

  for (const claimedId of result.claimed_articles) {
    const normalizedClaimId = normalizeClaimedArticleId(claimedId);
    const normalized = normalizedClaimId?.toLowerCase();
    const semanticMatch = semanticMatches.find((m) => {
      const normalizedSemantic = normalizeClaimedArticleId(m.eli_id);
      return normalizedSemantic && normalizedSemantic.toLowerCase() === normalized;
    });
    const isOverlap = normalized ? semanticSet.has(normalized) : false;

    if (isOverlap) overlapCount++;

    // Look up full article text
    let article = null;
    if (normalizedClaimId) article = await lookupArticleByELI(normalizedClaimId, kbConfig);
    if (!article) article = await lookupArticleByELI(claimedId, kbConfig);
    if (!article) article = findCaseGraphArticle(claimedId, options.articleIndex);

    matchedArticles.push({
      eli_id:            normalizedClaimId || claimedId,
      article_reference: article?.article_reference || normalizedClaimId || claimedId,
      article_text:      article?.article_text || semanticMatch?.article_text || null,
      match_type:        isOverlap ? 'verified' : 'claimed_only',
      semantic_score:    semanticMatch?.score || null
    });
  }

  result.matched_articles = matchedArticles;

  // Determine verification score
  if (overlapCount === result.claimed_articles.length && overlapCount > 0) {
    result.verification_score = 'HIGH';
  } else if (overlapCount > 0) {
    result.verification_score = 'MEDIUM';
    result.flags.push('partial_article_match');
  } else if (matchedArticles.some(a => !!a.article_text)) {
    result.verification_score = 'LOW';
    result.flags.push('claimed_articles_found_without_semantic_match');
  } else if (semanticMatches.length > 0) {
    result.verification_score = 'LOW';
    result.flags.push('claimed_articles_not_semantically_matched');
    // Add top semantic suggestions as alternatives
    result.suggested_articles = semanticMatches.slice(0, 3).map(m => ({
      eli_id:            m.eli_id,
      article_reference: m.article_reference,
      score:             m.score
    }));
  } else {
    result.verification_score = 'UNVERIFIABLE';
    result.flags.push('no_articles_in_knowledge_base');
  }

  // Additional flags
  if (violation.confidence !== undefined && violation.confidence < 0.5) {
    result.flags.push('low_extraction_confidence');
  }
  if (result.matched_articles.some(a => !a.article_text)) {
    result.flags.push('missing_article_text_in_kb');
  }

  return result;
}

/**
 * Verify all violations from a case graph.
 *
 * @param {Array}  violations   - Array of violation nodes
 * @param {Object} caseGraph    - Full case graph (for jurisdiction context)
 * @param {Object} options      - { kbConfig, analysisProfile }
 * @returns {Promise<Object>}   { results, stats }
 */
async function verifyAllViolations(violations, caseGraph, options = {}) {
  const profile = normalizeAnalysisProfile(options.analysisProfile || ANALYSIS_PROFILE_DEFAULT);
  const kbConfig = options.kbConfig || getKbConfig(profile);
  const jurisdiction = caseGraph?.nodes?.case?.[0]?.jurisdiction || null;
  const articleIndex = buildCaseGraphArticleIndex(caseGraph);

  if (!kbConfig.enabled) {
    return {
      results: [],
      stats: {
        total:              violations.length,
        high_confidence:    0,
        medium_confidence:  0,
        low_confidence:     0,
        suggested:          0,
        unverifiable:       0,
        total_flags:        0,
        articles_verified:  0,
        articles_claimed_only: 0,
        kb_disabled:        true
      }
    };
  }

  const results = [];
  for (const violation of violations) {
    const result = await verifyViolation(violation, { kbConfig, jurisdiction, articleIndex });
    results.push(result);
  }

  const stats = {
    total:              results.length,
    high_confidence:    results.filter(r => r.verification_score === 'HIGH').length,
    medium_confidence:  results.filter(r => r.verification_score === 'MEDIUM').length,
    low_confidence:     results.filter(r => r.verification_score === 'LOW').length,
    suggested:          results.filter(r => r.verification_score === 'SUGGESTED').length,
    unverifiable:       results.filter(r => ['UNVERIFIABLE', 'NO_MATCH', 'INSUFFICIENT_TEXT'].includes(r.verification_score)).length,
    total_flags:        results.reduce((sum, r) => sum + r.flags.length, 0),
    articles_verified:  results.reduce((sum, r) => sum + r.matched_articles.filter(a => a.match_type === 'verified').length, 0),
    articles_claimed_only: results.reduce((sum, r) => sum + r.matched_articles.filter(a => a.match_type === 'claimed_only').length, 0)
  };

  // Augment violation nodes with verification info
  for (const result of results) {
    const viol = violations.find(v => v.node_id === result.violation_id);
    if (viol) {
      viol._verification_score = result.verification_score;
      viol._verified_articles = result.matched_articles.filter(a => a.match_type === 'verified').map(a => a.eli_id);
      viol._verification_flags = result.flags;
    }
  }

  return { results, stats };
}

/**
 * Generate a human-readable verification report.
 *
 * @param {Array}  verificationResults - From verifyAllViolations
 * @param {Object} stats
 * @param {Object} caseGraph
 * @returns {Object} Report object (also serializable to JSON/MD)
 */
function generateVerificationReport(verificationResults, stats, caseGraph) {
  const caseNode = caseGraph?.nodes?.case?.[0] || {};

  const report = {
    _meta: {
      generated_at: new Date().toISOString(),
      pipeline_stage: 'L8-verification',
      case_id: caseNode.node_id || 'unknown',
      case_title: caseNode.title || 'Unknown Case'
    },
    summary: stats,
    violations_by_confidence: {
      HIGH:   verificationResults.filter(r => r.verification_score === 'HIGH'),
      MEDIUM: verificationResults.filter(r => r.verification_score === 'MEDIUM'),
      LOW:    verificationResults.filter(r => r.verification_score === 'LOW'),
      SUGGESTED: verificationResults.filter(r => r.verification_score === 'SUGGESTED'),
      UNVERIFIABLE: verificationResults.filter(r =>
        ['UNVERIFIABLE', 'NO_MATCH', 'INSUFFICIENT_TEXT'].includes(r.verification_score)
      )
    },
    flags_summary: summarizeFlags(verificationResults),
    recommendations: generateRecommendations(verificationResults, stats)
  };

  return report;
}

/**
 * Generate markdown text from the verification report.
 */
function renderVerificationMarkdown(report) {
  const { summary, violations_by_confidence: vbc, flags_summary, recommendations } = report;

  let md = '';
  md += `# Legal Verification Report\n\n`;
  md += `**Generated:** ${report._meta.generated_at}\n`;
  md += `**Case:** ${report._meta.case_title}\n\n`;

  md += `## Summary\n\n`;
  md += `| Metric | Count |\n`;
  md += `|---|---|\n`;
  md += `| Total violations | ${summary.total} |\n`;
  md += `| HIGH confidence | ${summary.high_confidence} |\n`;
  md += `| MEDIUM confidence | ${summary.medium_confidence} |\n`;
  md += `| LOW confidence | ${summary.low_confidence} |\n`;
  md += `| Suggested (no articles claimed) | ${summary.suggested} |\n`;
  md += `| Unverifiable | ${summary.unverifiable} |\n`;
  md += `| Articles verified | ${summary.articles_verified} |\n`;
  md += `| Articles claimed but unverified | ${summary.articles_claimed_only} |\n\n`;

  if (vbc.HIGH.length > 0) {
    md += `## HIGH Confidence (${vbc.HIGH.length})\n\n`;
    md += `These violations have strong semantic matches with their claimed law articles.\n\n`;
    for (const r of vbc.HIGH) {
      md += `- **${r.violation_id}** — ${r.category}: ${r.description.slice(0, 120)}\n`;
      for (const a of r.matched_articles.filter(a => a.match_type === 'verified')) {
        md += `  - ${a.article_reference} (score: ${a.semantic_score?.toFixed(3) || 'N/A'})\n`;
      }
    }
    md += '\n';
  }

  if (vbc.LOW.length > 0) {
    md += `## LOW Confidence (${vbc.LOW.length}) — Needs Review\n\n`;
    md += `These violations claim articles that don't match semantic search. Possible misclassification.\n\n`;
    for (const r of vbc.LOW) {
      md += `- **${r.violation_id}** — ${r.category}: ${r.description.slice(0, 120)}\n`;
      md += `  - Claimed: ${r.claimed_articles.join(', ') || 'none'}\n`;
      if (r.suggested_articles?.length) {
        md += `  - Suggested: ${r.suggested_articles.map(a => a.article_reference).join(', ')}\n`;
      }
    }
    md += '\n';
  }

  if (vbc.SUGGESTED.length > 0) {
    md += `## Suggested Articles (${vbc.SUGGESTED.length})\n\n`;
    md += `Violations that didn't claim any articles but have strong semantic matches.\n\n`;
    for (const r of vbc.SUGGESTED) {
      md += `- **${r.violation_id}** — ${r.category}: ${r.description.slice(0, 120)}\n`;
      for (const m of r.matched_articles) {
        md += `  - ${m.article_reference} (semantic score: ${m.score?.toFixed(3) || 'N/A'})\n`;
      }
    }
    md += '\n';
  }

  if (flags_summary.length > 0) {
    md += `## Flags Summary\n\n`;
    for (const flag of flags_summary) {
      md += `- **${flag.flag}**: ${flag.count} violation(s)\n`;
    }
    md += '\n';
  }

  if (recommendations.length > 0) {
    md += `## Recommendations\n\n`;
    for (const rec of recommendations) {
      md += `- ${rec}\n`;
    }
    md += '\n';
  }

  return md;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function summarizeFlags(results) {
  const flagCounts = {};
  for (const r of results) {
    for (const flag of r.flags) {
      flagCounts[flag] = (flagCounts[flag] || 0) + 1;
    }
  }
  return Object.entries(flagCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([flag, count]) => ({ flag, count }));
}

function generateRecommendations(results, stats) {
  const recs = [];

  if (stats.low_confidence > 0) {
    recs.push(`Review ${stats.low_confidence} LOW-confidence violations — claimed articles don't match the violation description semantically. Consider reclassifying or updating law references.`);
  }

  if (stats.suggested > 0) {
    recs.push(`${stats.suggested} violations have no claimed articles but strong semantic matches exist in the knowledge base. Run auto-suggestion to populate article links.`);
  }

  if (stats.articles_claimed_only > 0) {
    recs.push(`${stats.articles_claimed_only} claimed articles could not be semantically verified; this may indicate malformed article IDs, weak extraction text, or missing KB links.`);
  }

  if (stats.unverifiable > 0) {
    recs.push(`${stats.unverifiable} violations could not be verified. Possible reasons: insufficient text, no matching articles in KB, or KB unavailable.`);
  }

  const missingTextCount = results.filter(r => r.flags.includes('missing_article_text_in_kb')).length;
  if (missingTextCount > 0) {
    recs.push(`${missingTextCount} violations reference articles whose full text is unavailable in the current lookup path. Check article ID normalization before re-running ingestion.`);
  }

  const lowConfCount = results.filter(r => r.flags.includes('low_extraction_confidence')).length;
  if (lowConfCount > 0) {
    recs.push(`${lowConfCount} violations have low extraction confidence (< 0.5). These may represent borderline or speculative findings.`);
  }

  return recs;
}

// ─── Exports ────────────────────────────────────────────────────────────────

module.exports = {
  verifyViolation,
  verifyAllViolations,
  generateVerificationReport,
  renderVerificationMarkdown
};
