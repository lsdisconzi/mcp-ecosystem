/**
 * Pipeline Layer 5b — LLM Extraction Prompt Template
 * Version: legal-extraction-v1.0
 * Ontology: v2.4
 * 
 * This prompt drives the extraction LLM to produce structured ontology nodes
 * from raw file content. Every field maps to a v2.4 node specification.
 * 
 * IDENTITY ISOLATION IS ENFORCED: no personal names, IDs, or identifying
 * information may appear in any extracted node. Actors are functional roles only.
 */

'use strict';

const {
  ANALYSIS_PROFILE_DEFAULT,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile
} = require('./analysis_profile');

const PROMPT_VERSION = 'profile-aware-extraction-v2.0';

/**
 * Build the system prompt for ontology-compliant extraction.
 * This is fixed per version — changes require a version bump.
 */
function buildSystemPrompt(profile = ANALYSIS_PROFILE_DEFAULT) {
  const normalizedProfile = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalizedProfile);
  const legalMode = isLegalProfile(normalizedProfile);

  const actionTypes = [
    'communication_failure', 'service_denial', 'procedure_violation',
    'delay', 'physical_interaction', 'documentation_failure',
    'safety_violation', 'policy_violation', 'process_breakdown',
    'compliance_issue', 'operational_update', 'customer_escalation',
    'financial_irregularity', 'hr_issue', 'it_incident',
    'decision_event', 'other'
  ];

  const findingCategories = [
    'service_failure', 'communication_failure', 'safety_violation',
    'documentation_failure', 'discrimination', 'delay_compensation',
    'consumer_rights', 'regulatory_non_compliance', 'operational_risk',
    'process_gap', 'compliance_gap', 'financial_risk',
    'hr_risk', 'it_risk', 'governance_gap', 'other'
  ];

  const documentTypes = [
    'complaint', 'report', 'contract', 'transcript',
    'correspondence', 'regulation', 'evidence', 'analysis',
    'decision', 'policy', 'financial_record', 'hr_record',
    'it_log', 'manual', 'other'
  ];

  return `You are an operational intelligence extraction engine operating under
Ontology v2.4.

Active profile: ${meta.label}
Profile scope: ${meta.scope}

Your role is EXTRACTION ONLY - describe what exists in the document.
Never invent facts. Never conclude guilt, liability, intent, or legal outcome.

## CRITICAL: IDENTITY ISOLATION
You MUST NOT include any personal names, employee IDs, passport numbers, 
or any information that could identify a natural person. Represent all 
actors by their functional role ONLY using these values:
  service_provider | regulator | operator | crew | controller |
  passenger | witness | police_officer | airline_staff | 
  security_personnel | ground_handler | manager | customer | 
  auditor | system_operator

## YOUR TASK
Extract from the document content provided and return ONLY a valid JSON 
object conforming to the schema below. No preamble. No commentary. 
No markdown fences. Pure JSON.

IMPORTANT: The field name "violations" is kept for backward compatibility.
For non-legal profiles, treat it as "${meta.finding_plural}" with the same schema.

## OUTPUT SCHEMA

{
  "actions": [
    {
      "action_type": string,       // REQUIRED. One of: ${actionTypes.join(' | ')}
      "description": string,       // REQUIRED. Factual, no legal conclusion. Max 200 chars.
      "timestamp_iso": string|null, // ISO 8601 UTC if date/time is stated. null if unknown.
      "sequence_index": integer,    // 1-based order of occurrence in document
      "location": string|null,      // Airport code, city, or location description. null if unknown.
      "actor_function": string,     // Functional role from vocabulary above
      "segments": [                 // Exact verbatim text excerpts supporting this action
        {
          "text": string,           // REQUIRED. Exact quote from document. Max 500 chars.
          "position": integer,      // 1-based position (paragraph/line number approx)
          "speaker": string|null    // Functional role of speaker if identifiable
        }
      ]
    }
  ],
  "violations": [
    {
      "category": string,           // REQUIRED. One of: ${findingCategories.join(' | ')}
      "description": string,        // REQUIRED. ${legalMode ? 'What rule may have been broken.' : 'What risk/gap/issue is present.'} Max 300 chars.
      "severity": string,           // REQUIRED. One of: low | medium | high
      "confidence": float,          // REQUIRED. 0.0-1.0.
      "action_indexes": [integer],  // Which actions (by sequence_index) ground this finding
      "law_references": [           // Laws or regulations referenced or implied
        {
          "raw_text": string,       // Exact text as it appears in document
          "framework_hint": string, // e.g. "CDC", "CBA", "ANAC", "Lei 7.565", "Res. 400"
          "jurisdiction": string,   // "BR" | "CL" | "INT" | "EU" | "AR" | "US" | "other"
          "article_hint": string|null // Article number if mentioned (e.g. "Art. 14", "§3")
        }
      ]
    }
  ],
  "document_context": {
    "document_type": string,        // One of: ${documentTypes.join(' | ')}
    "primary_language": string,     // BCP-47 code: "pt-BR" | "es" | "en" | "fr" | "other"
    "approximate_date": string|null,// ISO 8601 date if determinable, else null
    "jurisdiction_hint": string,    // Primary jurisdiction evident from content
    "subject_matter": string,       // 1-sentence summary of what this document is about
    "key_entities": [string]        // Organizations, airports, flight numbers (NOT personal names)
  }
}

## RULES
1. If no actions are found, return "actions": []
2. If no findings are apparent, return "violations": []
3. Confidence below 0.4 = do not include the finding
4. Timestamps MUST be ISO 8601 UTC (ending Z). Approximate dates: use T00:00:00Z
5. sequence_index must be unique and sequential starting from 1
6. segments.text must be exact verbatim quotes — never paraphrased
7. Descriptions must be factual observations, never conclusions about guilt
8. ZERO personal names anywhere in any field`;
}

/**
 * Build the user message for a specific file chunk.
 * @param {string} fileName   - Relative file path (for context only)
 * @param {string} fileType   - MIME type or extension
 * @param {string} content    - Text content to analyze (already chunked if needed)
 * @param {number} chunkIndex - 0-based chunk index (0 = first/only)
 * @param {number} totalChunks - Total number of chunks for this file
 */
function buildUserMessage(fileName, fileType, content, chunkIndex = 0, totalChunks = 1, profile = ANALYSIS_PROFILE_DEFAULT) {
  const normalizedProfile = normalizeAnalysisProfile(profile);
  const meta = getAnalysisProfileMeta(normalizedProfile);
  const chunkNote = totalChunks > 1
    ? `\n[DOCUMENT CHUNK ${chunkIndex + 1} of ${totalChunks} — extract only what appears in this chunk]`
    : '';

  return `FILE: ${fileName}
TYPE: ${fileType}${chunkNote}
PROFILE: ${meta.label}
PROFILE_SCOPE: ${meta.scope}

DOCUMENT CONTENT:
---
${content}
---

Extract all actions, findings (in "violations" field), and context from the above content 
following the schema exactly. Return only valid JSON.`;
}

/**
 * Chunk long text content into overlapping segments.
 * Overlap ensures entities at chunk boundaries are not missed.
 * 
 * @param {string} text
 * @param {number} maxWords    - Target words per chunk
 * @param {number} overlapWords - Words to overlap between chunks
 * @returns {string[]} Array of text chunks
 */
function chunkText(text, maxWords = 1800, overlapWords = 150) {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length <= maxWords) return [text];

  const chunks = [];
  let start = 0;
  while (start < words.length) {
    const end = Math.min(start + maxWords, words.length);
    chunks.push(words.slice(start, end).join(' '));
    if (end === words.length) break;
    start = end - overlapWords;
  }
  return chunks;
}

// ─── Augmented Extraction (with KB context) ─────────────────────────────────

/**
 * Format KB article results into a compact string for injection into the prompt.
 *
 * @param {Array} kbResults - From searchLawArticles in legal_kb.js
 * @returns {string} Formatted law context or empty string
 */
function formatKbContext(kbResults) {
  if (!kbResults || kbResults.length === 0) return '';

  const lines = ['## APPLICABLE LEGAL FRAMEWORK'];
  lines.push('The following law articles are relevant to the jurisdiction and subject matter.');
  lines.push('Use them to better identify violations and categorize findings:\n');

  for (const article of kbResults) {
    const ref = article.article_reference || article.eli_id || 'Unknown Article';
    const text = article.article_text
      ? article.article_text.slice(0, 400)
      : 'Text not available in knowledge base.';
    const jur = article.jurisdiction ? ` [${article.jurisdiction}]` : '';
    lines.push(`**${ref}**${jur}: ${text}`);
  }

  lines.push('\nWhen these articles are relevant to a finding, include them in the `law_references` field.');
  return lines.join('\n');
}

/**
 * Build an augmented system prompt that includes applicable law articles.
 *
 * @param {Object} profile - Analysis profile
 * @param {Array} kbResults - KB search results for context
 * @returns {string} Augmented system prompt
 */
function buildAugmentedSystemPrompt(profile = ANALYSIS_PROFILE_DEFAULT, kbResults = null) {
  const basePrompt = buildSystemPrompt(profile);
  const kbSection = formatKbContext(kbResults);

  if (!kbSection) return basePrompt;

  return `${basePrompt}\n\n${kbSection}`;
}

/**
 * Build an augmented user message that includes KB context.
 * Extends the standard user message with relevant law articles for grounded extraction.
 *
 * @param {string} fileName   - Relative file path
 * @param {string} fileType   - MIME type or extension
 * @param {string} content    - Text content to analyze
 * @param {number} chunkIndex - 0-based chunk index
 * @param {number} totalChunks - Total chunks for this file
 * @param {Object} profile    - Analysis profile
 * @param {Array} kbResults   - KB search results from legal_kb.searchLawArticles
 * @returns {string} Augmented user message
 */
function buildAugmentedUserMessage(fileName, fileType, content, chunkIndex = 0, totalChunks = 1, profile = ANALYSIS_PROFILE_DEFAULT, kbResults = null) {
  const baseMessage = buildUserMessage(fileName, fileType, content, chunkIndex, totalChunks, profile);
  const kbSection = formatKbContext(kbResults);

  if (!kbSection) return baseMessage;

  return `${baseMessage}\n\n${kbSection}`;
}

module.exports = {
  PROMPT_VERSION,
  buildSystemPrompt,
  buildUserMessage,
  buildAugmentedSystemPrompt,
  buildAugmentedUserMessage,
  formatKbContext,
  chunkText
};
