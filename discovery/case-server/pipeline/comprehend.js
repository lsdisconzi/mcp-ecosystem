/**
 * Pipeline Layer C — Corpus Comprehension
 *
 * Runs after L0–L4 offline enrichment. Uses an LLM to:
 *   1. Read representative samples from every file category
 *   2. Write a natural-language description of each category
 *   3. Synthesise a full corpus guide: what data exists, its quality,
 *      temporal narrative, and concrete organisation strategies
 *   4. Guide the user's next analysis step
 *
 * Outputs (all written to {rootDir}/_intelligence/):
 *   group_descriptions.json  — per-category LLM analysis
 *   corpus_overview.json     — synthesised understanding + stats
 *   corpus_guide.md          — human-readable guide with options
 *   restructure_options.json — concrete folder-structure strategies
 *
 * This layer is intentionally independent of L5–L7 (no ontology, no ELI
 * resolution). It answers a different question: "What have we got?"
 * rather than "What does the evidence say?"
 */

'use strict';

const fs   = require('fs');
const path = require('path');

// ─── Tuning constants ─────────────────────────────────────────────────────────

const MAX_SAMPLES_PER_GROUP     = 5;
const MAX_PREVIEW_CHARS         = 2000;
const MAX_GROUPS_IN_SYNTHESIS   = 20;  // cap to avoid oversized synthesis prompt
const MIN_WORDS_FOR_TEXT_SAMPLE = 10;
const ANALYSIS_PROFILE_DEFAULT  = 'general';

const ANALYSIS_PROFILE_META = {
  general: {
    label: 'General Workspace',
    scope: 'multi-domain operational documents',
    goal: 'extract practical understanding, risks, and organization opportunities'
  },
  office: {
    label: 'Office Operations',
    scope: 'administrative and procedural office records',
    goal: 'improve workflow structure, handoffs, and documentation quality'
  },
  'law-firm': {
    label: 'Law Firm Operations',
    scope: 'legal office material beyond strict violation analysis',
    goal: 'support triage, evidence organization, and legal review readiness'
  },
  business: {
    label: 'Business Operations',
    scope: 'corporate process, compliance, and reporting records',
    goal: 'surface operational risks and decision-support insights'
  },
  legal: {
    label: 'Legal / Violations',
    scope: 'legal and regulatory case material',
    goal: 'prepare a legal-oriented reading of events, violations, and evidence gaps'
  }
};

function normalizeAnalysisProfile(value) {
  const raw = String(value || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(ANALYSIS_PROFILE_META, raw)
    ? raw
    : ANALYSIS_PROFILE_DEFAULT;
}

function getAnalysisProfileMeta(profile) {
  return ANALYSIS_PROFILE_META[normalizeAnalysisProfile(profile)];
}

// ─── File grouping ────────────────────────────────────────────────────────────

/**
 * Group the pipeline store's files by their L2 primary domain.
 * Returns a map: domainKey → { domain, label, count, langs, exts, totalWords, files[] }
 */
function groupFiles(allFiles) {
  const groups = {};

  for (const record of allFiles) {
    const domain = record.layers?.L2?.primary_domain || 'general';
    const ext    = (record.layers?.L0?.extension || 'unknown').toLowerCase();
    const lang   = record.layers?.L2?.language || 'unknown';

    if (!groups[domain]) {
      groups[domain] = {
        domain,
        label:      formatLabel(domain),
        count:      0,
        langs:      {},
        exts:       {},
        totalWords: 0,
        files:      []
      };
    }

    const g = groups[domain];
    g.count++;
    g.langs[lang] = (g.langs[lang] || 0) + 1;
    g.exts[ext]   = (g.exts[ext]   || 0) + 1;
    g.totalWords += record.layers?.L1?.word_count || 0;
    g.files.push(record);
  }

  return groups;
}

function formatLabel(str) {
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ─── Smart sampling ───────────────────────────────────────────────────────────

/**
 * Pick up to maxSamples representative files from a group.
 * Prefers files with text content; spreads across extension types.
 */
function sampleGroup(files, maxSamples = MAX_SAMPLES_PER_GROUP) {
  // Prefer files that actually have text
  const textFiles = files.filter(f => (f.layers?.L1?.word_count || 0) >= MIN_WORDS_FOR_TEXT_SAMPLE);
  const pool      = textFiles.length > 0 ? textFiles : files;

  if (pool.length <= maxSamples) return pool;

  // Sort by word count descending — richest content first
  const sorted = [...pool].sort((a, b) =>
    (b.layers?.L1?.word_count || 0) - (a.layers?.L1?.word_count || 0)
  );

  // Ensure at least one example per unique extension
  const byExt  = {};
  for (const f of sorted) {
    const ext = f.layers?.L0?.extension || 'unknown';
    if (!byExt[ext]) byExt[ext] = f;
  }

  const chosen = new Set(Object.values(byExt).slice(0, maxSamples));

  // Fill remaining slots from the top of the word-count list
  for (const f of sorted) {
    if (chosen.size >= maxSamples) break;
    chosen.add(f);
  }

  return [...chosen];
}

/**
 * Flatten one store record into the compact shape the LLM will receive.
 */
function buildFileSummary(record) {
  const L0 = record.layers?.L0 || {};
  const L1 = record.layers?.L1 || {};
  const L2 = record.layers?.L2 || {};
  const L3 = record.layers?.L3 || {};

  return {
    path:       record.file_ref,
    extension:  L0.extension || 'unknown',
    size_bytes: L0.size_bytes || 0,
    word_count: L1.word_count || 0,
    language:   L2.language || 'unknown',
    tags:       (L2.tags || []).slice(0, 6),
    key_terms:  (L3.key_terms || []).slice(0, 8).map(t => t.term),
    preview:    (L1.preview || '').slice(0, MAX_PREVIEW_CHARS)
  };
}

// ─── LLM prompt builders ──────────────────────────────────────────────────────

function buildGroupSystemPrompt(profile = ANALYSIS_PROFILE_DEFAULT) {
  const meta = getAnalysisProfileMeta(profile);
  return `You are a corpus analyst for an operational intelligence platform.
You will be shown samples from one category of a ${meta.scope} dataset.
Analyse the samples and respond with ONLY a valid JSON object — no markdown fences, no explanation:

{
  "category_description": "What documents this category contains (2–3 sentences)",
  "content_type": "operations | legal_text | correspondence | analysis | transcript | regulation | financial | hr | it | commercial | other",
  "languages": ["list of detected languages"],
  "key_topics": ["5–8 key topics or recurring themes"],
  "temporal_range": "approximate date range visible in the content, or null",
  "quality_assessment": "1–2 sentences: is the content complete, fragmentary, well-structured?",
  "missing_patterns": ["what seems absent or incomplete — empty array if nothing obvious"],
  "case_relevance": "1 sentence: how this category supports the selected profile (${meta.label})"
}

RULES:
- Functional roles only when role references are needed — zero personal names
- Base everything strictly on the provided file content
- If content is insufficient to answer a field, use null
- Do not claim documents are missing from the corpus unless file metadata explicitly indicates absence
- If previews are abbreviated, treat that as sample limitation, not corpus absence`;
}

function buildGroupUserMessage(group, samples) {
  const extList  = Object.entries(group.exts).map(([e, n]) => `${e}×${n}`).join('  ');
  const langList = Object.entries(group.langs).map(([l, n]) => `${l}×${n}`).join('  ');

  const sampleBlock = samples.map((s, i) => {
    const termsLine = s.key_terms.length ? `Key terms: ${s.key_terms.join(', ')}` : '';
    const tagsLine  = s.tags.length      ? `Tags: ${s.tags.join(', ')}`            : '';
    return [
      `--- File ${i + 1}: ${s.path}  (${s.extension}, ${s.word_count} words) ---`,
      tagsLine,
      termsLine,
      s.preview || '(no text content)'
    ].filter(Boolean).join('\n');
  }).join('\n\n');

  return `GROUP: ${group.label}
TOTAL FILES: ${group.count}
EXTENSIONS: ${extList}
LANGUAGES: ${langList}
TOTAL WORDS: ${group.totalWords.toLocaleString()}

SAMPLES (${samples.length} of ${group.count}):
${sampleBlock}

Analyse this group and respond with the JSON format described.`;
}

function buildSynthesisSystemPrompt(profile = ANALYSIS_PROFILE_DEFAULT) {
  const meta = getAnalysisProfileMeta(profile);
  return `You are an intelligence analyst helping a user understand and organise a ${meta.scope} dataset.
You have received LLM descriptions of every file category in the corpus.

Respond with ONLY a valid JSON object — no markdown fences, no preamble:

{
  "corpus_summary": "3–4 sentence overview of what this dataset represents",
  "case_nature": "type of corpus/business context this appears to relate to (no personal names)",
  "data_strengths": ["what the dataset covers well"],
  "data_gaps": ["what appears missing, incomplete, or unreliable"],
  "key_themes": ["7–10 major themes across the corpus"],
  "temporal_narrative": "the chronological story the data seems to tell — key phases/events (no names, max 150 words)",
  "organization_strategies": [
    {
      "id": "STRAT_A",
      "name": "Short strategy name",
      "rationale": "Why this organisation suits this corpus",
      "structure": {
        "folder_name/": "what goes here and why"
      },
      "best_for": "which analysis goal this serves",
      "tradeoffs": "what this approach sacrifices"
    }
  ],
  "recommended_next_steps": [
    {
      "step": 1,
      "action": "specific, concrete action",
      "rationale": "why this comes first",
      "expected_output": "what you get from doing this"
    }
  ],
  "questions_to_resolve": ["open questions requiring human judgment"],
  "analysis_readiness": "low | medium | high — is this corpus ready for ${meta.goal}?"
}

Provide exactly 3 organisation strategies.
Be specific and actionable. No personal names. No legal conclusions.`;
}

function buildSynthesisUserMessage(groupDescriptions, overallStats, profile = ANALYSIS_PROFILE_DEFAULT) {
  const meta = getAnalysisProfileMeta(profile);
  const groupBlock = Object.values(groupDescriptions)
    .filter(g => g.llm_analysis && !g.llm_analysis.error)
    .map(g => `=== ${g.label} (${g.count} files · ${g.totalWords?.toLocaleString() || 0} words) ===\n${JSON.stringify(g.llm_analysis, null, 2)}`)
    .join('\n\n');

  return `CORPUS OVERVIEW
Analysis profile: ${meta.label}
Profile goal: ${meta.goal}
Total files:      ${overallStats.total_files}
Text files:       ${overallStats.text_files}
Total words:      ${overallStats.total_words?.toLocaleString()}
Languages:        ${JSON.stringify(overallStats.languages)}
Category count:   ${Object.keys(groupDescriptions).length}

GROUP ANALYSES:
${groupBlock}

Generate the comprehensive corpus guide JSON.`;
}

// ─── LLM caller ───────────────────────────────────────────────────────────────

const { callLLM } = require('./llm_client');

function parseJsonResponse(rawText) {
  const cleaned = String(rawText || '')
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```\s*$/,        '')
    .trim();

  const extractBalancedJson = (text) => {
    const start = text.indexOf('{');
    if (start < 0) return null;
    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let i = start; i < text.length; i++) {
      const ch = text[i];

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (ch === '\\') {
          escaped = true;
        } else if (ch === '"') {
          inString = false;
        }
        continue;
      }

      if (ch === '"') {
        inString = true;
        continue;
      }

      if (ch === '{') depth += 1;
      if (ch === '}') {
        depth -= 1;
        if (depth === 0) {
          return text.slice(start, i + 1);
        }
      }
    }

    return null;
  };

  const parseAttempt = (text) => {
    try {
      return { ok: true, data: JSON.parse(text) };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  };

  // First: direct parse
  const direct = parseAttempt(cleaned);
  if (direct.ok) return direct;

  // Second: extract the first balanced JSON object from wrapper text
  const balanced = extractBalancedJson(cleaned);
  if (balanced) {
    const parsed = parseAttempt(balanced);
    if (parsed.ok) return parsed;
  }

  // Third: remove common trailing commas then retry (best effort)
  const noTrailingCommas = cleaned
    .replace(/,\s*}/g, '}')
    .replace(/,\s*]/g, ']');

  const relaxed = parseAttempt(noTrailingCommas);
  if (relaxed.ok) return relaxed;

  try {
    return { ok: true, data: JSON.parse(cleaned) };
  } catch (e) {
    return { ok: false, error: e.message, raw: cleaned.slice(0, 500) };
  }
}

function buildHeuristicGroupAnalysis(group, samples, profile = ANALYSIS_PROFILE_DEFAULT) {
  const meta = getAnalysisProfileMeta(profile);
  const languageList = Object.keys(group.langs || {}).filter(Boolean);

  const uniqueTopics = [];
  const seen = new Set();
  for (const sample of samples || []) {
    for (const term of (sample.key_terms || [])) {
      const norm = String(term || '').toLowerCase().trim();
      if (!norm || seen.has(norm)) continue;
      seen.add(norm);
      uniqueTopics.push(norm.replace(/_/g, ' '));
      if (uniqueTopics.length >= 8) break;
    }
    if (uniqueTopics.length >= 8) break;
  }

  const allPreview = (samples || [])
    .map(s => String(s.preview || ''))
    .join('\n');

  const dateRegex = /\b(20\d{2}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]20\d{2})\b/g;
  const dateMatches = allPreview.match(dateRegex) || [];
  const temporalRange = dateMatches.length > 0
    ? `${dateMatches[0]} to ${dateMatches[dateMatches.length - 1]}`
    : null;

  const contentType = /law|legal|article|penal|regulation|cdc|icao/i.test(allPreview)
    ? 'legal_text'
    : /report|analysis|summary|finding/i.test(allPreview)
      ? 'analysis'
      : /invoice|budget|payment|fiscal|financial/i.test(allPreview)
        ? 'financial'
        : /hr|hiring|employee|onboarding|benefit/i.test(allPreview)
          ? 'hr'
          : /ticket|workflow|approval|sla|ops|operation/i.test(allPreview)
            ? 'operations'
            : 'other';

  return {
    category_description: `${group.label} contains ${group.count} file(s) with mostly textual operational/analytical content suitable for structured review.`,
    content_type: contentType,
    languages: languageList.length ? languageList : ['unknown'],
    key_topics: uniqueTopics.length ? uniqueTopics : ['process analysis', 'document operations'],
    temporal_range: temporalRange,
    quality_assessment: 'Content appears text-rich and structured, but this fallback path is based on lightweight heuristics and should be confirmed manually.',
    missing_patterns: [],
    case_relevance: `This category appears relevant for the selected profile (${meta.label}) and its analytical objectives.`,
    _fallback_used: true,
    _fallback_reason: 'llm_group_json_parse_failed'
  };
}

// ─── Guide markdown builder ───────────────────────────────────────────────────

function buildGuideMarkdown(synthesis, groupDescriptions, overallStats) {
  const lines = [];
  const date  = new Date().toISOString().split('T')[0];

  lines.push(`# Corpus Intelligence Guide`);
  lines.push(`\n> Generated by Discovery Comprehension Layer · ${date}\n`);
  lines.push('---\n');

  // ── Summary ──────────────────────────────────────────────────────────────────
  lines.push('## Corpus Summary\n');
  lines.push(synthesis.corpus_summary || '*No summary generated.*');
  lines.push('');
  lines.push(`**Corpus nature:** ${synthesis.case_nature || 'Undetermined'}`);
  lines.push(`**Analysis readiness:** \`${synthesis.analysis_readiness || 'unknown'}\``);
  lines.push(`**Total files:** ${overallStats.total_files} (${overallStats.text_files} with extractable text)`);
  lines.push(`**Total words:** ${overallStats.total_words?.toLocaleString()}`);
  lines.push('');

  // ── Key themes ────────────────────────────────────────────────────────────
  if (synthesis.key_themes?.length) {
    lines.push('## Key Themes\n');
    for (const t of synthesis.key_themes) lines.push(`- ${t}`);
    lines.push('');
  }

  // ── Temporal narrative ────────────────────────────────────────────────────
  if (synthesis.temporal_narrative) {
    lines.push('## Temporal Narrative\n');
    lines.push(synthesis.temporal_narrative);
    lines.push('');
  }

  // ── Data assessment ───────────────────────────────────────────────────────
  lines.push('## Data Assessment\n');
  if (synthesis.data_strengths?.length) {
    lines.push('### Strengths');
    for (const s of synthesis.data_strengths) lines.push(`- ✓ ${s}`);
    lines.push('');
  }
  if (synthesis.data_gaps?.length) {
    lines.push('### Gaps');
    for (const g of synthesis.data_gaps) lines.push(`- ⚠️  ${g}`);
    lines.push('');
  }

  // ── Category breakdown ────────────────────────────────────────────────────
  lines.push('---\n');
  lines.push(`## File Categories (${Object.keys(groupDescriptions).length})\n`);

  for (const g of Object.values(groupDescriptions)) {
    const a = g.llm_analysis || {};
    lines.push(`### ${g.label} — ${g.count} files · ${g.totalWords?.toLocaleString() || 0} words\n`);
    if (a.category_description) lines.push(a.category_description + '\n');
    if (a.key_topics?.length)    lines.push(`**Topics:** ${a.key_topics.slice(0, 6).join(' · ')}`);
    if (a.temporal_range)        lines.push(`**Date range:** ${a.temporal_range}`);
    if (a.quality_assessment)    lines.push(`**Quality:** ${a.quality_assessment}`);
    if (a.missing_patterns?.length) lines.push(`**Gaps:** ${a.missing_patterns.join('; ')}`);
    if (a.error)                 lines.push(`> ⚠️  Description error: ${a.error}`);
    lines.push('');
  }

  // ── Organisation strategies ───────────────────────────────────────────────
  lines.push('---\n');
  lines.push('## Organisation Strategies\n');
  lines.push('Choose the strategy that matches your analysis goal.\n');

  for (const strat of (synthesis.organization_strategies || [])) {
    lines.push(`### ${strat.id}: ${strat.name}\n`);
    lines.push(strat.rationale || '');
    lines.push('');
    if (strat.structure) {
      lines.push('**Proposed structure:**');
      for (const [folder, desc] of Object.entries(strat.structure)) {
        lines.push(`- \`${folder}\` — ${desc}`);
      }
    }
    lines.push('');
    lines.push(`**Best for:** ${strat.best_for || ''}`);
    lines.push(`**Tradeoffs:** ${strat.tradeoffs || ''}`);
    lines.push('');
  }

  // ── Next steps ────────────────────────────────────────────────────────────
  lines.push('---\n');
  lines.push('## Recommended Next Steps\n');
  for (const step of (synthesis.recommended_next_steps || [])) {
    lines.push(`### Step ${step.step}: ${step.action}\n`);
    lines.push(`**Rationale:** ${step.rationale}`);
    lines.push(`**Expected output:** ${step.expected_output}`);
    lines.push('');
  }

  // ── Open questions ────────────────────────────────────────────────────────
  if (synthesis.questions_to_resolve?.length) {
    lines.push('---\n');
    lines.push('## Open Questions for Human Review\n');
    for (const q of synthesis.questions_to_resolve) lines.push(`- ${q}`);
    lines.push('');
  }

  lines.push('---\n');
  lines.push('*Discovery Corpus Comprehension Layer · Awareness-AI*');
  return lines.join('\n');
}

// ─── Main entry point ─────────────────────────────────────────────────────────

/**
 * Run the corpus comprehension layer (Layer C) after L0–L4.
 *
 * @param {Object} store      - Pipeline store returned by runPipeline
 * @param {string} rootDir    - Source folder path
 * @param {Object} options    - { apiKey, model, outputDir, onProgress,
 *                               maxSamplesPerGroup, maxGroups, concurrency }
 * @returns {Promise<Object>} Result summary with output file paths
 */
async function runComprehension(store, rootDir, options = {}) {
  const {
    apiKey,
    model              = 'deepseek-v4-pro',
    outputDir          = path.join(rootDir, '_intelligence'),
    onProgress         = null,
    maxSamplesPerGroup = MAX_SAMPLES_PER_GROUP,
    maxGroups          = MAX_GROUPS_IN_SYNTHESIS,
    concurrency        = 3,
    analysisProfile    = ANALYSIS_PROFILE_DEFAULT
  } = options;

  if (!apiKey) throw new Error('API key required for corpus comprehension');
  const profile = normalizeAnalysisProfile(analysisProfile);
  const profileMeta = getAnalysisProfileMeta(profile);

  function progress(stage, detail) {
    const msg = `[${new Date().toISOString()}] ${stage}: ${detail}`;
    if (onProgress) onProgress(stage, detail);
    else process.stdout.write(msg + '\n');
  }

  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  // ── 1. Group files ──────────────────────────────────────────────────────────
  const allFiles = Object.values(store.getAllFiles());
  const groups   = groupFiles(allFiles);

  const overallStats = {
    total_files: allFiles.length,
    text_files:  allFiles.filter(f => f.layers?.L1?.is_text).length,
    total_words: allFiles.reduce((s, f) => s + (f.layers?.L1?.word_count || 0), 0),
    languages:   {},
    domains:     {}
  };
  for (const f of allFiles) {
    const lang   = f.layers?.L2?.language || 'unknown';
    const domain = f.layers?.L2?.primary_domain || 'general';
    overallStats.languages[lang]  = (overallStats.languages[lang]  || 0) + 1;
    overallStats.domains[domain]  = (overallStats.domains[domain]  || 0) + 1;
  }

  // Sort by size descending, cap at maxGroups
  const sortedKeys = Object.keys(groups)
    .sort((a, b) => groups[b].count - groups[a].count)
    .slice(0, maxGroups);

  progress('COMPREHEND', `${allFiles.length} files in ${sortedKeys.length} categories — profile: ${profileMeta.label}`);

  // ── 2. Describe each group (in batches) ────────────────────────────────────
  const groupDescriptions = {};
  const systemPrompt      = buildGroupSystemPrompt(profile);

  for (let i = 0; i < sortedKeys.length; i += concurrency) {
    const batch = sortedKeys.slice(i, i + concurrency);

    await Promise.allSettled(batch.map(async key => {
      const group   = groups[key];
      const samples = sampleGroup(group.files, maxSamplesPerGroup).map(buildFileSummary);

      try {
        const raw    = await callLLM(systemPrompt, buildGroupUserMessage(group, samples),
                                     { apiKey, model, maxTokens: 1024 });
        const parsed = parseJsonResponse(raw);
        const llmAnalysis = parsed.ok
          ? parsed.data
          : buildHeuristicGroupAnalysis(group, samples, profile);

        groupDescriptions[key] = {
          domain:       group.domain,
          label:        group.label,
          count:        group.count,
          totalWords:   group.totalWords,
          languages:    group.langs,
          extensions:   group.exts,
          sample_count: samples.length,
          llm_analysis: llmAnalysis,
          samples:      samples.map(s => ({ path: s.path, extension: s.extension, word_count: s.word_count }))
        };
      } catch (err) {
        groupDescriptions[key] = {
          domain:  group.domain,
          label:   group.label,
          count:   group.count,
          totalWords: group.totalWords,
          error:   err.message
        };
      }
      progress('COMPREHEND', `Described: ${group.label} (${group.count} files)`);
    }));

    if (i + concurrency < sortedKeys.length) {
      await new Promise(r => setTimeout(r, 200));
    }
  }

  // Write group descriptions immediately
  const groupDescPath = path.join(outputDir, 'group_descriptions.json');
  fs.writeFileSync(groupDescPath, JSON.stringify(groupDescriptions, null, 2));

  progress('COMPREHEND', `All groups described — synthesising corpus guide`);

  // ── 3. Synthesise overall understanding ────────────────────────────────────
  let synthesis          = {};
  let synthesisSucceeded = false;

  try {
    const raw    = await callLLM(
      buildSynthesisSystemPrompt(profile),
      buildSynthesisUserMessage(groupDescriptions, overallStats, profile),
      { apiKey, model, maxTokens: 4096 }
    );
    const parsed = parseJsonResponse(raw);
    if (parsed.ok) {
      synthesis          = parsed.data;
      synthesisSucceeded = true;
    } else {
      synthesis = { error: parsed.error, raw: raw.slice(0, 1000) };
    }
  } catch (err) {
    synthesis = { error: err.message };
  }

  // ── 4. Write all output files ──────────────────────────────────────────────
  const overviewPath  = path.join(outputDir, 'corpus_overview.json');
  const guidePath     = path.join(outputDir, 'corpus_guide.md');
  const stratPath     = path.join(outputDir, 'restructure_options.json');

  const corpusOverview = {
    generated_at:    new Date().toISOString(),
    root_dir:        rootDir,
    analysis_profile: profile,
    overall_stats:   overallStats,
    group_count:     Object.keys(groupDescriptions).length,
    synthesis,
    synthesis_ok:    synthesisSucceeded
  };

  fs.writeFileSync(overviewPath, JSON.stringify(corpusOverview, null, 2));
  fs.writeFileSync(guidePath,    buildGuideMarkdown(synthesis, groupDescriptions, overallStats));
  fs.writeFileSync(stratPath,    JSON.stringify(synthesis.organization_strategies || [], null, 2));

  progress('COMPREHEND', `Corpus guide written → ${guidePath}`);

  return {
    ok:               true,
    generated_at:     new Date().toISOString(),
    root_dir:         rootDir,
    analysis_profile: profile,
    groups_analyzed:  Object.keys(groupDescriptions).length,
    overall_stats:    overallStats,
    analysis_readiness: synthesis.analysis_readiness || null,
    question_count:   synthesis.questions_to_resolve?.length || 0,
    output_files: {
      group_descriptions:  groupDescPath,
      corpus_overview:     overviewPath,
      corpus_guide:        guidePath,
      restructure_options: stratPath
    }
  };
}

module.exports = {
  runComprehension,
  groupFiles,
  sampleGroup,
  buildFileSummary
};
