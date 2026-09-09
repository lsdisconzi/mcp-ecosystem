/**
 * structured_extract.js — Deterministic, evidence-grounded extraction
 *
 * When the extraction LLM returns empty (a known failure mode in this
 * environment), narrative transcripts can STILL be extracted correctly from
 * their own curated metadata — no fabrication, no hallucination:
 *
 *   - participants      → ActorRole nodes (functional roles)
 *   - segments[].text   → verbatim Segment quotes
 *   - key_evidentiary_findings → Action nodes (analyst findings, grounded)
 *   - violations_cited  → Violation nodes (codes the transcript itself cites)
 *   - recording_datetime/location → timestamps & location
 *
 * This is the honest baseline: it only surfaces what the source document
 * already declares. LLM extraction remains the richer path when it works.
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const crypto = require('crypto');
const { detectJsonKind, decodeNarrativeTranscript } = require('./document_decode');

const PREFIX = {
  evidence: 'EVID',
  action:   'ACTN',
  actor:    'ROLE',
  segment:  'SEG',
  violation:'VIOL'
};

function makeNodeId(type) {
  return `${PREFIX[type] || 'NODE'}_${crypto.randomBytes(4).toString('hex')}`;
}

function isoFromRecording(raw) {
  const s = String(raw || '').trim().replace(' ', 'T');
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) return null;
  const base = s.length >= 19 ? s.slice(0, 19) : `${s}:00`;
  return `${base}.000Z`;
}

/**
 * Map a free-form participant role / speaker label to the v2.4 functional
 * role vocabulary. Names are never emitted.
 */
function mapActorFunction(raw) {
  const r = String(raw || '').toLowerCase();
  if (!r) return 'other';
  if (/passenger|passageiro|pasajero/.test(r)) return 'passenger';
  if (/pilot|captain|capt[aã]o|cabin|crew|tripul/.test(r)) return 'crew';
  if (/security|seguran[cç]a|seguridad/.test(r)) return 'security_personnel';
  if (/polic|carabineros|carabinero/.test(r)) return 'police_officer';
  if (/dgac|regulator|authority|autoridad|anac/.test(r)) return 'regulator';
  if (/pdi|immigration|migra|control\b|inspector/.test(r)) return 'controller';
  if (/airline|latam|airport|aeroporto|aeropuerto|staff|agente|agent|counter|ground|gate|check-?in/.test(r)) return 'airline_staff';
  if (/witness|testemunha|testigo|fellow/.test(r)) return 'witness';
  if (/manager|supervisor/.test(r)) return 'manager';
  return 'airline_staff';
}

function inferActionType(text) {
  const t = String(text || '').toLowerCase();
  if (/aggress|confront|standoff|physical|forc|remov|empurr|violent/.test(t)) return 'physical_interaction';
  if (/denied|denial|remov|offload|prevent|block|barred|nega[cç]/.test(t)) return 'service_denial';
  if (/delay|atraso|retraso/.test(t)) return 'delay';
  if (/document|carta|record|report|signed|assin|falsif/.test(t)) return 'documentation_failure';
  if (/inform|notif|communicat|aviso|notice|written/.test(t)) return 'communication_failure';
  if (/safety|risk|danger|perigo|seguran/.test(t)) return 'safety_violation';
  return 'operational_update';
}

function inferViolationCategory(code) {
  const c = String(code || '').toLowerCase();
  if (/abuso|abuse|forcible|physical/.test(c)) return 'safety_violation';
  if (/denied|denial|compensation|consumer|cdc|cach|rights/.test(c)) return 'consumer_rights';
  if (/calumnia|falsif|document/.test(c)) return 'documentation_failure';
  return 'regulatory_non_compliance';
}

/**
 * Build grounded ontology nodes from a narrative transcript file on disk.
 * @param {Object} file    - pipeline store file record
 * @param {string} rootDir - absolute workspace root
 * @returns {object|null}  - nodes object, or null if not a transcript / unreadable
 */
function buildFromTranscript(file, rootDir) {
  if (!file || !rootDir || !file.file_ref) return null;
  if (file.layers?.L1?.structured_kind !== 'narrative_transcript' &&
      file.layers?.L1?.structured?.kind !== 'narrative_transcript') return null;

  let parsed;
  try {
    const abs = path.resolve(rootDir, file.file_ref);
    parsed = JSON.parse(fs.readFileSync(abs, 'utf8'));
  } catch {
    return null;
  }
  if (detectJsonKind(parsed, file.file_ref) !== 'narrative_transcript') return null;

  const dec = decodeNarrativeTranscript(parsed, file.file_ref);
  const now = new Date().toISOString();
  const iso = isoFromRecording(dec.recording_datetime) || now;

  const evidenceId = makeNodeId('evidence');
  const evidence = {
    node_id:       evidenceId,
    type:          'Evidence',
    evidence_type: 'document',
    source:        file.file_ref,
    timestamp:     iso,
    description:   dec.title || dec.subtitle || null,
    _source_file_id: file.layers?.L0?.file_node_id || null,
    _chunk_index:  0
  };

  // Actors (functional roles only — zero names)
  const participants = Array.isArray(parsed.participants) ? parsed.participants : [];
  const actorsByFunction = {};
  for (const p of participants) {
    const fn = mapActorFunction(p.role || p.speaker_label || p.canonical_name || '');
    if (!actorsByFunction[fn]) {
      actorsByFunction[fn] = { node_id: makeNodeId('actor'), type: 'ActorRole', function: fn, context: null };
    }
  }

  // Verbatim segments (skip ASR artifacts)
  const segments = [];
  const rawSegments = Array.isArray(parsed.segments) ? parsed.segments : [];
  for (const s of rawSegments) {
    const text = String((s && s.text) || '').trim();
    if (!text || /^\[[^\]]*\]$/.test(text)) continue;
    segments.push({
      node_id: makeNodeId('segment'),
      type: 'Segment',
      text: text.slice(0, 500),
      position: (s.index != null ? s.index : segments.length) + 1,
      evidence_node_id: evidenceId,
      speaker: mapActorFunction(s.speaker || s.speaker_label || '')
    });
  }

  // Actions — grounded in the analyst's own key findings.
  const actions = [];
  const findings = Array.isArray(parsed.key_evidentiary_findings) ? parsed.key_evidentiary_findings : [];
  findings.forEach((f, i) => {
    const desc = String((f && (f.finding || f.description)) || '').trim().slice(0, 200);
    if (!desc) return;
    const actionId = makeNodeId('action');
    actions.push({
      node_id:            actionId,
      type:               'Action',
      action_type:        inferActionType(desc),
      description:        desc,
      timestamp:          iso,
      sequence_index:     i + 1,
      location:           parsed.location || null,
      _performed_by_role_id: null,
      _evidence_id:       evidenceId,
      _segment_ids:       []
    });
  });

  // If no curated findings, emit a single stage event so the file still
  // contributes to the timeline (grounded in title/subtitle, not fabricated).
  if (actions.length === 0) {
    const title = String(parsed.subtitle || parsed.title || '').trim().slice(0, 200);
    actions.push({
      node_id:        makeNodeId('action'),
      type:           'Action',
      action_type:    'operational_update',
      description:    title || 'Transcript stage',
      timestamp:      iso,
      sequence_index: 1,
      location:       parsed.location || null,
      _performed_by_role_id: null,
      _evidence_id:   evidenceId,
      _segment_ids:   []
    });
  }

  // Violations — the codes the transcript itself cites (ground truth), with a
  // clean raw reference (no JSON escaping artifacts).
  const violations = [];
  for (const code of dec.violations_cited || []) {
    violations.push({
      node_id:      makeNodeId('violation'),
      type:         'Violation',
      category:     inferViolationCategory(code),
      description:  `Cited in transcript: ${code}`.slice(0, 300),
      timestamp:    iso,
      severity:     'medium',
      confidence:   null,  // unrated — not model-derived
      _law_references: [{
        raw_text:       code,
        framework_hint: 'transcript_cited',
        jurisdiction:   dec.jurisdiction || null,
        article_hint:   null
      }],
      _grounded_in_action_ids: [],
      _supported_by_evidence_id: evidenceId,
      _llm_run_id: null
    });
  }

  return {
    evidence,
    actions,
    actors: Object.values(actorsByFunction),
    segments,
    violations,
    llm_runs: [],
    contexts: [{
      document_type:      'transcript',
      primary_language:   dec.language || 'other',
      approximate_date:   dec.recording_datetime ? String(dec.recording_datetime).slice(0, 10) : null,
      jurisdiction_hint:  dec.jurisdiction || 'INT',
      subject_matter:     dec.title || 'Narrative transcript',
      key_entities:       []
    }],
    _extraction_source: 'structured_transcript',
    _heuristic: true,
    _degraded: false
  };
}

module.exports = {
  buildFromTranscript,
  mapActorFunction,
  inferActionType,
  inferViolationCategory
};
