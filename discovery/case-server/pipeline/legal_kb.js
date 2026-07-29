/**
 * Pipeline — Legal Knowledge Base Connector
 *
 * Unified access layer for:
 *   Qdrant Memory Service — vector search for semantic law article lookup
 *   Neo4j Query API v2   — graph traversal for cross-case pattern detection
 *
 * Every function degrades gracefully when the KB is unavailable:
 * returns null, empty arrays, or empty objects — never throws.
 *
 * Requirements: ZERO npm dependencies. Uses HTTP REST APIs exclusively.
 *
 * Configuration via environment variables:
 *   KB_ENABLED               — "true" to enable (default: false)
 *   KB_QDRANT_URL            — Qdrant Memory Service REST endpoint (default: http://72.60.143.139:8079)
 *   KB_QDRANT_LAW_COLLECTION — Law articles collection (default: la8159_grounding)
 *   KB_QDRANT_TRANSCRIPT_COLLECTION — Transcript segments collection (default: la8159_transcripts)
 *   KB_NEO4J_QUERY_URL       — Neo4j Query API v2 URL (default: https://1e0e6845.databases.neo4j.io/db/1e0e6845/query/v2)
 *   KB_NEO4J_USER            — Neo4j username
 *   KB_NEO4J_PASSWORD        — Neo4j password
 */

'use strict';

// ─── Configuration ──────────────────────────────────────────────────────────

function readConfig(overrides = {}) {
  return {
    enabled:                coerceBool(overrides.enabled, process.env.KB_ENABLED, false),
    qdrantUrl:              overrides.qdrantUrl || process.env.KB_QDRANT_URL || 'http://72.60.143.139:8079',
    qdrantLawCollection:    overrides.qdrantCollection || process.env.KB_QDRANT_LAW_COLLECTION || 'la8159_grounding',
    qdrantTranscriptCollection: overrides.qdrantTranscriptCollection || process.env.KB_QDRANT_TRANSCRIPT_COLLECTION || 'la8159_transcripts',
    neo4jQueryUrl:          overrides.neo4jQueryUrl || process.env.KB_NEO4J_QUERY_URL || 'https://1e0e6845.databases.neo4j.io/db/1e0e6845/query/v2',
    neo4jUser:              overrides.neo4jUser || process.env.KB_NEO4J_USER || '1e0e6845',
    neo4jPassword:          overrides.neo4jPassword || process.env.KB_NEO4J_PASSWORD || '',
  };
}

function coerceBool(...values) {
  for (const v of values) {
    if (v === true || v === 'true' || v === '1' || v === 1) return true;
    if (v === false || v === 'false' || v === '0' || v === 0) return false;
  }
  return false;
}

// ─── HTTP Helpers ───────────────────────────────────────────────────────────

async function httpPost(url, body, auth = null, timeout = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    if (auth) {
      headers['Authorization'] = 'Basic ' + Buffer.from(auth.user + ':' + auth.pass).toString('base64');
    }
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function httpGet(url, timeout = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) return null;
    return await resp.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Qdrant Operations (via Memory Service REST API) ────────────────────────

/**
 * Search Qdrant for law articles semantically similar to the query.
 * Uses the Memory Service text-search endpoint — embeddings are generated
 * server-side with the same BERT model used at ingest time (768-dim).
 *
 * @param {string} query - Violation description or legal question
 * @param {string} jurisdiction - Jurisdiction filter (BR, CL, INT) or null for all
 * @param {number} topK - Number of results to return
 * @param {Object} overrides - Optional config overrides
 * @returns {Promise<Array>} Ranked articles with full text, or empty array
 */
async function searchLawArticles(query, jurisdiction = null, topK = 5, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled || !query) return [];

  // Fetch more than needed to allow for client-side jurisdiction filtering
  const fetchLimit = jurisdiction ? Math.min(topK * 4, 30) : Math.min(topK, 20);

  const result = await httpPost(`${config.qdrantUrl}/api/v1/qdrant/search`, {
    collection_name: config.qdrantLawCollection,
    query_text: query.slice(0, 2000),
    limit: fetchLimit,
    min_score: 0.25
  });

  if (!result || !result.results) return [];

  let mapped = result.results.map(r => ({
    eli_id:              r.payload?.eli_id || null,
    article_number:      r.payload?.article_number || null,
    article_text:        r.payload?.text || null,
    article_reference:   r.payload?.reference || null,
    framework_code:      r.payload?.framework_code || null,
    framework_name:      r.payload?.framework_name || null,
    jurisdiction:        r.payload?.jurisdiction || null,
    hierarchy_label:     r.payload?.hierarchy_label || null,
    norm_type:           r.payload?.norm_type || null,
    regulated_subject:   r.payload?.regulated_subject || null,
    score:               r.score || 0
  }));

  // Client-side jurisdiction filter (Qdrant server lacks payload indexes)
  if (jurisdiction) {
    mapped = mapped.filter(a => a.jurisdiction === jurisdiction);
  }

  return mapped.slice(0, topK);
}

/**
 * Search transcript segments semantically.
 *
 * @param {string} query - Context or violation description
 * @param {number} topK - Number of results
 * @param {Object} overrides
 * @returns {Promise<Array>} Relevant transcript segments
 */
async function searchTranscriptSegments(query, topK = 5, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled || !query) return [];

  const result = await httpPost(`${config.qdrantUrl}/api/v1/qdrant/search`, {
    collection_name: config.qdrantTranscriptCollection,
    query_text: query.slice(0, 2000),
    limit: Math.min(topK, 20),
    min_score: 0.25
  });

  if (!result || !result.results) return [];

  return result.results.map(r => ({
    transcript_id:       r.payload?.transcript_id || null,
    transcript_title:    r.payload?.transcript_title || null,
    speaker:             r.payload?.speaker || 'unknown',
    text:                r.payload?.text || '',
    start:               r.payload?.start || 0,
    end:                 r.payload?.end || 0,
    local_time:          r.payload?.local_time || null,
    location:            r.payload?.location || null,
    recording_datetime:  r.payload?.recording_datetime || null,
    score:               r.score || 0
  }));
}

/**
 * Look up a specific article by its ELI ID.
 * Uses Neo4j for exact match (unique constraint on LawArticle.eli_id).
 *
 * @param {string} eliId - e.g. "BR.CDC.T4.C2.Art.14"
 * @param {Object} overrides
 * @returns {Promise<Object|null>} Article with full text, or null
 */
async function lookupArticleByELI(eliId, overrides = {}) {
  if (!eliId) return null;

  const results = await neo4jRead(
    `MATCH (a:LawArticle {eli_id: $eliId})
     OPTIONAL MATCH (a)-[:BELONGS_TO]->(f:LegalFramework)
     RETURN a.eli_id AS eli_id, a.article_number AS article_number,
            a.text AS article_text, a.reference AS article_reference,
            a.framework_code AS framework_code, f.framework_name AS framework_name,
            a.jurisdiction AS jurisdiction, a.hierarchy_label AS hierarchy_label,
            a.norm_type AS norm_type, a.regulated_subject AS regulated_subject`,
    { eliId },
    overrides
  );

  if (!results || results.length === 0) return null;
  return results[0];
}

/**
 * Upsert a batch of law article vectors into Qdrant.
 * Uses the Memory Service structured ingest endpoint.
 *
 * @param {Array} articles - [{ eli_id, article_number, text, reference, framework_code, ... }]
 * @param {Object} overrides
 * @returns {Promise<{upserted: number, errors: number}>}
 */
async function upsertArticles(articles, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled) return { upserted: 0, errors: 0 };
  if (!articles || articles.length === 0) return { upserted: 0, errors: 0 };

  // Convert to format expected by structured ingest
  const items = articles.map(a => ({
    text: a.article_text || a.text || '',
    eli_id: a.eli_id || null,
    article_number: a.article_number || null,
    reference: a.article_reference || a.reference || null,
    framework_code: a.framework_code || null,
    framework_name: a.framework_name || null,
    jurisdiction: a.jurisdiction || null,
    verification_status: a.verification_status || 'pending'
  })).filter(item => item.text && item.eli_id);

  if (items.length === 0) return { upserted: 0, errors: 0 };

  const result = await httpPost(
    `${config.qdrantUrl}/api/v1/qdrant/collections/${config.qdrantLawCollection}/ingest/structured`,
    {
      collection_name: config.qdrantLawCollection,
      data_type: 'law',
      items,
      chunk_size: 1000,
      chunk_overlap: 100
    }
  );

  if (!result || result.status !== 'success') {
    return { upserted: 0, errors: items.length };
  }

  return { upserted: items.length, errors: 0 };
}

// ─── Neo4j Operations (via Query API v2 HTTP) ───────────────────────────────

function neo4jAuth(config) {
  if (!config.neo4jUser || !config.neo4jPassword) return null;
  return { user: config.neo4jUser, pass: config.neo4jPassword };
}

/**
 * Execute a Cypher query against Neo4j via the Query API v2.
 */
async function neo4jQuery(statement, params = {}, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled) return null;

  const auth = neo4jAuth(config);
  if (!auth) return null;

  const body = { statement };
  if (params && Object.keys(params).length > 0) {
    body.parameters = params;
  }

  return httpPost(config.neo4jQueryUrl, body, auth, 30000);
}

/**
 * Execute a read query against Neo4j.
 */
async function neo4jRead(cypher, params = {}, overrides = {}) {
  const result = await neo4jQuery(cypher, params, overrides);
  if (!result || !result.data) return [];

  const keys = result.data.fields || [];
  const rows = result.data.values || [];

  return rows.map(row => {
    const obj = {};
    keys.forEach((key, i) => {
      obj[key] = row[i];
    });
    return obj;
  });
}

/**
 * Execute a write query against Neo4j.
 */
async function neo4jWrite(cypher, params = {}, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled) return { ok: false, reason: 'kb_disabled' };

  const result = await neo4jQuery(cypher, params, overrides);
  if (!result) return { ok: false, reason: 'query_failed' };

  return { ok: true };
}

/**
 * Find articles frequently co-cited with the given article across cases.
 *
 * @param {string} eliId
 * @param {Object} overrides
 * @returns {Promise<Array>} Related articles with co-citation counts
 */
async function getRelatedArticles(eliId, overrides = {}) {
  if (!eliId) return [];

  return neo4jRead(
    `MATCH (a:LawArticle {eli_id: $eliId})<-[:VIOLATES]-(v:ViolationID)-[:VIOLATES]->(other:LawArticle)
     WHERE other.eli_id <> $eliId
     RETURN other.eli_id AS eli_id, other.article_number AS article_number,
            other.framework_code AS framework_code, count(v) AS co_citation_count
     ORDER BY co_citation_count DESC
     LIMIT 10`,
    { eliId },
    overrides
  );
}

/**
 * Find violation patterns similar to the given category/jurisdiction across all cases.
 *
 * @param {string} violationCategory
 * @param {string} jurisdiction
 * @param {Object} overrides
 * @returns {Promise<Array>} Similar violations
 */
async function getViolationPatterns(violationCategory, jurisdiction = null, overrides = {}) {
  let cypher = `
    MATCH (v:ViolationID)
    WHERE v.category = $category
  `;
  const params = { category: violationCategory };

  if (jurisdiction) {
    cypher += ` AND v.jurisdiction = $jurisdiction`;
    params.jurisdiction = jurisdiction;
  }

  cypher += `
    OPTIONAL MATCH (v)-[:VIOLATES]->(a:LawArticle)
    RETURN v.id AS violation_id, v.category AS category, v.severity AS severity,
           v.description AS description,
           collect(DISTINCT a.eli_id) AS article_ids
    LIMIT 20
  `;

  return neo4jRead(cypher, params, overrides);
}

/**
 * Persist a case graph (violations + article links) to Neo4j.
 *
 * @param {Object} caseGraph - The normalized case graph from L6
 * @param {Object} overrides
 * @returns {Promise<{ok: boolean, persisted_violations: number, persisted_articles: number}>}
 */
async function persistCaseGraph(caseGraph, overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled) {
    return { ok: false, reason: 'kb_disabled', persisted_violations: 0, persisted_articles: 0 };
  }

  const caseId = caseGraph.nodes?.case?.[0]?.node_id || 'unknown';
  const jurisdiction = caseGraph.nodes?.case?.[0]?.jurisdiction || 'unknown';
  let persistedViolations = 0;
  let persistedArticles = 0;

  // Persist all violations in one batch
  const violations = caseGraph.nodes?.violations || [];
  for (const v of violations) {
    const result = await neo4jWrite(
      `MERGE (viol:ViolationID {id: $id})
       SET viol.category = $category,
           viol.severity = $severity,
           viol.description = $description,
           viol.confidence = $confidence,
           viol.case_id = $caseId,
           viol.jurisdiction = $jurisdiction,
           viol.updated_at = datetime()`,
      {
        id: v.node_id,
        category: v.category || 'other',
        severity: v.severity || 'medium',
        description: (v.description || '').slice(0, 500),
        confidence: v.confidence || 0,
        caseId,
        jurisdiction
      },
      overrides
    );

    if (result.ok) {
      persistedViolations++;

      // Create VIOLATES relationships to articles
      for (const articleId of (v._violates_article_ids || [])) {
        const relResult = await neo4jWrite(
          `MATCH (viol:ViolationID {id: $violId})
           MERGE (a:LawArticle {eli_id: $eliId})
           MERGE (viol)-[:VIOLATES]->(a)`,
          { violId: v.node_id, eliId: articleId },
          overrides
        );
        if (relResult.ok) persistedArticles++;
      }
    }
  }

  // Persist legal framework nodes
  for (const fw of (caseGraph.nodes?.legal_frameworks || [])) {
    await neo4jWrite(
      `MERGE (f:LegalFramework {framework_code: $code})
       SET f.framework_name = $name, f.jurisdiction = $jurisdiction`,
      { code: fw.node_id || fw.framework_code, name: fw.name || '', jurisdiction: fw.jurisdiction || '' },
      overrides
    );
  }

  return { ok: true, persisted_violations: persistedViolations, persisted_articles: persistedArticles };
}

// ─── LA8159 Agent / Source Ingestion ───────────────────────────────────────

/**
 * Parse a single LA8159 agent .md file and extract article entries from its table.
 *
 * Expected table format (from agent definitions like br-cdc.agent.md):
 *   | Art. N | Topic | Verification | Notes |
 *
 * @param {string} filePath - Path to agent .md file
 * @returns {Array} Extracted article objects
 */
function parseAgentFile(filePath) {
  const fs = require('fs');
  const path = require('path');

  let content;
  try {
    content = fs.readFileSync(filePath, 'utf-8');
  } catch (_) {
    return [];
  }

  const articles = [];

  // Extract agent identity from frontmatter or header
  const agentIdMatch = content.match(/\*\*Agent ID:\*\*\s*`?(\w+)`?/);
  const jurisdictionMatch = content.match(/\*\*Jurisdiction:\*\*\s*(.+)/);
  const instrumentMatch = content.match(/\*\*Primary instrument:\*\*\s*(.+)/);

  const agentId = agentIdMatch?.[1] || path.basename(filePath, '.agent.md').toUpperCase();
  const jurisdiction = (jurisdictionMatch?.[1] || '').trim();
  const instrument = (instrumentMatch?.[1] || '').trim();

  const jurCode = /brazil/i.test(jurisdiction) ? 'BR'
    : /chile/i.test(jurisdiction) ? 'CL'
    : /international/i.test(jurisdiction) ? 'INT'
    : /eu/i.test(jurisdiction) ? 'EU'
    : 'other';

  const tableRegex = /\|\s*(?:Art\.?\s*(\d+(?:\s*[A-Za-z]+)?(?:\s*[§º°])?(?:\s*[IVX]+)?(?:[^|]*?)))\s*\|\s*([^|]+?)\s*\|[^|]*\|([^|]*?)\s*\|/g;

  let match;
  while ((match = tableRegex.exec(content)) !== null) {
    const articleNum = match[1].trim();
    const topic = match[2].trim();
    const notes = match[3].trim();

    if (/^-{2,}$/.test(articleNum) || articleNum === 'Article') continue;

    const articleText = topic
      ? `${topic}${notes && notes !== topic ? ' — ' + notes : ''}`
      : notes || topic || '';

    const eliId = `${jurCode}.${agentId}.Art.${articleNum.replace(/[°º§]/g, '').replace(/\s+/g, '')}`;

    articles.push({
      eli_id: eliId,
      article_number: articleNum,
      article_text: articleText.slice(0, 2000),
      article_reference: `${agentId}, Art. ${articleNum}`,
      framework_code: agentId,
      framework_name: instrument || agentId,
      jurisdiction: jurCode,
      verification_status: /✅|confirmed/i.test(notes) ? 'verified'
        : /⏳|pending/i.test(notes) ? 'pending'
        : 'unverified',
      source_file: path.basename(filePath)
    });
  }

  return articles;
}

/**
 * Ingest all LA8159 agent .md files into the knowledge base.
 *
 * @param {string} agentsDir - Path to directory containing agent .md files
 * @param {Object} overrides
 * @returns {Promise<{parsed: number, upserted: number, errors: number}>}
 */
async function ingestAgentKnowledge(agentsDir, overrides = {}) {
  const fs = require('fs');
  const path = require('path');

  let files;
  try {
    files = fs.readdirSync(agentsDir).filter(f => f.endsWith('.agent.md'));
  } catch (_) {
    return { parsed: 0, upserted: 0, errors: 0 };
  }

  const allArticles = [];
  for (const file of files) {
    const articles = parseAgentFile(path.join(agentsDir, file));
    allArticles.push(...articles);
  }

  if (allArticles.length === 0) {
    return { parsed: 0, upserted: 0, errors: 0 };
  }

  // Upsert to Qdrant
  const { upserted, errors } = await upsertArticles(allArticles, overrides);

  // Also persist to Neo4j
  for (const article of allArticles) {
    await neo4jWrite(
      `MERGE (a:LawArticle {eli_id: $eliId})
       SET a.article_number = $articleNumber,
           a.text = $text,
           a.framework_code = $frameworkCode,
           a.jurisdiction = $jurisdiction,
           a.verification_status = $verificationStatus
       MERGE (f:LegalFramework {framework_code: $frameworkCode})
       ON CREATE SET f.framework_name = $frameworkName, f.jurisdiction = $jurisdiction
       MERGE (a)-[:BELONGS_TO]->(f)`,
      {
        eliId: article.eli_id,
        articleNumber: article.article_number,
        text: article.article_text.slice(0, 2000),
        frameworkCode: article.framework_code,
        frameworkName: article.framework_name,
        jurisdiction: article.jurisdiction,
        verificationStatus: article.verification_status
      },
      overrides
    );
  }

  return { parsed: allArticles.length, upserted, errors };
}

// ─── Health Check ───────────────────────────────────────────────────────────

/**
 * Check if the knowledge base is available.
 *
 * @param {Object} overrides
 * @returns {Promise<{qdrant: boolean, neo4j: boolean, enabled: boolean}>}
 */
async function isAvailable(overrides = {}) {
  const config = readConfig(overrides);
  if (!config.enabled) return { qdrant: false, neo4j: false, enabled: false };

  const [qdrantOk, neo4jOk] = await Promise.all([
    checkQdrant(config),
    checkNeo4j(config)
  ]);

  return { qdrant: qdrantOk, neo4j: neo4jOk, enabled: config.enabled };
}

async function checkQdrant(config) {
  const result = await httpGet(`${config.qdrantUrl}/api/v1/qdrant/collections/${config.qdrantLawCollection}/info`);
  return !!(result && result.name);
}

async function checkNeo4j(config) {
  const result = await neo4jQuery('RETURN 1 AS ok', {}, { ...readConfig(), ...config });
  return !!(result && result.data);
}

// ─── Exports ────────────────────────────────────────────────────────────────

module.exports = {
  // Configuration
  readConfig,

  // Qdrant (Memory Service REST API)
  searchLawArticles,
  searchTranscriptSegments,
  lookupArticleByELI,
  upsertArticles,

  // Neo4j (Query API v2 HTTP)
  getRelatedArticles,
  getViolationPatterns,
  persistCaseGraph,
  neo4jRead,
  neo4jWrite,

  // Ingestion
  parseAgentFile,
  ingestAgentKnowledge,

  // Health
  isAvailable
};
