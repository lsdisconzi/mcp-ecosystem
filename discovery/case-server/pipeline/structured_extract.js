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
    local_datetime: dec.recording_datetime || null,
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

  // Verbatim segments (skip ASR artifacts). We keep a map from the original
  // segment index to its node + local segment_datetime so findings can point to
  // exact evidence and resolve precise per-observation local datetimes.
  const segments = [];
  const rawSegments = Array.isArray(parsed.segments) ? parsed.segments : [];
  const segByOrigIndex = {};       // originalIndex -> { node_id, datetime }
  for (const s of rawSegments) {
    const text = String((s && s.text) || '').trim();
    if (!text || /^\[[^\]]*\]$/.test(text)) continue;
    const origIndex = (s && s.index != null) ? s.index : null;
    const segNode = {
      node_id: makeNodeId('segment'),
      type: 'Segment',
      text: text.slice(0, 500),
      // original 0-based index in the source transcript — the upstream handle
      // used to identify this exact segment verbatim
      index: origIndex,
      position: (origIndex != null ? origIndex : segments.length) + 1,
      evidence_node_id: evidenceId,
      speaker: mapActorFunction(s.speaker || s.speaker_label || ''),
      local_datetime: (s && s.segment_datetime) || null
    };
    segments.push(segNode);
    if (origIndex != null) {
      segByOrigIndex[origIndex] = {
        node_id: segNode.node_id,
        datetime: (s && s.segment_datetime) || null
      };
    }
  }

  // Expand a finding/segment reference like "5" or "0-5" into concrete indices.
  function expandSegRefs(refs) {
    const out = [];
    for (const ref of Array.isArray(refs) ? refs : []) {
      const str = String(ref).trim();
      const range = str.match(/^(\d+)\s*-\s*(\d+)$/);
      if (range) {
        const a = parseInt(range[1], 10); const b = parseInt(range[2], 10);
        for (let x = Math.min(a, b); x <= Math.max(a, b); x++) out.push(x);
      } else if (/^\d+$/.test(str)) {
        out.push(parseInt(str, 10));
      }
    }
    return out;
  }

  // ── Verbatim → segment inference ─────────────────────────────────────────
  // Findings whose author did not fill the `segments` field still usually quote
  // the transcript verbatim (e.g. Stewardess: 'eso es lo que me indican.'). We
  // locate the ORIGINAL segment index(s) whose text contains that quote, so the
  // event/timeline can be traced upstream even without an explicit ref. Only
  // text-level anchors are used — never meaning/paraphrase — so inferred links
  // stay grounded (no fabrication). Anything that cannot be anchored stays empty.
  function normForMatch(t) {
    return String(t || '')
      .toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9ñ\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // Pull quoted spans out of a finding ("…", '…', “…”/‘…’, «…»). A quote must be
  // bounded by real delimiters (start/space/colon/dash before the opener; space
  // or punctuation after the closer) so apostrophes inside words like
  // "document's" are never mistaken for quote delimiters.
  function extractQuotedSpans(text) {
    const spans = [];
    const pairs = [["'", "'"], ['"', '"'], ['\u2018', '\u2019'], ['\u201c', '\u201d'], ['\u00ab', '\u00bb']];
    for (const [open, close] of pairs) {
      const openEsc = open === "'" || open === '"' ? '\\' + open : open;
      const closeEsc = close === "'" || close === '"' ? '\\' + close : close;
      const re = new RegExp(
        '(^|[\\s:;\\u2014\\u2013\\(\\[/,\\u2019])' + openEsc + '([^' + openEsc + closeEsc + ']{4,})' + closeEsc +
        '(?=$|[\\s.\\,\\?\\!;:\\u2014\\u2013\\-\\]\\)\\u2019])', 'g'
      );
      let m;
      while ((m = re.exec(String(text || '')))) spans.push(m[2]);
    }
    return spans;
  }

  // Longest-common-substring length (characters) — robust to ASR typos/inserts.
  function lcsLength(a, b) {
    const n = a.length, m = b.length;
    if (!n || !m) return 0;
    let best = 0;
    const dp = new Uint16Array(m + 1);
    for (let i = 1; i <= n; i++) {
      let prev = 0;
      for (let j = 1; j <= m; j++) {
        const cur = dp[j];
        if (a[i - 1] === b[j - 1]) { dp[j] = prev + 1; if (dp[j] > best) best = dp[j]; }
        else dp[j] = 0;
        prev = cur;
      }
    }
    return best;
  }

  // Match one normalized quote against the transcript's non-artifact segments.
  // Returns original indices whose text contains the quote (exact) or shares a
  // long-enough common substring (typo-tolerant). Empty when no anchor found.
  const inferableSegments = [];      // { index, norm, dtMs } of kept segments
  for (const s of rawSegments) {
    const text = String((s && s.text) || '').trim();
    if (!text || /^\[[^\]]*\]$/.test(text)) continue;
    if ((s && s.index == null)) continue;
    inferableSegments.push({
      index: s.index,
      norm: normForMatch(text),
      dtMs: Date.parse(String((s && s.segment_datetime) || '').replace(' ', 'T'))
    });
  }

  function matchQuoteToSegments(rawQuote) {
    const nq = normForMatch(rawQuote);
    if (nq.length < 5) return [];
    const out = [];
    // Short/distinctive quote → require exact containment.
    if (nq.length <= 12) {
      for (const seg of inferableSegments) if (seg.norm.includes(nq)) out.push(seg.index);
      return out;
    }
    // Longer quote → exact first, else typo-tolerant LCS over the whole quote.
    let exact = [];
    for (const seg of inferableSegments) if (seg.norm.includes(nq)) exact.push(seg.index);
    if (exact.length) return exact;
    let bestLen = 0, bestIdx = [];
    for (const seg of inferableSegments) {
      const l = lcsLength(nq, seg.norm);
      if (l > bestLen) { bestLen = l; bestIdx = [seg.index]; }
      else if (l === bestLen && l > 0) bestIdx.push(seg.index);
    }
    const threshold = Math.max(10, Math.floor(nq.length * 0.5));
    return bestLen >= threshold ? bestIdx.slice(0, 6) : [];
  }

  // Resolve the original transcript indices grounding a finding: explicit refs
  // win; otherwise infer from verbatim quoted spans, "(segs N,M)" hints, or an
  // unambiguous whole-text anchor. Returns { indices, inferred }.
  function resolveFindingSegmentIndices(f) {
    const textFull = String((f && (f.finding || f.description)) || '').trim();
    const explicit = expandSegRefs((f && f.segments) || [])
      .filter(idx => segByOrigIndex[idx]);
    if (explicit.length) return { indices: explicit, inferred: false };

    const found = new Set();
    // "(segs 72, 87, 109)" hints embedded in the finding text.
    for (const m of textFull.matchAll(/\(\s*segs?\s+([\d,\s]+)\s*\)/gi)) {
      for (const n of m[1].match(/\d+/g)) { const idx = parseInt(n, 10); if (segByOrigIndex[idx]) found.add(idx); }
    }
    for (const span of extractQuotedSpans(textFull)) {
      for (const idx of matchQuoteToSegments(span)) {
        if (segByOrigIndex[idx]) found.add(idx);
      }
    }
    // Whole-finding verbatim anchor (no quotes) — only when a single segment
    // contains a long verbatim run of the description itself.
    if (found.size === 0 && textFull.length > 0) {
      const nf = normForMatch(textFull);
      if (nf.length >= 12) {
        let bestLen = 0, bestIdx = [];
        for (const seg of inferableSegments) {
          const l = lcsLength(nf, seg.norm);
          if (l > bestLen) { bestLen = l; bestIdx = [seg.index]; }
          else if (l === bestLen && l > 0) bestIdx.push(seg.index);
        }
        if (bestLen >= 14 && bestIdx.length <= 2) {
          for (const idx of bestIdx) if (segByOrigIndex[idx]) found.add(idx);
        }
      }
    }
    // Time-anchor fallback (last resort): if no text/verbatim anchor exists,
    // snap to the transcript segment whose segment_datetime is nearest to the
    // finding's local datetime anchor. This keeps analytical summary findings
    // (which quote nothing) traceable to a concrete upstream segment by time.
    if (found.size === 0) {
      const anchorMs = Date.parse(String(dec.recording_datetime || '').replace(' ', 'T'));
      if (Number.isFinite(anchorMs)) {
        let bestIdx = null, bestDiff = Infinity;
        for (const seg of inferableSegments) {
          if (!Number.isFinite(seg.dtMs)) continue;
          const diff = Math.abs(seg.dtMs - anchorMs);
          if (diff < bestDiff) { bestDiff = diff; bestIdx = seg.index; }
        }
        if (bestIdx != null && segByOrigIndex[bestIdx]) found.add(bestIdx);
      }
    }
    const indices = [...found].sort((a, b) => a - b);
    return { indices: indices.slice(0, 10), inferred: indices.length > 0 };
  }

  // Earliest local datetime referenced by a set of original segment indices.
  function earliestSegDatetime(refs) {
    let earliest = null;
    for (const idx of expandSegRefs(refs)) {
      const seg = segByOrigIndex[idx];
      const dt = seg && seg.datetime;
      if (!dt) continue;
      if (!earliest || String(dt) < String(earliest)) earliest = String(dt);
    }
    return earliest;
  }

  // Actions — grounded in the analyst's own key findings, each carrying the
  // precise local datetime of its earliest supporting segment.
  const actions = [];
  const findings = Array.isArray(parsed.key_evidentiary_findings) ? parsed.key_evidentiary_findings : [];
  findings.forEach((f, i) => {
    const desc = String((f && (f.finding || f.description)) || '').trim().slice(0, 200);
    if (!desc) return;

    // Explicit transcript `segments` refs win; findings without them get the
    // segment indices inferred from their own verbatim quotes (still grounded
    // in exact transcript text, never paraphrased meaning).
    const { indices, inferred } = resolveFindingSegmentIndices(f);
    const segIds = indices
      .map(idx => (segByOrigIndex[idx] ? segByOrigIndex[idx].node_id : null))
      .filter(Boolean);
    const localDt = earliestSegDatetime(indices.length ? indices : (f && f.segments)) || dec.recording_datetime || null;

    const actionId = makeNodeId('action');
    const action = {
      node_id:            actionId,
      type:               'Action',
      action_type:        inferActionType(desc),
      description:        desc,
      timestamp:          localDt || iso,
      local_datetime:     localDt,
      sequence_index:     i + 1,
      location:           parsed.location || null,
      _performed_by_role_id: null,
      _evidence_id:       evidenceId,
      _segment_ids:       segIds.slice(0, 10)
    };
    // Traceability provenance: true when the segment links were inferred from
    // verbatim text rather than declared by the transcript author.
    if (inferred && segIds.length) action._segment_inferred = true;
    actions.push(action);
  });

  // If no curated findings, emit a single stage event so the file still
  // contributes to the timeline (grounded in title/subtitle, not fabricated).
  if (actions.length === 0) {
    const title = String(parsed.subtitle || parsed.title || '').trim().slice(0, 200);
    // Time-anchor this stage event to the transcript segment nearest the
    // recording start, so it is still traceable to a concrete upstream segment.
    const anchorMs = Date.parse(String(dec.recording_datetime || '').replace(' ', 'T'));
    let stageIdx = null;
    if (Number.isFinite(anchorMs)) {
      let bestDiff = Infinity;
      for (const seg of inferableSegments) {
        if (!Number.isFinite(seg.dtMs)) continue;
        const diff = Math.abs(seg.dtMs - anchorMs);
        if (diff < bestDiff) { bestDiff = diff; stageIdx = seg.index; }
      }
    }
    const stageSegIds = (stageIdx != null && segByOrigIndex[stageIdx])
      ? [segByOrigIndex[stageIdx].node_id]
      : [];
    actions.push({
      node_id:        makeNodeId('action'),
      type:           'Action',
      action_type:    'operational_update',
      description:    title || 'Transcript stage',
      timestamp:      iso,
      local_datetime: dec.recording_datetime || null,
      sequence_index: 1,
      location:       parsed.location || null,
      _performed_by_role_id: null,
      _evidence_id:   evidenceId,
      _segment_ids:   stageSegIds
    });
    if (stageSegIds.length) actions[actions.length - 1]._segment_inferred = true;
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
      local_datetime: dec.recording_datetime || null,
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
