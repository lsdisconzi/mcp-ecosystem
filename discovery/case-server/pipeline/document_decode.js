/**
 * document_decode.js — Structured decode for JSON documents (Layer 1 helper)
 *
 * The L1 layer historically stored RAW file bytes as text for `.json` files.
 * That corrupted every downstream stage (language detection, L5b extraction,
 * law resolution) for structured corpora such as:
 *
 *   1. Narrative transcripts  — { segments:[{speaker,text}], title, ... }
 *   2. Legal violation dossiers — { violation_id, legal_basis[], ... }
 *
 * This module decodes those structures into clean, readable text plus typed
 * metadata so that L2–L7 operate on meaning instead of JSON syntax noise.
 *
 * Design notes:
 *   - Identity isolation is preserved: speaker labels rendered from
 *     participants resolve to functional roles; names inside parentheses are
 *     stripped from labels (source speech is left untouched — it is evidence).
 *   - Canonical case identity: folder/file prefix `I-00X` wins over any
 *     inconsistent `case_id` field (confirmed decision).
 *   - Jurisdiction normalization: `IN` → `INT`.
 */

'use strict';

// ─── Small text helpers ───────────────────────────────────────────────────────

function cleanSpeakerLabel(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  // "Passenger (Leandro Disconzi)" -> "Passenger"; "Latam Pilot Ruiz" -> as-is
  const paren = s.match(/^([^(]+?)\s*\([^)]*\)\s*$/);
  if (paren && paren[1].trim()) return paren[1].trim();
  // Keep generic labels only if they carry no obvious personal-name pattern.
  return s;
}

function isNoiseSegment(text) {
  const t = String(text || '').trim();
  if (!t) return true;
  // ASR artifacts such as [Silence/Artifact], [Music], etc.
  if (/^\[[^\]]*\]$/.test(t)) return true;
  if (/^(\(\s*)?(silence|inaudible|unintelligible|music|applause|noise|artifacts?|laughter)\b/i.test(t)) return true;
  return false;
}

function fmtSeconds(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n < 0) return '';
  const m = Math.floor(n / 60);
  const s = Math.floor(n % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function normalizeJurisdiction(value) {
  const raw = String(value || '').trim().toUpperCase();
  if (!raw) return null;
  // Confirmed decision: normalize IN -> INT
  if (raw === 'IN' || raw === 'IN/CL') return 'INT';
  if (raw === 'CL/INT') return 'CL/INT';
  if (raw === 'CL') return 'CL';
  if (raw === 'BR') return 'BR';
  if (raw === 'INT') return 'INT';
  return raw;
}

/**
 * Normalize a law/violation code reference (e.g. "cl-014", "IN-003", "CL-014").
 * Keeps descriptive citations intact (e.g. "CACH Art. 133 — ...").
 * @returns {string|null} uppercase code like "CL-014"/"INT-003" or null
 */
function normalizeLawCode(value) {
  const raw = String(value || '').trim().toUpperCase().replace(/\s+/g, ' ');
  if (!raw) return null;
  // Convert IN-xxx to INT-xxx (confirmed decision).
  const m = raw.match(/^(IN|INT)-(\d+)$/);
  if (m) return `INT-${m[2]}`;
  const m2 = raw.match(/^(CL|BR)-(\d+)$/);
  if (m2) return `${m2[1]}-${m2[2]}`;
  // Descriptive long-form citations are left as-is for downstream matching.
  return /^(CL|BR|INT)-\d+/.test(raw) ? raw : raw;
}

// ─── Canonical case id ────────────────────────────────────────────────────────

const CASE_PREFIX_RE = /I[-_ ]?(\d{2,3})/i;

function normalizeCaseId(raw, fileRef) {
  const fromRaw = String(raw || '').trim();
  const rawMatch = fromRaw.match(CASE_PREFIX_RE);
  if (rawMatch) return `I-${rawMatch[1]}`;

  // Folder / file prefix is authoritative (confirmed decision #2).
  const refMatch = String(fileRef || '').match(/(?:^|\/)(I[-_ ]?0\d{2})/i);
  if (refMatch) return refMatch[1].replace(/[_\s-]+/g, '-');
  return fromRaw || null;
}

// ─── Kind detection ───────────────────────────────────────────────────────────

/**
 * Classify a parsed JSON object.
 * @returns {'narrative_transcript'|'legal_dossier'|'other'}
 */
function detectJsonKind(parsed, fileRef = '') {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return 'other';

  const hasViolationId = typeof parsed.violation_id === 'string' && /^(CL|BR|IN|INT)-\d+$/i.test(parsed.violation_id.trim());
  const hasDossierShape = hasViolationId &&
    (Array.isArray(parsed.legal_basis) ||
     parsed.element_grids ||
     parsed.required_elements_status ||
     Array.isArray(parsed.candidate_articles));

  if (hasDossierShape || (hasViolationId && (parsed.incident_id || parsed.incident))) {
    return 'legal_dossier';
  }

  const hasSegments = Array.isArray(parsed.segments) && parsed.segments.length > 0 &&
    typeof parsed.segments[0] === 'object' && parsed.segments[0] !== null;
  const hasTranscriptMeta = (parsed.transcript_id || parsed.narrative_id || parsed.audio_id) &&
    (parsed.title || parsed.subtitle);

  if (hasSegments || hasTranscriptMeta) return 'narrative_transcript';
  return 'other';
}

// ─── Narrative transcript decode ──────────────────────────────────────────────

/**
 * Decode a narrative transcript into readable text + typed metadata.
 */
function decodeNarrativeTranscript(parsed, fileRef = '') {
  const participants = Array.isArray(parsed.participants) ? parsed.participants : [];
  const roleByLabel = {};
  const roleByCanonical = {};
  for (const p of participants) {
    const role = (p.role || '').trim();
    const canonical = (p.canonical_name || '').trim();
    const label = (p.speaker_label || p.canonical_name || '').trim();
    if (role) {
      if (canonical) roleByCanonical[canonical.toLowerCase()] = role;
      if (label) roleByLabel[label.toLowerCase()] = role;
    }
  }

  const segments = Array.isArray(parsed.segments) ? parsed.segments : [];
  let reviewedCount = 0;
  let substantive = 0;
  const lines = [];

  const title = String(parsed.title || parsed.subtitle || '').trim();
  if (title) lines.push(`# ${title}`);
  if (parsed.subtitle && parsed.subtitle !== title) lines.push(`_${parsed.subtitle}_`);

  const metaBits = [];
  if (parsed.recording_datetime) metaBits.push(`Date/time: ${parsed.recording_datetime}`);
  if (parsed.location) metaBits.push(`Location: ${parsed.location}`);
  if (metaBits.length) lines.push('');
  lines.push(...metaBits);

  const roleSummary = participants
    .map(p => (p.role || '').trim())
    .filter((r, i, a) => r && a.indexOf(r) === i);
  if (roleSummary.length) {
    lines.push(`Participants (roles): ${roleSummary.join(', ')}`);
  }
  lines.push('');

  let lastSpeaker = null;
  for (const seg of segments) {
    if (!seg || typeof seg !== 'object') continue;
    if (seg.reviewed) reviewedCount += 1;
    const text = String(seg.text || '').trim();
    if (isNoiseSegment(text)) continue;

    let speaker = cleanSpeakerLabel(seg.speaker || '');
    if (!speaker) speaker = cleanSpeakerLabel(seg.speaker_label || '');
    if (speaker) {
      const role = roleByLabel[speaker.toLowerCase()] || roleByCanonical[speaker.toLowerCase()];
      if (role) speaker = role;
    }
    if (!speaker) speaker = 'Speaker';

    const time = fmtSeconds(seg.start);
    const prefix = lastSpeaker === speaker ? '  ' : `[${speaker}]`;
    lastSpeaker = speaker;
    lines.push(`${time ? `${time} ` : ''}${prefix} ${text}`.trim());
    substantive += 1;
  }

  // Forensic cluster summaries (curated analyst content) — kept as structured notes.
  const clusters = parsed.forensic_clusters && typeof parsed.forensic_clusters === 'object'
    ? parsed.forensic_clusters : {};
  const clusterLines = Object.values(clusters)
    .map(c => (c && typeof c === 'object' && c.summary ? c.summary : null))
    .filter(Boolean);
  if (clusterLines.length) {
    lines.push('');
    lines.push('---');
    lines.push('Stage summaries:');
    for (const cl of clusterLines) lines.push(`- ${cl}`);
  }

  // Key evidentiary findings (curated) — these are the analyst's own notes.
  const findings = Array.isArray(parsed.key_evidentiary_findings)
    ? parsed.key_evidentiary_findings : [];
  if (findings.length) {
    lines.push('');
    lines.push('---');
    lines.push('Key evidentiary findings:');
    for (const f of findings) {
      if (!f || typeof f !== 'object') continue;
      const findingText = String(f.finding || f.description || '').trim();
      if (findingText) lines.push(`- ${findingText}`);
    }
  }

  const fullText = lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  const words = fullText.split(/\s+/).filter(Boolean).length;

  const language = normalizeLang(parsed.language);
  const location = String(parsed.location || '');
  const caseId = normalizeCaseId(parsed.case_id || parsed.caseId, fileRef);
  const jurisdiction = inferJurisdictionFromLocation(location, caseId, parsed);

  return {
    kind: 'narrative_transcript',
    fullText,
    word_count: words,
    segment_count: segments.length,
    reviewed_share: segments.length ? Math.round((reviewedCount / segments.length) * 100) : 0,
    title,
    subtitle: parsed.subtitle || null,
    language,
    recording_datetime: parsed.recording_datetime || null,
    case_id: caseId,
    narrative_id: parsed.narrative_id || null,
    chronological_order: parsed.chronological_order || null,
    prior_stage: parsed.prior_stage || null,
    next_stage: parsed.next_stage || null,
    jurisdiction,
    violations_cited: Array.isArray(parsed.violations_cited)
      ? parsed.violations_cited.map(v => String(v).trim()).filter(Boolean)
      : []
  };
}

function normalizeLang(raw) {
  const v = String(raw || '').trim().toLowerCase();
  if (['pt', 'es', 'en'].includes(v)) return v;
  return null;
}

function inferJurisdictionFromLocation(location, caseId, parsed) {
  const hay = `${location || ''} ${caseId || ''} ${parsed.case_id || ''} ${parsed.title || ''}`.toLowerCase();
  if (/guarulhos|brasil|brazil|s[ãa]o paulo|aeroporto.*(gr)?u|\.br|brazil/i.test(hay)) return 'BR';
  if (/santiago|chile|scl|dgac|carabineros|pdi\b/i.test(hay)) return 'CL';
  return null;
}

// ─── Legal dossier decode ─────────────────────────────────────────────────────

/**
 * Decode a legal dossier into a compact registry entry + short readable text.
 */
function decodeLegalDossier(parsed, fileRef = '') {
  const code = String(parsed.violation_id || '').trim().toUpperCase();
  const confidenceRaw = parsed.confidence;
  const confValue = confidenceRaw && typeof confidenceRaw === 'object'
    ? Number(confidenceRaw.value)
    : Number(confidenceRaw);

  const legalBasis = Array.isArray(parsed.legal_basis) ? parsed.legal_basis : [];
  const basisSummary = legalBasis
    .filter(b => b && typeof b === 'object')
    .map(b => `${b.article_id || b.article_name || ''}${b.status === 'established' ? ' [established]' : ''}`.trim())
    .filter(Boolean);

  const category = String(parsed.category || '');
  const isSeed = /seed|lote\s*f/i.test(category);

  const incidents = toArray(parsed.incident_id || parsed.incident);
  const incidentText = incidents.map(v => typeof v === 'string' ? v : JSON.stringify(v)).join(' ');
  const incidentCases = [...new Set((incidentText.match(/I[-_ ]?\d{2,3}/gi) || []).map(m => m.replace(/[_ ]/g, '-')))];
  const caseId = normalizeCaseId(incidentCases[0] || parsed.case_id, fileRef);

  const jurisdiction = normalizeJurisdiction(parsed.jurisdiction);

  const title = String(parsed.title || '').trim();
  const entry = {
    code,
    title,
    jurisdiction,
    case_ids: incidentCases,
    case_id: caseId,
    severity: parsed.severity || null,
    category,
    is_seed: isSeed,
    has_broken_refs: Boolean(parsed.has_broken_refs),
    confidence: {
      value: Number.isFinite(confValue) ? confValue : 0,
      components: confidenceRaw && typeof confidenceRaw === 'object' && confidenceRaw.components
        ? confidenceRaw.components : {}
    },
    legal_basis: legalBasis
      .filter(b => b && typeof b === 'object')
      .map(b => ({
        article_id: b.article_id || null,
        article_name: b.article_name || null,
        status: b.status || null,
        applicability: b.applicability || null,
        verbatim_text: b.verbatim_text || null
      })),
    candidate_articles: Array.isArray(parsed.candidate_articles) ? parsed.candidate_articles.map(a => ({
      candidate_article_id: a && (a.candidate_article_id || a.candidate_name) || null,
      framework_cache_status: a && a.framework_cache_status || null,
      preliminary_view: a && a.preliminary_view || null
    })) : [],
    element_grid_keys: parsed.element_grids && typeof parsed.element_grids === 'object'
      ? Object.keys(parsed.element_grids) : [],
    related_violations: Array.isArray(parsed.related_violations) ? parsed.related_violations : [],
    trust_tier: computeDossierTier({
      confValue: Number.isFinite(confValue) ? confValue : 0,
      hasVerbatim: legalBasis.some(b => b && typeof b === 'object' && (b.verbatim_text || '').trim()),
      broken: Boolean(parsed.has_broken_refs),
      seed: isSeed
    })
  };

  const fullText = [
    `# ${title || code}`,
    `${code} · ${jurisdiction || ''} · ${category || ''}${parsed.severity ? ` · ${parsed.severity}` : ''}`,
    '',
    'Legal basis:',
    ...(basisSummary.length ? basisSummary.map(b => `- ${b}`) : ['- (none recorded)'])
  ].join('\n');

  return { entry, fullText };
}

function computeDossierTier({ confValue, hasVerbatim, broken, seed }) {
  if (broken || seed) return 'C';
  if (confValue > 0 && hasVerbatim) return 'A';
  if (hasVerbatim) return 'B';
  return 'C';
}

function toArray(v) {
  if (v === undefined || v === null) return [];
  if (Array.isArray(v)) return v;
  return [v];
}

// ─── File-level decode used by extract.js L1 ─────────────────────────────────

/**
 * Attempt structured decode of a JSON file's text content.
 * @param {string} text  raw file content
 * @param {string} fileRef relative path (used for case-id fallback)
 * @returns {null|{kind,fullText,preview,meta}}
 */
function decodeStructuredJson(text, fileRef = '') {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  const kind = detectJsonKind(parsed, fileRef);
  if (kind === 'narrative_transcript') {
    const dec = decodeNarrativeTranscript(parsed, fileRef);
    const meta = { ...dec };
    delete meta.fullText;
    return {
      kind,
      fullText: dec.fullText,
      meta
    };
  }
  if (kind === 'legal_dossier') {
    const { entry, fullText } = decodeLegalDossier(parsed, fileRef);
    return {
      kind,
      fullText,
      meta: { ...entry, fullText: undefined }
    };
  }
  return null;
}

// ─── Exclusion helpers (shared with walkers) ─────────────────────────────────

const EXCLUDED_BASENAMES = new Set([
  '.ds_store', 'thumbs.db', 'desktop.ini', '.gitignore'
]);

function isExcludedBasename(name) {
  const base = String(name || '').toLowerCase();
  if (EXCLUDED_BASENAMES.has(base)) return true;
  if (/\.bak$/i.test(base)) return true;               // .bak backups
  if (/\.(tmp|temp|swp|swo|part|download|orig)$/i.test(base)) return true;
  if (/^\._/.test(base)) return true;                  // macOS resource forks
  if (/~$/.test(name || '')) return true;              // editor backups (foo~)
  return false;
}

function isExcludedRelativePath(relPath) {
  const rel = String(relPath || '').replace(/\\/g, '/').toLowerCase();
  if (!rel) return true;
  if (isExcludedBasename(rel.split('/').pop())) return true;
  if (rel.startsWith('_intelligence/')) return true;
  if (rel.startsWith('.discovery/')) return true;
  if (rel === 'pipeline_store.json') return true;
  return false;
}

module.exports = {
  cleanSpeakerLabel,
  isNoiseSegment,
  normalizeJurisdiction,
  normalizeLawCode,
  normalizeCaseId,
  detectJsonKind,
  decodeNarrativeTranscript,
  decodeLegalDossier,
  decodeStructuredJson,
  isExcludedBasename,
  isExcludedRelativePath,
  computeDossierTier
};
