/**
 * Pipeline Layer E — Event Formalization
 *
 * Sits between L5b (raw LLM extraction) and L6 (normalization).
 * Collapses Action + Evidence + Violation ontology nodes into
 * first-class Event objects with multi-source evidence merging
 * and confidence scoring.
 *
 * An Event is "something that happened in the real world."
 * Documents are just artifacts that prove an event occurred.
 *
 * Outputs (written to {rootDir}/_intelligence/):
 *   events.json         — merged, deduplicated event objects
 *   event_graph.json    — event-to-event causal/temporal edges
 *
 * Does NOT modify the case graph — it produces a parallel view.
 */

'use strict';

const crypto = require('crypto');
const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta
} = require('./analysis_profile');

// ─── Event Type Vocabulary ────────────────────────────────────────────────────
// Groups the fine-grained action_types from L5b into higher-level event types

const ACTION_TO_EVENT_TYPE = {
  communication_failure:  'communication',
  service_denial:         'institutional_action',
  procedure_violation:    'violation_event',
  delay:                  'incident',
  physical_interaction:   'incident',
  documentation_failure:  'documentation',
  safety_violation:       'violation_event',
  policy_violation:       'violation_event',
  process_breakdown:      'incident',
  compliance_issue:       'violation_event',
  operational_update:     'documentation',
  customer_escalation:    'complaint',
  financial_irregularity: 'violation_event',
  hr_issue:               'incident',
  it_incident:            'incident',
  decision_event:         'institutional_action',
  other:                  'other'
};

// Higher-level event type vocabulary
const EVENT_TYPES = new Set([
  'incident',             // something happened (flight event, accident, misconduct)
  'communication',        // message sent, email, phone call, statement
  'complaint',            // formal complaint filed
  'institutional_action', // investigation started/closed, report issued
  'legal_process',        // lawsuit filed, ruling issued, appeal submitted
  'violation_event',      // rule/law broken (derived from L5b violations)
  'documentation',        // report submitted, record created
  'other'
]);

// ─── Event ID ─────────────────────────────────────────────────────────────────

function makeEventId() {
  return `EVT_${crypto.randomBytes(4).toString('hex')}`;
}

// ─── Date Normalization ───────────────────────────────────────────────────────

/**
 * Parse an ISO-ish string into { date, precision }.
 * precision: 'day' | 'month' | 'year' | 'unknown'
 */
function normalizeDate(raw) {
  if (!raw) return { date: null, precision: 'unknown' };

  const s = String(raw).trim();

  // Full ISO datetime
  const full = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (full) {
    const d = new Date(full[1]);
    if (!isNaN(d)) return { date: full[1], precision: 'day' };
  }

  // Year-month only
  const ym = s.match(/^(\d{4}-\d{2})$/);
  if (ym) return { date: `${ym[1]}-01`, precision: 'month' };

  // Year only
  const y = s.match(/^(\d{4})$/);
  if (y) return { date: `${y[1]}-01-01`, precision: 'year' };

  return { date: null, precision: 'unknown' };
}

// ─── Extract Events from L5b + L6 Data ────────────────────────────────────────

/**
 * Build raw Event objects from a single file's extraction result.
 * Each Action becomes a candidate event, enriched with its Evidence + Violations.
 *
 * @param {string} fileRef          - source file path
 * @param {Object} extractionResult - L5b result for this file
 * @returns {Object[]} array of raw event candidates
 */
function extractEventsFromFile(fileRef, extractionResult) {
  if (!extractionResult || extractionResult.skipped || !extractionResult.nodes) return [];

  const { nodes } = extractionResult;
  const evidence  = nodes.evidence;
  const actions   = nodes.actions   || [];
  const violations = nodes.violations || [];
  const context   = (nodes.contexts && nodes.contexts[0]) || {};

  // Map action sequence_index → grounding violations
  const violsByAction = {};
  for (const v of violations) {
    for (const actionId of (v._grounded_in_action_ids || [])) {
      if (!violsByAction[actionId]) violsByAction[actionId] = [];
      violsByAction[actionId].push(v);
    }
  }

  const events = [];

  for (const action of actions) {
    const { date, precision } = normalizeDate(action.timestamp);
    const eventType = ACTION_TO_EVENT_TYPE[action.action_type] || 'other';

    // Linked violations raise the event's significance
    const linkedViols = violsByAction[action.node_id] || [];
    const maxConfidence = linkedViols.length > 0
      ? Math.max(...linkedViols.map(v => v.confidence || 0))
      : 0;

    events.push({
      id:              makeEventId(),
      type:            eventType,
      action_type:     action.action_type,
      description:     action.description,
      date,
      date_precision:  precision,
      location:        action.location || null,
      actor_function:  action._performed_by_role_id || null,
      sequence_index:  action.sequence_index,

      // Evidence linkage
      source_documents: [fileRef],
      evidence_node_id: evidence?.node_id || null,

      // From document context
      jurisdiction:    context.jurisdiction_hint || null,

      // Violation linkage
      violations: linkedViols.map(v => ({
        violation_id: v.node_id,
        category:     v.category,
        severity:     v.severity,
        confidence:   v.confidence,
        articles:     (v._law_references || []).map(r => r.raw_text || r.framework_hint || '').filter(Boolean)
      })),

      // Confidence starts from the max violation confidence,
      // with a floor of 0.5 for any event that was explicitly extracted
      confidence: Math.max(0.5, maxConfidence),

      // Fingerprint for merge matching (type + date + description prefix)
      _fingerprint: null  // computed next
    });
  }

  // Build fingerprints for merge matching
  for (const evt of events) {
    evt._fingerprint = buildFingerprint(evt);
  }

  return events;
}

// ─── Fingerprinting for Merge ─────────────────────────────────────────────────

/**
 * Build a merge-matching fingerprint from an event's core identity.
 * Two events with the same fingerprint describe the same real-world happening.
 */
function buildFingerprint(evt) {
  const parts = [
    evt.type,
    evt.date || 'nodate',
    // Normalize description to lowercase tokens, keep first 6 words
    (evt.description || '')
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, '')
      .split(/\s+/)
      .slice(0, 6)
      .join('_')
  ];
  return crypto
    .createHash('md5')
    .update(parts.join('|'))
    .digest('hex')
    .slice(0, 12);
}

// ─── Event Merging ────────────────────────────────────────────────────────────

/**
 * Merge events with matching fingerprints.
 * Multi-source evidence accumulates; confidence increases with corroboration.
 *
 * @param {Object[]} rawEvents - all candidate events across all files
 * @returns {Object[]} merged event list
 */
function mergeEvents(rawEvents) {
  const buckets = {};

  for (const evt of rawEvents) {
    const fp = evt._fingerprint;
    if (!buckets[fp]) {
      buckets[fp] = { ...evt, _merge_count: 1 };
    } else {
      const target = buckets[fp];
      target._merge_count++;

      // Merge source documents
      for (const doc of evt.source_documents) {
        if (!target.source_documents.includes(doc)) {
          target.source_documents.push(doc);
        }
      }

      // Merge violations (deduplicate by violation_id)
      const existing = new Set(target.violations.map(v => v.violation_id));
      for (const v of evt.violations) {
        if (!existing.has(v.violation_id)) {
          target.violations.push(v);
          existing.add(v.violation_id);
        }
      }

      // Use most precise date
      if (evt.date_precision === 'day' && target.date_precision !== 'day') {
        target.date           = evt.date;
        target.date_precision = 'day';
      }

      // Take location if missing
      if (!target.location && evt.location) target.location = evt.location;

      // Confidence boost for corroboration: +0.08 per additional source, capped at 1.0
      target.confidence = Math.min(1.0, target.confidence + 0.08);

      // Prefer longer description
      if ((evt.description || '').length > (target.description || '').length) {
        target.description = evt.description;
      }
    }
  }

  return Object.values(buckets);
}

// ─── Event Graph (Causal / Temporal Edges) ────────────────────────────────────

/**
 * Build edges between events based on temporal sequence and shared actors/violations.
 *
 * Edge types:
 *   PRECEDED_BY    — temporal ordering (A happened before B)
 *   CAUSED         — A's violation triggered B (e.g. incident → complaint)
 *   RELATED_TO     — shared actors or entities, no clear causal direction
 */
function buildEventGraph(events) {
  const edges = [];

  // Sort by date (nulls last)
  const sorted = events
    .slice()
    .sort((a, b) => {
      if (!a.date && !b.date) return 0;
      if (!a.date) return 1;
      if (!b.date) return -1;
      return a.date.localeCompare(b.date);
    });

  // Temporal precedence — link consecutive dated events
  for (let i = 0; i < sorted.length - 1; i++) {
    const curr = sorted[i];
    const next = sorted[i + 1];
    if (curr.date && next.date) {
      edges.push({
        from:  curr.id,
        to:    next.id,
        type:  'PRECEDED_BY',
        label: `${curr.date} → ${next.date}`
      });
    }
  }

  // Causal inference: incident/violation → complaint/institutional_action
  const CAUSE_TARGETS = new Set(['complaint', 'institutional_action', 'legal_process']);
  const CAUSE_SOURCES = new Set(['incident', 'violation_event']);

  for (const src of sorted) {
    if (!CAUSE_SOURCES.has(src.type)) continue;
    for (const tgt of sorted) {
      if (tgt.id === src.id) continue;
      if (!CAUSE_TARGETS.has(tgt.type)) continue;
      // Must be after source
      if (src.date && tgt.date && tgt.date >= src.date) {
        // Check if they share jurisdiction or actor
        const related = src.jurisdiction && tgt.jurisdiction && src.jurisdiction === tgt.jurisdiction;
        const sharedActor = src.actor_function && tgt.actor_function && src.actor_function === tgt.actor_function;
        if (related || sharedActor || !src.jurisdiction) {
          edges.push({
            from:  src.id,
            to:    tgt.id,
            type:  'CAUSED',
            label: `${src.type} → ${tgt.type}`
          });
        }
      }
    }
  }

  // Related: shared source documents
  for (let i = 0; i < sorted.length; i++) {
    for (let j = i + 1; j < sorted.length; j++) {
      const a = sorted[i];
      const b = sorted[j];
      const shared = a.source_documents.filter(d => b.source_documents.includes(d));
      if (shared.length > 0 && a.type !== b.type) {
        // Only add if no causal edge already exists
        const hasCausal = edges.some(e =>
          (e.from === a.id && e.to === b.id) || (e.from === b.id && e.to === a.id)
        );
        if (!hasCausal) {
          edges.push({
            from:  a.id,
            to:    b.id,
            type:  'RELATED_TO',
            label: `shared source: ${shared[0]}`
          });
        }
      }
    }
  }

  return edges;
}

// ─── Main ─────────────────────────────────────────────────────────────────────

/**
 * Run event formalization over extraction results.
 *
 * @param {Object} extractionResults - Map of file_ref → L5b extraction result
 * @param {Object} options           - { outputDir, onProgress }
 * @returns {Object} { events, event_graph, stats }
 */
function formalizeEvents(extractionResults, options = {}) {
  const {
    outputDir,
    onProgress,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT
  } = options;

  const profile = normalizeAnalysisProfile(analysisProfile);
  const profileMeta = getAnalysisProfileMeta(profile);

  const progress = (msg) => { if (onProgress) onProgress('events', msg); };

  // Phase 1: Extract candidate events from every file
  progress('Extracting events from L5b results');
  const rawEvents = [];
  let filesWithEvents = 0;

  for (const [fileRef, result] of Object.entries(extractionResults)) {
    const fileEvents = extractEventsFromFile(fileRef, result);
    if (fileEvents.length > 0) filesWithEvents++;
    rawEvents.push(...fileEvents);
  }

  progress(`${rawEvents.length} raw events from ${filesWithEvents} files`);

  // Phase 2: Merge corroborated events
  progress('Merging corroborated events');
  const merged = mergeEvents(rawEvents);

  const multiSource = merged.filter(e => e.source_documents.length > 1);
  progress(`${merged.length} unique events (${multiSource.length} corroborated by multiple sources)`);

  // Phase 3: Build causal/temporal graph
  progress('Building event graph');
  const edges = buildEventGraph(merged);

  // Phase 4: Clean output (remove internal fields)
  const events = merged.map(evt => {
    const { _fingerprint, _merge_count, ...clean } = evt;
    clean.corroboration = {
      source_count: clean.source_documents.length,
      merge_count:  _merge_count
    };
    return clean;
  });

  // Sort chronologically
  events.sort((a, b) => {
    if (!a.date && !b.date) return 0;
    if (!a.date) return 1;
    if (!b.date) return -1;
    return a.date.localeCompare(b.date);
  });

  const stats = {
    raw_events:         rawEvents.length,
    merged_events:      events.length,
    corroborated:       multiSource.length,
    files_with_events:  filesWithEvents,
    graph_edges:        edges.length,
    causal_edges:       edges.filter(e => e.type === 'CAUSED').length,
    temporal_edges:     edges.filter(e => e.type === 'PRECEDED_BY').length,
    by_type:            events.reduce((acc, e) => { acc[e.type] = (acc[e.type] || 0) + 1; return acc; }, {})
  };

  const eventGraph = {
    _meta: {
      generated_at: new Date().toISOString(),
      pipeline_layer: 'events',
      analysis_profile: profile,
      analysis_profile_label: profileMeta.label,
      total_events: events.length,
      total_edges: edges.length
    },
    events: events.map(e => e.id),
    edges
  };

  // Write output files if outputDir is provided
  if (outputDir) {
    const fs   = require('fs');
    const path = require('path');

    if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

    fs.writeFileSync(
      path.join(outputDir, 'events.json'),
      JSON.stringify({ stats, events }, null, 2)
    );
    fs.writeFileSync(
      path.join(outputDir, 'event_graph.json'),
      JSON.stringify(eventGraph, null, 2)
    );
  }

  return { events, event_graph: eventGraph, stats };
}

module.exports = {
  formalizeEvents,
  extractEventsFromFile,
  mergeEvents,
  buildEventGraph,
  normalizeDate,
  EVENT_TYPES
};
