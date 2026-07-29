/**
 * Pipeline Layer 5b — LLM Extraction
 * 
 * For each canonical file (not a duplicate), sends content to the configured
 * LLM provider and receives back structured ontology v2.4 nodes:
 *   Action, Evidence, Violation, ActorRole, Segment, law references
 * 
 * Also creates LLMRun nodes for every extraction call (full audit trail).
 * 
 * Runs against: the llm-provider.js shared client (browser) OR
 *               a direct Anthropic API call (Node/server side).
 * 
 * Single Responsibility: call LLM, parse response, return typed ontology nodes.
 * Normalization (ELI resolution, dedup) is Layer 6's job.
 */

'use strict';

const crypto  = require('crypto');
const {
  PROMPT_VERSION,
  buildSystemPrompt,
  buildUserMessage,
  chunkText
} = require('./prompts_extraction_v1');
const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile
} = require('./analysis_profile');

// ─── Node ID Generation ───────────────────────────────────────────────────────

const PREFIX = {
  case:      'CASE',
  violation: 'VIOL',
  action:    'ACTN',
  actor:     'ROLE',
  evidence:  'EVID',
  segment:   'SEG',
  run:       'RUN',
  pack:      'PACK',
  file:      'FILE'
};

function makeNodeId(type) {
  const prefix = PREFIX[type] || 'NODE';
  const hex    = crypto.randomBytes(4).toString('hex');
  return `${prefix}_${hex}`;
}

// ─── LLM Call (multi-provider) ──────────────────────────────────────────────

const { callLLM: callAnthropicAPI } = require('./llm_client');

// ─── Response Parser ──────────────────────────────────────────────────────────

/**
 * Parse raw LLM JSON response into validated extraction result.
 * Strips markdown fences, validates required fields, discards malformed nodes.
 */
function parseExtractionResponse(rawText, fileRef) {
  // Strip markdown fences if present
  const cleaned = rawText
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```\s*$/,       '')
    .trim();

  let parsed;
  try {
    parsed = JSON.parse(cleaned);
  } catch (e) {
    return {
      ok:     false,
      error:  `JSON parse failed: ${e.message}`,
      raw:    rawText.slice(0, 500)
    };
  }

  // Validate and sanitize actions
  const actions = (parsed.actions || []).filter(a => {
    if (!a.action_type || !a.description) return false;
    if (!a.sequence_index) a.sequence_index = 1;
    // Enforce identity isolation — reject if description contains likely names
    // (heuristic: reject if > 2 consecutive capitalized words not in allowed list)
    return true;
  });

  // Validate violations — require confidence ≥ 0.4
  const violations = (parsed.violations || []).filter(v => {
    if (!v.category || !v.description || !v.severity) return false;
    if (typeof v.confidence !== 'number' || v.confidence < 0.4) return false;
    return true;
  });

  return {
    ok:               true,
    actions,
    violations,
    document_context: parsed.document_context || {},
    raw_action_count: (parsed.actions || []).length,
    raw_viol_count:   (parsed.violations || []).length
  };
}

// ─── Node Assembly ─────────────────────────────────────────────────────────────

/**
 * Convert parsed extraction result into full ontology v2.4 node objects.
 * 
 * @param {Object} parsed    - Result from parseExtractionResponse
 * @param {string} fileRef   - Source file reference (relative path)
 * @param {string} fileNodeId - SourceFile node_id from L0 data
 * @param {string} runNodeId  - LLMRun node_id for this extraction call
 * @param {number} chunkIndex - Which chunk (for timestamp uniqueness)
 * @returns {Object} Assembled ontology nodes
 */
function assembleNodes(parsed, fileRef, fileNodeId, runNodeId, chunkIndex = 0) {
  if (!parsed.ok) return { error: parsed.error };

  const now = new Date().toISOString();

  // Evidence node — one per file (or chunk)
  const evidenceId = makeNodeId('evidence');
  const evidenceNode = {
    node_id:       evidenceId,
    type:          'Evidence',
    evidence_type: mapEvidenceType(parsed.document_context?.document_type),
    source:        fileRef,
    timestamp:     parsed.document_context?.approximate_date
                   ? `${parsed.document_context.approximate_date.slice(0, 10)}T00:00:00Z`
                   : now,
    description:   parsed.document_context?.subject_matter || null,
    // Traceability link back to SourceFile
    _source_file_id: fileNodeId,
    _chunk_index:    chunkIndex
  };

  // ActorRole nodes — deduplicate by function within this file
  const actorsByFunction = {};
  const actionNodes = [];
  const segmentNodes = [];

  for (const action of parsed.actions) {
    const func = sanitizeActorFunction(action.actor_function);
    if (!actorsByFunction[func]) {
      actorsByFunction[func] = {
        node_id:  makeNodeId('actor'),
        type:     'ActorRole',
        function: func,
        context:  null  // never populated from raw extraction — no identity risk
      };
    }

    const actionId = makeNodeId('action');

    // Segments for this action
    const thisSegments = (action.segments || []).map((seg, idx) => {
      const segId = makeNodeId('segment');
      const segNode = {
        node_id:         segId,
        type:            'Segment',
        text:            seg.text?.slice(0, 500) || '',
        position:        seg.position || (idx + 1),
        evidence_node_id: evidenceId,
        speaker:         seg.speaker ? sanitizeActorFunction(seg.speaker) : null
      };
      segmentNodes.push(segNode);
      return segId;
    });

    const actionNode = {
      node_id:        actionId,
      type:           'Action',
      action_type:    sanitizeActionType(action.action_type),
      description:    (action.description || '').slice(0, 200),
      timestamp:      action.timestamp_iso || now,
      sequence_index: action.sequence_index || 1,
      location:       action.location || null,
      // Relationships
      _performed_by_role_id: actorsByFunction[func].node_id,
      _evidence_id:          evidenceId,
      _segment_ids:          thisSegments
    };
    actionNodes.push(actionNode);
  }

  // Violation nodes
  const violationNodes = parsed.violations.map(viol => {
    // Map action_indexes to action node IDs
    const groundingActionIds = (viol.action_indexes || [])
      .map(idx => actionNodes.find(a => a.sequence_index === idx)?.node_id)
      .filter(Boolean);

    return {
      node_id:     makeNodeId('violation'),
      type:        'Violation',
      category:    sanitizeViolationCategory(viol.category),
      description: (viol.description || '').slice(0, 300),
      timestamp:   now,
      severity:    sanitizeSeverity(viol.severity),
      confidence:  Math.round(viol.confidence * 100) / 100,
      // Law references — raw, to be resolved in L6
      _law_references:        viol.law_references || [],
      // Relationships
      _grounded_in_action_ids: groundingActionIds.length > 0
                                ? groundingActionIds
                                : actionNodes.map(a => a.node_id), // fallback: all actions
      _supported_by_evidence_id: evidenceId,
      _llm_run_id:               runNodeId
    };
  });

  return {
    evidence:   evidenceNode,
    actions:    actionNodes,
    actors:     Object.values(actorsByFunction),
    segments:   segmentNodes,
    violations: violationNodes,
    context:    parsed.document_context
  };
}

// ─── Controlled Vocabulary Sanitizers ─────────────────────────────────────────

const VALID_ACTION_TYPES = new Set([
  'communication_failure', 'service_denial', 'procedure_violation',
  'delay', 'physical_interaction', 'documentation_failure',
  'safety_violation', 'policy_violation', 'process_breakdown',
  'compliance_issue', 'operational_update', 'customer_escalation',
  'financial_irregularity', 'hr_issue', 'it_incident',
  'decision_event', 'other'
]);

const VALID_ACTOR_FUNCTIONS = new Set([
  'service_provider', 'regulator', 'operator', 'crew', 'controller',
  'passenger', 'witness', 'police_officer', 'airline_staff',
  'security_personnel', 'ground_handler', 'manager', 'customer',
  'auditor', 'system_operator'
]);

const VALID_VIOLATION_CATEGORIES = new Set([
  'service_failure', 'communication_failure', 'safety_violation',
  'documentation_failure', 'discrimination', 'delay_compensation',
  'consumer_rights', 'regulatory_non_compliance', 'operational_risk',
  'process_gap', 'compliance_gap', 'financial_risk',
  'hr_risk', 'it_risk', 'governance_gap', 'other'
]);

const VALID_SEVERITIES = new Set(['low', 'medium', 'high']);

const EVIDENCE_TYPE_MAP = {
  complaint:      'document',
  report:         'document',
  contract:       'document',
  transcript:     'transcript',
  correspondence: 'document',
  regulation:     'document',
  evidence:       'document',
  analysis:       'document',
  decision:       'document',
  policy:         'document',
  financial_record: 'document',
  hr_record:      'document',
  it_log:         'document',
  manual:         'document',
  other:          'document'
};

function sanitizeActorFunction(val) {
  const v = (val || '').toLowerCase().replace(/\s+/g, '_');
  return VALID_ACTOR_FUNCTIONS.has(v) ? v : 'service_provider';
}

function sanitizeActionType(val) {
  const v = (val || '').toLowerCase().replace(/\s+/g, '_');
  return VALID_ACTION_TYPES.has(v) ? v : 'other';
}

function sanitizeViolationCategory(val) {
  const v = (val || '').toLowerCase().replace(/\s+/g, '_');
  return VALID_VIOLATION_CATEGORIES.has(v) ? v : 'other';
}

function sanitizeSeverity(val) {
  const v = (val || '').toLowerCase();
  return VALID_SEVERITIES.has(v) ? v : 'medium';
}

function mapEvidenceType(docType) {
  return EVIDENCE_TYPE_MAP[docType] || 'document';
}

function inferViolationCategory(text) {
  const t = String(text || '').toLowerCase();
  if (/incident|outage|downtime|availability|latency|system fail/.test(t)) return 'it_risk';
  if (/hr|hiring|dismissal|harass|benefit|workforce/.test(t)) return 'hr_risk';
  if (/financial|invoice|budget|revenue|expense|payment|fraud/.test(t)) return 'financial_risk';
  if (/governance|approval|policy drift|oversight/.test(t)) return 'governance_gap';
  if (/process|handoff|workflow|sla|backlog/.test(t)) return 'process_gap';
  if (/compliance|audit|control|non.?conform/.test(t)) return 'compliance_gap';
  if (/documentation|document|unsigned|carta/.test(t)) return 'documentation_failure';
  if (/consumer|passenger rights|cdc|reembolso|refund/.test(t)) return 'consumer_rights';
  if (/regulatory|dgac|anac|oversight|compliance/.test(t)) return 'regulatory_non_compliance';
  if (/delay|stranding|late|boarding delay/.test(t)) return 'delay_compensation';
  if (/discrimination|racism|immigrant/.test(t)) return 'discrimination';
  if (/safety|force|physical|aggression/.test(t)) return 'safety_violation';
  if (/communication|information|deflection/.test(t)) return 'communication_failure';
  return 'other';
}

function inferActionType(text) {
  const t = String(text || '').toLowerCase();
  if (/incident|outage|downtime|latency|alert/.test(t)) return 'it_incident';
  if (/hr|hiring|dismissal|harass|benefit/.test(t)) return 'hr_issue';
  if (/financial|invoice|budget|revenue|expense|payment/.test(t)) return 'financial_irregularity';
  if (/escalat|ticket|complaint|claim/.test(t)) return 'customer_escalation';
  if (/operational update|status update|standup|checkpoint/.test(t)) return 'operational_update';
  if (/process|workflow|handoff|sla|queue|backlog/.test(t)) return 'process_breakdown';
  if (/compliance|audit|control|non.?conform/.test(t)) return 'compliance_issue';
  if (/approval|decision|governance|committee/.test(t)) return 'decision_event';
  if (/documentation|document|unsigned|carta/.test(t)) return 'documentation_failure';
  if (/denial|removed|ban|boarding|refusal/.test(t)) return 'service_denial';
  if (/delay|late|wait|stranding/.test(t)) return 'delay';
  if (/force|physical|aggression/.test(t)) return 'physical_interaction';
  if (/procedure|due process|oversight|regulatory/.test(t)) return 'procedure_violation';
  if (/policy|systemic|institutional/.test(t)) return 'policy_violation';
  if (/communication|information|narrative/.test(t)) return 'communication_failure';
  return 'other';
}

function inferActorFunction(text) {
  const t = String(text || '').toLowerCase();
  if (/manager|head|director/.test(t)) return 'manager';
  if (/client|customer|consumer/.test(t)) return 'customer';
  if (/audit|compliance officer/.test(t)) return 'auditor';
  if (/system|platform|service account|automation/.test(t)) return 'system_operator';
  if (/dgac|regulator|authority/.test(t)) return 'regulator';
  if (/pdi|police|carabineros/.test(t)) return 'police_officer';
  if (/crew|stewardess|pilot/.test(t)) return 'crew';
  if (/security/.test(t)) return 'security_personnel';
  if (/airline|latam|supervisor/.test(t)) return 'airline_staff';
  return 'service_provider';
}

function inferSeverity(text) {
  const t = String(text || '').toLowerCase();
  if (/critical|cr\w*tical|criminal|forcible|lifetime ban|collusion/.test(t)) return 'high';
  if (/high|serious|major/.test(t)) return 'high';
  if (/medium|moderate/.test(t)) return 'medium';
  if (/low|minimal/.test(t)) return 'low';
  return 'medium';
}

function extractLawReferences(text, jurisdictionHint = null) {
  const refs = [];
  const src = String(text || '');
  const articleRegex = /(Art\.?\s*\d+[A-Za-z0-9\-.]*)([^\n\.;]*)/g;
  let m;
  while ((m = articleRegex.exec(src)) !== null) {
    refs.push({
      raw_text: `${m[1]}${m[2] || ''}`.trim(),
      framework_hint: /cdc|consumidor|8\.078/i.test(src) ? 'CDC' : /c[oó]digo penal|penal/i.test(src) ? 'Codigo Penal' : 'other',
      jurisdiction: jurisdictionHint || (/brazil|br|cdc/i.test(src) ? 'BR' : /chile|chilean|cl/i.test(src) ? 'CL' : 'INT'),
      article_hint: m[1].replace(/\s+/g, ' ').trim()
    });
    if (refs.length >= 6) break;
  }
  return refs;
}

function buildFallbackFromMarkdown(fullText, fileRef, fileNodeId, fileType = 'unknown', profile = ANALYSIS_PROFILE_DEFAULT) {
  const meta = getAnalysisProfileMeta(profile);
  const legalMode = isLegalProfile(profile);
  const now = new Date().toISOString();
  const lines = String(fullText || '').split(/\r?\n/);
  const actions = [];
  const violations = [];
  const segments = [];
  const actorsByFunction = {};

  const evidenceId = makeNodeId('evidence');
  const evidence = {
    node_id: evidenceId,
    type: 'Evidence',
    evidence_type: 'document',
    source: fileRef,
    timestamp: now,
    description: 'Heuristic extraction fallback from markdown legal report',
    _source_file_id: fileNodeId,
    _chunk_index: 0
  };

  function getActor(functionName) {
    if (!actorsByFunction[functionName]) {
      actorsByFunction[functionName] = {
        node_id: makeNodeId('actor'),
        type: 'ActorRole',
        function: functionName,
        context: null
      };
    }
    return actorsByFunction[functionName];
  }

  const candidates = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    const coded = line.match(/^[-*]\s+\*\*([A-Z0-9_-]+(?:::[a-z0-9_-]+)?)\*\*\s+[—-]\s+(.+)$/i);
    if (coded) {
      candidates.push({
        code: coded[1],
        description: coded[2].trim(),
        segmentText: line,
        position: i + 1
      });
      continue;
    }

    const heading = line.match(/^####\s+(.+)$/);
    if (heading && /violation|failure|collusion|defamation|obstruction|rights/i.test(heading[1])) {
      candidates.push({
        code: null,
        description: heading[1].trim(),
        segmentText: line,
        position: i + 1
      });
    }
  }

  const limited = candidates.slice(0, 120);
  let seq = 1;

  for (const c of limited) {
    const actionType = inferActionType(c.description);
    const actorFunction = inferActorFunction(`${c.code || ''} ${c.description}`);
    const actor = getActor(actorFunction);

    const segId = makeNodeId('segment');
    segments.push({
      node_id: segId,
      type: 'Segment',
      text: c.segmentText.slice(0, 500),
      position: c.position,
      evidence_node_id: evidenceId,
      speaker: actorFunction
    });

    const actionId = makeNodeId('action');
    actions.push({
      node_id: actionId,
      type: 'Action',
      action_type: actionType,
      description: `${c.code ? `${c.code}: ` : ''}${c.description}`.slice(0, 200),
      timestamp: now,
      sequence_index: seq,
      location: null,
      _performed_by_role_id: actor.node_id,
      _evidence_id: evidenceId,
      _segment_ids: [segId]
    });

    violations.push({
      node_id: makeNodeId('violation'),
      type: 'Violation',
      category: inferViolationCategory(c.description),
      description: `${c.code ? `${c.code}: ` : ''}${c.description}`.slice(0, 300),
      timestamp: now,
      severity: inferSeverity(c.description),
      confidence: 0.62,
      _law_references: extractLawReferences(c.description),
      _grounded_in_action_ids: [actionId],
      _supported_by_evidence_id: evidenceId,
      _llm_run_id: null
    });

    seq += 1;
  }

  if (actions.length === 0 && /art\.?\s*\d+|violation|defamation|collusion|obstruction/i.test(fullText)) {
    const actor = getActor('service_provider');
    const segId = makeNodeId('segment');
    segments.push({
      node_id: segId,
      type: 'Segment',
      text: lines.find(l => l.trim()).slice(0, 500),
      position: 1,
      evidence_node_id: evidenceId,
      speaker: 'service_provider'
    });

    const actionId = makeNodeId('action');
    actions.push({
      node_id: actionId,
      type: 'Action',
      action_type: 'policy_violation',
      description: 'Legal report indicates policy or procedural violations requiring structured review.',
      timestamp: now,
      sequence_index: 1,
      location: null,
      _performed_by_role_id: actor.node_id,
      _evidence_id: evidenceId,
      _segment_ids: [segId]
    });

    violations.push({
      node_id: makeNodeId('violation'),
      type: 'Violation',
      category: 'regulatory_non_compliance',
      description: 'Report-level evidence indicates potential regulatory non-compliance pending detailed verification.',
      timestamp: now,
      severity: 'medium',
      confidence: 0.51,
      _law_references: extractLawReferences(fullText.slice(0, 4000)),
      _grounded_in_action_ids: [actionId],
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
      document_type: /policy|procedure|manual/i.test(fileRef)
        ? 'policy'
        : /invoice|budget|financial/i.test(fileRef)
          ? 'financial_record'
          : /report|memorandum|analysis/i.test(fileRef)
            ? 'analysis'
            : 'other',
      primary_language: 'other',
      approximate_date: null,
      jurisdiction_hint: /brazil|br|cdc/i.test(fullText) ? 'BR' : /chile|cl/i.test(fullText) ? 'CL' : 'INT',
      subject_matter: legalMode
        ? 'Legal findings and potential violation catalog extracted from markdown report.'
        : `${meta.label} findings extracted from markdown report for operational review.`,
      key_entities: Array.from(new Set((fullText.match(/LATAM|DGAC|PDI|ICAO|Montreal|CDC|Carabineros/gi) || []).slice(0, 8)))
    }],
    _fallback_used: true,
    _fallback_reason: 'llm_empty_output_on_structured_markdown'
  };
}

// ─── Main Export ──────────────────────────────────────────────────────────────

/**
 * Run L5b extraction on a single file.
 * 
 * @param {Object} file    - Pipeline store file object (has file_ref, layers)
 * @param {Object} options - { apiKey, model, maxTokens, skipIfNoText }
 * @returns {Promise<Object>} Extraction result with ontology nodes + LLMRun record
 */
async function extractFile(file, options = {}) {
  const {
    apiKey,
    model,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT,
    skipIfNoText = true,
    maxRetries = 2,
    retryBaseMs = 700,
    timeoutMs = Number(process.env.LLM_TIMEOUT_MS || 120000)
  } = options;

  const profile = normalizeAnalysisProfile(analysisProfile);

  const fileRef  = file.file_ref;
  const preview  = file.layers?.L1?.preview || '';
  const wordCount = file.layers?.L1?.word_count || 0;
  const mimeType  = file.layers?.L0?.mime_type || 'application/octet-stream';
  const fileType  = file.layers?.L0?.extension || 'unknown';

  // Skip binary files and files with no extractable text
  if (skipIfNoText && wordCount < 10) {
    return {
      file_ref: fileRef,
      skipped:  true,
      reason:   'insufficient_text',
      nodes:    null
    };
  }

  // Get full text content from L1 (preview is truncated; use full if available)
  // In production, pipe the full text. Here we use what we have.
  const fullText = file.layers?.L1?.full_text || preview;
  const chunks   = chunkText(fullText);
  const fileSha256 = file.layers?.L0?.sha256 || null;

  const systemPrompt = buildSystemPrompt(profile);
  const allNodes     = [];
  const runIds       = [];
  const errors       = [];

  // Process each chunk
  for (let i = 0; i < chunks.length; i++) {
    const userMsg   = buildUserMessage(fileRef, fileType, chunks[i], i, chunks.length, profile);
    const runNodeId = makeNodeId('run');

    // LLMRun node — created before the call, regardless of outcome
    const llmRunNode = {
      node_id:        runNodeId,
      type:           'LLMRun',
      model:          model || 'deepseek-v4-pro',
      framework:      'discovery-pipeline-v1.0',
      timestamp:      new Date().toISOString(),
      prompt_version: PROMPT_VERSION,
      pipeline_stage: 'extraction',
      _file_ref:      fileRef,
      _chunk_index:   i
    };

    runIds.push(runNodeId);

    let rawResponse;
    try {
      rawResponse = await callAnthropicAPI(systemPrompt, userMsg, {
        apiKey,
        model,
        maxRetries,
        retryBaseMs,
        timeoutMs
      });
    } catch (err) {
      errors.push({ chunk: i, error: err.message });
      allNodes.push({ llm_run: llmRunNode, error: err.message });
      continue;
    }

    const parsed = parseExtractionResponse(rawResponse, fileRef);

    // Determine SourceFile node_id from L0 data
    const fileNodeId = file.layers?.L0?.file_node_id || `FILE_${crypto.createHash('md5').update(fileRef).digest('hex').slice(0, 8)}`;

    const assembled = assembleNodes(parsed, fileRef, fileNodeId, runNodeId, i);

    allNodes.push({
      llm_run:  llmRunNode,
      chunk:    i,
      parsed_ok: parsed.ok,
      ...assembled
    });
  }

  // Merge multi-chunk results — actions and violations accumulate across chunks
  const merged = mergeChunkResults(allNodes, fileRef);

  const fileNodeId = file.layers?.L0?.file_node_id || `FILE_${crypto.createHash('md5').update(fileRef).digest('hex').slice(0, 8)}`;
  let finalNodes = merged;
  if (errors.length === 0 && (merged.actions?.length || 0) === 0 && (merged.violations?.length || 0) === 0) {
    const fallbackNodes = buildFallbackFromMarkdown(fullText, fileRef, fileNodeId, fileType, profile);
    if ((fallbackNodes.actions?.length || 0) > 0 || (fallbackNodes.violations?.length || 0) > 0) {
      finalNodes = fallbackNodes;
    }
  }

  return {
    file_ref:   fileRef,
    _sha256:    fileSha256,
    skipped:    false,
    chunk_count: chunks.length,
    run_ids:    runIds,
    errors,
    nodes:      finalNodes
  };
}

/**
 * Merge extraction results across multiple chunks of the same file.
 * Renumbers sequence_indexes to be globally sequential.
 */
function mergeChunkResults(chunkResults, fileRef) {
  const merged = {
    evidence:   null,
    actions:    [],
    actors:     {},
    segments:   [],
    violations: [],
    llm_runs:   [],
    contexts:   []
  };

  let actionOffset = 0;

  for (const chunk of chunkResults) {
    if (chunk.llm_run) merged.llm_runs.push(chunk.llm_run);
    if (chunk.error)   continue;
    if (!chunk.actions) continue;

    // Use the first chunk's evidence node, or create one per chunk
    if (!merged.evidence && chunk.evidence) {
      merged.evidence = chunk.evidence;
    }

    // Offset sequence_indexes to avoid collision
    const maxIdx = chunk.actions.reduce((m, a) => Math.max(m, a.sequence_index || 0), 0);
    for (const action of chunk.actions) {
      action.sequence_index = (action.sequence_index || 0) + actionOffset;
      merged.actions.push(action);
    }
    actionOffset += maxIdx;

    merged.segments.push(...(chunk.segments || []));
    merged.violations.push(...(chunk.violations || []));

    // Merge actors by function (deduplicate)
    for (const actor of (chunk.actors || [])) {
      if (!merged.actors[actor.function]) {
        merged.actors[actor.function] = actor;
      }
    }

    if (chunk.context) merged.contexts.push(chunk.context);
  }

  merged.actors = Object.values(merged.actors);
  return merged;
}

/**
 * Run extraction over an array of files (batch).
 * Respects rate limits with configurable concurrency.
 * 
 * @param {Array} files       - Array of pipeline store file objects
 * @param {Object} options    - { apiKey, model, concurrency, onProgress }
 * @returns {Promise<Object>} Map of file_ref → extraction result
 */
async function extractBatch(files, options = {}) {
  const {
    apiKey,
    model,
    analysisProfile = ANALYSIS_PROFILE_DEFAULT,
    concurrency  = 3,   // parallel calls
    onProgress   = null,  // callback(done, total, file_ref)
    maxRetries   = 2,
    retryBaseMs  = 700,
    timeoutMs    = Number(process.env.LLM_TIMEOUT_MS || 120000)
  } = options;

  const results = {};
  let done = 0;

  // Process in batches of `concurrency`
  for (let i = 0; i < files.length; i += concurrency) {
    const batch = files.slice(i, i + concurrency);
    const tracked = batch.map((file) =>
      extractFile(file, { apiKey, model, analysisProfile, maxRetries, retryBaseMs, timeoutMs })
        .then((value) => {
          results[value.file_ref] = value;
        })
        .catch((error) => {
          results[`error_${file?.file_ref || i}`] = {
            skipped: false,
            error: error?.message || 'unknown error'
          };
        })
        .finally(() => {
          done += 1;
          if (onProgress) onProgress(done, files.length, file?.file_ref);
        })
    );

    await Promise.all(tracked);

    // Small delay between batches to respect rate limits
    if (i + concurrency < files.length) {
      await new Promise(r => setTimeout(r, 200));
    }
  }

  const stats = {
    total:        files.length,
    extracted:    0,
    skipped:      Object.values(results).filter(r => r.skipped).length,
    errors:       0,
    files_with_errors: 0,
    auth_errors:  0,
    total_actions:    0,
    total_violations: 0,
    total_runs:       0
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

  for (const r of Object.values(results)) {
    const topLevelErrors = r.error ? 1 : 0;
    const chunkErrors = Array.isArray(r.errors) ? r.errors.length : 0;
    const totalErrorsForFile = topLevelErrors + chunkErrors;

    if (totalErrorsForFile > 0) {
      stats.files_with_errors += 1;
      stats.errors += totalErrorsForFile;
    }

    if (r.error && isAuthFailure(r.error)) {
      stats.auth_errors += 1;
    }
    if (Array.isArray(r.errors)) {
      for (const err of r.errors) {
        if (isAuthFailure(err?.error)) {
          stats.auth_errors += 1;
        }
      }
    }

    if (r.nodes) {
      if ((r.nodes.actions?.length || 0) > 0 || (r.nodes.violations?.length || 0) > 0) {
        stats.extracted += 1;
      }
      stats.total_actions    += r.nodes.actions?.length || 0;
      stats.total_violations += r.nodes.violations?.length || 0;
      stats.total_runs       += r.run_ids?.length || 0;
    }
  }

  return { results, stats };
}

module.exports = {
  extractFile,
  extractBatch,
  makeNodeId,
  parseExtractionResponse,
  assembleNodes
};
