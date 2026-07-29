/**
 * Pipeline Layer S — Case State Engine
 *
 * A declarative rule evaluator that sits on top of formalized events
 * and the case graph. Detects anomalies, procedural gaps, and
 * recommends next steps by reasoning over event sequences.
 *
 * Rules are plain objects — no DSL, no external engine.
 * Each rule takes the event list + timeline and returns zero or more
 * findings (alerts, flags, recommendations).
 *
 * Outputs (written to {rootDir}/_intelligence/):
 *   case_state.json   — current state, findings, next steps
 *
 * Does NOT modify events or the case graph.
 */

'use strict';

const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile
} = require('./analysis_profile');

// ─── Case Phase Detection ────────────────────────────────────────────────────

/**
 * Determine the current phase of the case based on which event types
 * have been observed. Phases are cumulative — later phases imply earlier ones.
 *
 * Phases (in order):
 *   1. incident_detected   — at least one incident/violation event
 *   2. complaint_filed     — a complaint or communication event with complaint indicators
 *   3. investigation_open  — an institutional action referencing investigation
 *   4. legal_proceedings   — legal_process events present
 *   5. ruling_issued       — legal_process event with ruling/decision indicators
 *   6. case_closed         — explicit closure indicators
 */
const PHASE_ORDER = [
  'incident_detected',
  'complaint_filed',
  'investigation_open',
  'legal_proceedings',
  'ruling_issued',
  'case_closed'
];

function detectPhase(events) {
  const phases = new Set();

  for (const evt of events) {
    const desc = (evt.description || '').toLowerCase();

    // Phase 1: incident
    if (evt.type === 'incident' || evt.type === 'violation_event') {
      phases.add('incident_detected');
    }

    // Phase 2: complaint
    if (evt.type === 'complaint' ||
        (evt.type === 'communication' && /complaint|reclama|queixa|denuncia/i.test(desc))) {
      phases.add('complaint_filed');
    }

    // Phase 3: investigation
    if (evt.type === 'institutional_action' && /investigat|inquérito|averigua|apura/i.test(desc)) {
      phases.add('investigation_open');
    }

    // Phase 4: legal proceedings
    if (evt.type === 'legal_process') {
      phases.add('legal_proceedings');

      // Phase 5: ruling
      if (/ruling|decisão|sentença|resolução|judgment|acórdão|fallo/i.test(desc)) {
        phases.add('ruling_issued');
      }

      // Phase 6: closure
      if (/close|encerr|arquiv|dismiss|trânsito em julgado/i.test(desc)) {
        phases.add('case_closed');
      }
    }
  }

  // Return the highest phase reached
  let currentPhase = 'unknown';
  for (const phase of PHASE_ORDER) {
    if (phases.has(phase)) currentPhase = phase;
  }

  return {
    current_phase:  currentPhase,
    phases_reached: PHASE_ORDER.filter(p => phases.has(p)),
    phases_missing: PHASE_ORDER.filter(p => !phases.has(p))
  };
}

// ─── Rule Definitions ─────────────────────────────────────────────────────────

/**
 * Each rule is { id, name, severity, check(events, phase, stats) → finding|null }
 *
 * A finding: { rule_id, rule_name, severity, type, message, details }
 *   type: 'anomaly' | 'gap' | 'recommendation' | 'alert'
 */
const RULES = [

  // ── Procedural Anomalies ──────────────────────────────────────────────────

  {
    id:       'RULE_001',
    name:     'Investigation without ruling (>2 years)',
    severity: 'high',
    check(events, phase) {
      if (phase.current_phase !== 'investigation_open') return null;

      const investigations = events.filter(e =>
        e.type === 'institutional_action' && /investigat|inquérito|averigua/i.test(e.description || '')
      );
      const rulings = events.filter(e =>
        e.type === 'legal_process' && /ruling|decisão|sentença|judgment/i.test(e.description || '')
      );

      if (investigations.length === 0 || rulings.length > 0) return null;

      // Check if oldest investigation is >2 years old
      const oldest = investigations
        .filter(e => e.date)
        .sort((a, b) => a.date.localeCompare(b.date))[0];

      if (!oldest || !oldest.date) return null;

      const ageMs = Date.now() - new Date(oldest.date).getTime();
      const ageYears = ageMs / (365.25 * 24 * 60 * 60 * 1000);

      if (ageYears < 2) return null;

      return {
        type:     'anomaly',
        message:  `Investigation opened ${oldest.date} has been running for ${ageYears.toFixed(1)} years with no ruling.`,
        details:  { investigation_date: oldest.date, age_years: Math.round(ageYears * 10) / 10 }
      };
    }
  },

  {
    id:       'RULE_002',
    name:     'Complaint without institutional response (>90 days)',
    severity: 'high',
    check(events) {
      const complaints = events.filter(e =>
        e.type === 'complaint' ||
        (e.type === 'communication' && /complaint|reclama|queixa|denuncia/i.test(e.description || ''))
      ).filter(e => e.date);

      const responses = events.filter(e =>
        e.type === 'institutional_action' || e.type === 'legal_process'
      ).filter(e => e.date);

      if (complaints.length === 0) return null;

      // Find earliest complaint
      const earliest = complaints.sort((a, b) => a.date.localeCompare(b.date))[0];

      // Find earliest response after complaint
      const responseAfter = responses
        .filter(r => r.date >= earliest.date)
        .sort((a, b) => a.date.localeCompare(b.date))[0];

      if (responseAfter) {
        const gapMs   = new Date(responseAfter.date) - new Date(earliest.date);
        const gapDays = gapMs / (1000 * 60 * 60 * 24);
        if (gapDays <= 90) return null;

        return {
          type:     'anomaly',
          message:  `${Math.round(gapDays)}-day gap between complaint (${earliest.date}) and first institutional response (${responseAfter.date}).`,
          details:  { complaint_date: earliest.date, response_date: responseAfter.date, gap_days: Math.round(gapDays) }
        };
      }

      // No response at all
      const ageMs   = Date.now() - new Date(earliest.date).getTime();
      const ageDays = ageMs / (1000 * 60 * 60 * 24);

      if (ageDays > 90) {
        return {
          type:     'anomaly',
          message:  `Complaint filed on ${earliest.date} with no institutional response after ${Math.round(ageDays)} days.`,
          details:  { complaint_date: earliest.date, days_without_response: Math.round(ageDays) }
        };
      }

      return null;
    }
  },

  {
    id:       'RULE_003',
    name:     'High-severity violation without legal action',
    severity: 'medium',
    check(events, phase, stats, profileMeta) {
      const highViols = events.filter(e =>
        e.violations && e.violations.some(v => v.severity === 'high')
      );
      const legalActions = events.filter(e => e.type === 'legal_process');
      const legalMode = isLegalProfile(profileMeta?.key || ANALYSIS_PROFILE_DEFAULT);
      const findingNoun = legalMode ? 'violation(s)' : `${profileMeta?.finding_plural || 'findings'}`;
      const escalationLabel = legalMode ? 'legal proceedings' : (profileMeta?.proceeding_label || 'formal escalation');

      if (highViols.length > 0 && legalActions.length === 0) {
        return {
          type:     'recommendation',
          message:  `${highViols.length} high-severity ${findingNoun} detected but no ${escalationLabel} found. Consider escalation.`,
          details:  { high_violations: highViols.length }
        };
      }
      return null;
    }
  },

  // ── Evidence Gaps ─────────────────────────────────────────────────────────

  {
    id:       'RULE_004',
    name:     'Events without dated evidence',
    severity: 'low',
    check(events) {
      const undated = events.filter(e => !e.date);
      if (undated.length === 0) return null;

      const pct = Math.round((undated.length / events.length) * 100);
      if (pct < 20) return null;  // tolerable

      return {
        type:     'gap',
        message:  `${undated.length} of ${events.length} events (${pct}%) have no date. Timeline reconstruction will be incomplete.`,
        details:  { undated_count: undated.length, total: events.length, pct }
      };
    }
  },

  {
    id:       'RULE_005',
    name:     'Single-source events (no corroboration)',
    severity: 'low',
    check(events) {
      const single = events.filter(e => e.source_documents.length === 1);
      if (single.length === 0) return null;

      const pct = Math.round((single.length / events.length) * 100);
      return {
        type:     'gap',
        message:  `${single.length} events (${pct}%) rely on a single source document. Cross-referencing recommended.`,
        details:  { single_source_count: single.length, pct }
      };
    }
  },

  // ── Timeline Coherence ─────────────────────────────────────────────────────

  {
    id:       'RULE_006',
    name:     'Large temporal gaps in event sequence',
    severity: 'medium',
    check(events) {
      const dated = events.filter(e => e.date).sort((a, b) => a.date.localeCompare(b.date));
      if (dated.length < 2) return null;

      const gaps = [];
      for (let i = 0; i < dated.length - 1; i++) {
        const gapMs   = new Date(dated[i + 1].date) - new Date(dated[i].date);
        const gapDays = gapMs / (1000 * 60 * 60 * 24);
        if (gapDays > 180) {  // 6-month gap
          gaps.push({
            from:      dated[i].date,
            to:        dated[i + 1].date,
            gap_days:  Math.round(gapDays),
            from_type: dated[i].type,
            to_type:   dated[i + 1].type
          });
        }
      }

      if (gaps.length === 0) return null;

      return {
        type:     'gap',
        message:  `${gaps.length} gap(s) of 6+ months found in the event timeline. Missing evidence or unreported events likely.`,
        details:  { gaps }
      };
    }
  },

  // ── Next Step Recommendations ──────────────────────────────────────────────

  {
    id:       'RULE_007',
    name:     'Recommend Argus law enrichment',
    severity: 'low',
    check(events, phase, stats, profileMeta) {
      const legalMode = isLegalProfile(profileMeta?.key || ANALYSIS_PROFILE_DEFAULT);
      const withArticles = events.filter(e =>
        e.violations && e.violations.some(v => v.articles && v.articles.length > 0)
      );
      const withViols = events.filter(e => e.violations && e.violations.length > 0);

      if (withViols.length > 0 && withArticles.length < withViols.length) {
        return {
          type:     'recommendation',
          message:  legalMode
            ? `${withViols.length - withArticles.length} violation events lack specific article references. Run Argus enrichment to resolve.`
            : `${withViols.length - withArticles.length} finding events lack specific policy/regulatory references. Run enrichment to resolve.`,
          details:  { events_with_articles: withArticles.length, events_with_violations: withViols.length }
        };
      }
      return null;
    }
  },

  {
    id:       'RULE_008',
    name:     'Phase-aware next step',
    severity: 'medium',
    check(events, phase, stats, profileMeta) {
      const legalMode = isLegalProfile(profileMeta?.key || ANALYSIS_PROFILE_DEFAULT);
      const recs = legalMode
        ? {
          incident_detected:   'File a formal complaint or report to the relevant authority.',
          complaint_filed:     'Monitor for institutional response. Set 90-day follow-up reminder.',
          investigation_open:  'Gather and preserve all supporting evidence for the investigation.',
          legal_proceedings:   'Prepare case summary and ensure all evidence is court-admissible.',
          ruling_issued:       'Review ruling for appeal grounds. Check statute of limitations for appeal.',
          case_closed:         'Archive case materials. Document lessons learned.'
        }
        : {
          incident_detected:   'Open an operational incident record and assign accountable owners.',
          complaint_filed:     'Track response SLA and document remediation commitments.',
          investigation_open:  'Collect corroborating records and define corrective actions with deadlines.',
          legal_proceedings:   'Escalate to governance/compliance review with an executive summary.',
          ruling_issued:       'Translate decision outcomes into controls, policies, and runbook updates.',
          case_closed:         'Close the incident and document lessons learned for prevention.'
        };

      const rec = recs[phase.current_phase];
      if (!rec) return null;

      return {
        type:     'recommendation',
        message:  rec,
        details:  { phase: phase.current_phase }
      };
    }
  }
];

// ─── Main Engine ──────────────────────────────────────────────────────────────

/**
 * Run the case state engine over formalized events.
 *
 * @param {Object[]} events   - formalized event array from events.js
 * @param {Object}   options  - { outputDir, onProgress }
 * @returns {Object} { phase, findings, next_steps, stats }
 */
function evaluateCaseState(events, options = {}) {
  const {
    outputDir,
    onProgress,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT
  } = options;
  const profile = normalizeAnalysisProfile(analysisProfile);
  const profileMeta = getAnalysisProfileMeta(profile);
  const progress = (msg) => { if (onProgress) onProgress('case_state', msg); };

  progress(`Evaluating ${events.length} events (${profileMeta.label})`);

  // Detect phase
  const phase = detectPhase(events);
  progress(`Case phase: ${phase.current_phase}`);

  // Calculate event stats for rules
  const stats = {
    total_events:    events.length,
    dated_events:    events.filter(e => e.date).length,
    event_types:     events.reduce((a, e) => { a[e.type] = (a[e.type] || 0) + 1; return a; }, {}),
    date_range:      getDateRange(events),
    avg_confidence:  events.length > 0
      ? Math.round(events.reduce((s, e) => s + e.confidence, 0) / events.length * 100) / 100
      : 0,
    total_violations: events.reduce((s, e) => s + (e.violations?.length || 0), 0),
    multi_source:    events.filter(e => e.source_documents?.length > 1).length
  };

  // Run all rules
  const findings = [];
  for (const rule of RULES) {
    try {
      const result = rule.check(events, phase, stats, profileMeta);
      if (result) {
        findings.push({
          rule_id:   rule.id,
          rule_name: rule.name,
          severity:  rule.severity,
          ...result
        });
      }
    } catch (err) {
      // Don't let a single rule failure break the engine
      findings.push({
        rule_id:   rule.id,
        rule_name: rule.name,
        severity:  'low',
        type:      'error',
        message:   `Rule evaluation failed: ${err.message}`
      });
    }
  }

  // Sort findings by severity (high → medium → low)
  const severityOrder = { high: 0, medium: 1, low: 2 };
  findings.sort((a, b) => (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3));

  // Extract next steps from recommendations
  const next_steps = findings
    .filter(f => f.type === 'recommendation')
    .map(f => ({ action: f.message, severity: f.severity, rule: f.rule_name }));

  const caseState = {
    _meta: {
      generated_at:    new Date().toISOString(),
      pipeline_layer:  'case_state',
      analysis_profile: profile,
      analysis_profile_label: profileMeta.label,
      rules_evaluated: RULES.length,
      rules_triggered: findings.length
    },
    phase,
    findings,
    next_steps,
    stats
  };

  progress(`${findings.length} findings, ${next_steps.length} recommendations`);

  // Write output
  if (outputDir) {
    const fs   = require('fs');
    const path = require('path');
    if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });
    fs.writeFileSync(
      path.join(outputDir, 'case_state.json'),
      JSON.stringify(caseState, null, 2)
    );
  }

  return caseState;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getDateRange(events) {
  const dates = events.filter(e => e.date).map(e => e.date).sort();
  if (dates.length === 0) return { earliest: null, latest: null, span_days: 0 };

  const earliest = dates[0];
  const latest   = dates[dates.length - 1];
  const spanMs   = new Date(latest) - new Date(earliest);
  const spanDays = Math.round(spanMs / (1000 * 60 * 60 * 24));

  return { earliest, latest, span_days: spanDays };
}

module.exports = {
  evaluateCaseState,
  detectPhase,
  RULES,
  PHASE_ORDER
};
