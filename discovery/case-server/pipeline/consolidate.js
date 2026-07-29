/**
 * Case Consolidation Module — LA8159 Trial Directory Builder
 *
 * Reads validated data from /Users/dev/LA8159-incident/ and assembles
 * a consolidated, trial-ready directory structure.
 *
 * Single Responsibility: gather, organize, cross-reference.
 * Does NOT re-extract or re-verify — data is already validated.
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const crypto = require('crypto');

const LA8159_ROOT = '/Users/dev/LA8159-incident';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function readJSON(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function readText(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch (e) {
    return null;
  }
}

function writeJSON(filePath, data) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

function writeText(filePath, text) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(filePath, text);
}

function copyFile(src, dest) {
  if (!fs.existsSync(src)) return false;
  const dir = path.dirname(dest);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.copyFileSync(src, dest);
  return true;
}

function copyDir(src, dest) {
  if (!fs.existsSync(src)) return 0;
  let count = 0;
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      count += copyDir(srcPath, destPath);
    } else {
      if (copyFile(srcPath, destPath)) count++;
    }
  }
  return count;
}

function sha256short(str) {
  return crypto.createHash('sha256').update(str).digest('hex').slice(0, 12);
}

// ─── Violation Loader ─────────────────────────────────────────────────────────

function loadViolations() {
  const violations = { BR: [], CL: [], INT: [] };
  const byId = {};

  for (const jur of ['BR', 'CL', 'INT']) {
    const dir = path.join(LA8159_ROOT, '10_violations_json', 'validated', jur);
    if (!fs.existsSync(dir)) continue;

    const files = fs.readdirSync(dir).filter(f => f.endsWith('.json'));
    for (const file of files) {
      const data = readJSON(path.join(dir, file));
      if (!data || !data.violation_id) continue;

      violations[jur].push(data);
      byId[data.violation_id] = data;
    }
  }

  return { violations, byId };
}

// ─── Law Loader ───────────────────────────────────────────────────────────────

function loadLawArticles() {
  const articles = { BR: {}, CL: {}, INT: {} };
  const byELI = {};

  for (const jur of ['BR', 'CL', 'INT']) {
    const dir = path.join(LA8159_ROOT, '09_LAW', jur, 'json');
    if (!fs.existsSync(dir)) continue;

    const files = fs.readdirSync(dir).filter(f => f.endsWith('.json'));
    for (const file of files) {
      const data = readJSON(path.join(dir, file));
      if (!data || !Array.isArray(data)) continue;

      const framework = file.replace('.json', '');
      articles[jur][framework] = data;

      for (const article of data) {
        if (article.eli_id) {
          byELI[article.eli_id] = article;
        }
      }
    }
  }

  return { articles, byELI };
}

// ─── Agent Loader ──────────────────────────────────────────────────────────────

function loadAgents() {
  const agents = { BR: [], CL: [], INT: [], meta: [] };

  for (const category of ['BR', 'CL', 'INT', 'meta']) {
    const dir = path.join(LA8159_ROOT, '0_agents', category);
    if (!fs.existsSync(dir)) continue;

    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const agentDir = path.join(dir, entry.name);
      const agentMdPath = path.join(agentDir, 'agent.md');
      const agentMd = readText(agentMdPath);

      if (agentMd) {
        agents[category].push({
          id: entry.name,
          dir: agentDir,
          spec: agentMd
        });
      }
    }
  }

  return agents;
}

// ─── Evidence Loader ───────────────────────────────────────────────────────────

function loadEvidenceIndex() {
  const evidenceDir = path.join(LA8159_ROOT, '03_EVIDENCE');
  if (!fs.existsSync(evidenceDir)) return [];

  const items = [];
  function walk(dir, prefix) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      const relPath = path.relative(evidenceDir, fullPath);
      if (entry.isDirectory()) {
        walk(fullPath, prefix);
      } else if (!entry.name.startsWith('.')) {
        const stat = fs.statSync(fullPath);
        items.push({
          path: relPath,
          size: stat.size,
          modified: stat.mtime.toISOString()
        });
      }
    }
  }
  walk(evidenceDir, '');
  return items;
}

// ─── Case Graph Builder ───────────────────────────────────────────────────────

function buildCaseGraph(violations, lawArticles, agentMapping) {
  const nodes = {
    case: {
      id: 'CASE_LA8159',
      type: 'Case',
      title: 'LA8159 — LATAM Airlines Cross-Jurisdictional Violations',
      description: 'Multi-jurisdictional case involving LATAM Airlines\' conduct toward passenger Leandro Disconzi across Brazil (GRU, April 2024) and Chile (Santiago/STG, July 2024)',
      jurisdictions: ['BR', 'CL', 'INT'],
      date_range: {
        start: '2024-04-04',
        end: '2024-07-06'
      }
    },
    violations: [],
    actions: [],
    actors: [],
    lawRefs: [],
    evidenceRefs: []
  };

  const actorSet = new Set();
  const lawRefSet = new Set();

  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      // Violation node
      const vNode = {
        id: v.violation_id,
        type: 'Violation',
        title: v.title || v.violation_id,
        severity: v.severity || 'UNKNOWN',
        confidence: v.confidence || 0,
        jurisdiction: jur,
        status: v.status || 'validated',
        date: v.incident?.date || null,
        location: v.incident?.location || null,
        summary: v.facts?.summary || '',
        actors: v.facts?.actors || [],
        segments: v.facts?.segments || [],
        legal_basis: v.legal_basis || {},
        enrichment_level: v.enrichment_level || 'basic',
        agents: agentMapping?.[v.violation_id] || { primary: [], supporting: [] }
      };
      nodes.violations.push(vNode);

      // Collect actors
      for (const actor of (v.facts?.actors || [])) {
        if (!actorSet.has(actor)) {
          actorSet.add(actor);
          nodes.actors.push({ name: actor, id: `ACTOR_${sha256short(actor)}` });
        }
      }

      // Collect segments as actions
      for (const seg of (v.facts?.segments || [])) {
        nodes.actions.push({
          id: seg.segment_id || `SEG_${sha256short(JSON.stringify(seg))}`,
          timeStart: seg.timeStart || null,
          timeEnd: seg.timeEnd || null,
          speaker: seg.speaker || 'Unknown',
          text: seg.text || '',
          violation_id: v.violation_id
        });
      }

      // Collect law references
      const frameworks = v.legal_basis?.frameworks || [];
      for (const fw of frameworks) {
        const articles = fw.articles || [];
        for (const art of articles) {
          const refKey = art.article_id;
          if (!lawRefSet.has(refKey)) {
            lawRefSet.add(refKey);
            nodes.lawRefs.push({
              id: refKey,
              framework: fw.framework_code,
              article_text: art.article_text || '',
              duty_bearer: art.duty_bearer || '',
              norm_type: art.norm_type || '',
              applicability: art.applicability || 'direct'
            });
          }
        }
      }
    }
  }

  // Relationships / edges
  const edges = [];
  for (const v of nodes.violations) {
    for (const art of (v.legal_basis?.frameworks || [])) {
      for (const a of (art.articles || [])) {
        edges.push({
          source: v.id,
          target: a.article_id,
          type: 'VIOLATES'
        });
      }
    }
    for (const seg of (v.facts?.segments || [])) {
      edges.push({
        source: v.id,
        target: seg.segment_id,
        type: 'CONTAINS_SEGMENT'
      });
    }
  }

  return {
    ontology_version: '2.4',
    generated_at: new Date().toISOString(),
    nodes,
    edges,
    stats: {
      total_violations: nodes.violations.length,
      total_actions: nodes.actions.length,
      total_actors: nodes.actors.length,
      total_law_refs: nodes.lawRefs.length,
      total_edges: edges.length,
      by_jurisdiction: {
        BR: violations.BR.length,
        CL: violations.CL.length,
        INT: violations.INT.length
      }
    }
  };
}

// ─── Master Index Builder ─────────────────────────────────────────────────────

function buildMasterIndex(violations, lawArticles, agents, evidenceItems, mapping, caseGraph) {
  const index = {
    generated_at: new Date().toISOString(),
    case_id: 'LA8159',
    summary: {
      total_violations: caseGraph.stats.total_violations,
      total_law_articles: Object.values(lawArticles.byELI).length,
      total_agents: agents.BR.length + agents.CL.length + agents.INT.length + agents.meta.length,
      total_evidence_items: evidenceItems.length,
      jurisdictions: ['BR', 'CL', 'INT']
    },
    violations: {},
    law_articles: {},
    agents: {},
    cross_references: mapping || {}
  };

  // Index violations
  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      index.violations[v.violation_id] = {
        title: v.title,
        severity: v.severity,
        status: v.status,
        jurisdiction: jur,
        date: v.incident?.date,
        location: v.incident?.location,
        articles: (v.legal_basis?.frameworks || []).flatMap(f =>
          (f.articles || []).map(a => a.article_id)
        ),
        agents: mapping?.[v.violation_id] || null,
        actors: v.facts?.actors || [],
        enrichment: v.enrichment_level
      };
    }
  }

  // Index law articles
  for (const [eli, article] of Object.entries(lawArticles.byELI)) {
    index.law_articles[eli] = {
      jurisdiction: article.jurisdiction,
      framework: article.framework_code,
      article_number: article.article_number,
      text_preview: (article.text || '').slice(0, 200),
      norm_type: article.norm_type,
      theme: article.theme
    };
  }

  // Index agents
  for (const category of ['BR', 'CL', 'INT', 'meta']) {
    for (const agent of agents[category]) {
      index.agents[agent.id] = {
        category,
        dir: agent.dir
      };
    }
  }

  return index;
}

// ─── Cross-Reference Map Builder ──────────────────────────────────────────────

function buildCrossReferenceMap(violations) {
  const map = {
    by_jurisdiction: { BR: [], CL: [], INT: [] },
    by_severity: { CRITICAL: [], HIGH: [], MEDIUM: [], LOW: [], UNKNOWN: [] },
    by_date: {},
    violation_links: []
  };

  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      map.by_jurisdiction[jur].push(v.violation_id);
      const sev = v.severity || 'UNKNOWN';
      if (!map.by_severity[sev]) map.by_severity[sev] = [];
      map.by_severity[sev].push(v.violation_id);

      const date = v.incident?.date;
      if (date) {
        if (!map.by_date[date]) map.by_date[date] = [];
        map.by_date[date].push(v.violation_id);
      }
    }
  }

  // Cross-jurisdictional links (violations that reference frameworks from other jurisdictions)
  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      const frameworks = v.legal_basis?.frameworks || [];
      for (const fw of frameworks) {
        const fwJur = fw.primary_jurisdiction || jur;
        if (fwJur !== jur) {
          map.violation_links.push({
            violation: v.violation_id,
            home_jurisdiction: jur,
            references_jurisdiction: fwJur,
            framework: fw.framework_code
          });
        }
      }
    }
  }

  return map;
}

// ─── Agent-Violation Map Builder ──────────────────────────────────────────────

function buildAgentViolationMap(mapping) {
  const agentMap = {};

  if (!mapping) return agentMap;

  for (const jur of ['BR', 'CL', 'INT']) {
    for (const [violationId, agentRefs] of Object.entries(mapping[jur] || {})) {
      for (const agentId of (agentRefs.primary || [])) {
        if (!agentMap[agentId]) agentMap[agentId] = { primary: [], supporting: [] };
        agentMap[agentId].primary.push(violationId);
      }
      for (const agentId of (agentRefs.supporting || [])) {
        if (!agentMap[agentId]) agentMap[agentId] = { primary: [], supporting: [] };
        agentMap[agentId].supporting.push(violationId);
      }
    }
  }

  // Meta agents
  const metaSection = mapping.META || {};
  for (const [agentId, metaData] of Object.entries(metaSection)) {
    if (agentId.startsWith('_')) continue;
    if (!agentMap[agentId]) agentMap[agentId] = { primary: [], supporting: [], meta: metaData };
  }

  return agentMap;
}

// ─── CASE_SUMMARY.md Generator ────────────────────────────────────────────────

function generateCaseSummary(caseGraph, crossRefMap, agentViolationMap, agents) {
  const stats = caseGraph.stats;
  const criticalCount = (crossRefMap.by_severity.CRITICAL || []).length;
  const highCount = (crossRefMap.by_severity.HIGH || []).length;

  const lines = [
    `# LA8159 — Consolidated Case Summary`,
    ``,
    `**Generated:** ${new Date().toISOString()}`,
    `**Ontology:** v${caseGraph.ontology_version}`,
    ``,
    `## Overview`,
    ``,
    `The LA8159 case involves LATAM Airlines\' conduct toward passenger Leandro Disconzi across two incidents:`,
    ``,
    `1. **April 4, 2024 (GRU, Brazil)** — Staff misconduct and boarding dispute at Guarulhos Airport, revealing LATAM\'s institutional culture of indifference toward passenger complaints.`,
    `2. **July 5, 2024 (Santiago, Chile → GRU, Brazil)** — False accusation, forcible removal, and lifetime ban imposed against the same passenger, spanning multiple jurisdictions.`,
    ``,
    `## Key Statistics`,
    ``,
    `| Metric | Count |`,
    `|--------|-------|`,
    `| Total Violations | ${stats.total_violations} |`,
    `| CRITICAL Severity | ${criticalCount} |`,
    `| HIGH Severity | ${highCount} |`,
    `| Brazil (BR) Violations | ${stats.by_jurisdiction.BR} |`,
    `| Chile (CL) Violations | ${stats.by_jurisdiction.CL} |`,
    `| International (INT) Violations | ${stats.by_jurisdiction.INT} |`,
    `| Law References | ${stats.total_law_refs} |`,
    `| Actors Identified | ${stats.total_actors} |`,
    `| Action Segments | ${stats.total_actions} |`,
    ``,
    `## Jurisdictions Involved`,
    ``,
    `- **Brazil** — Consumer protection (CDC), Aviation (CBA, ANAC R400), Criminal (CP), Civil (CC), Constitutional (CF88), Administrative (Lei 9.784)`,
    `- **Chile** — Consumer protection (LPDC), Aviation (CACH), Criminal (CPCL), Constitutional, DGAC (L16752), Transparency (L20285)`,
    `- **International** — ICAO Annexes (9, 17, 6, 13), Montreal Convention 1999, ACHR, VCCR, IATA General Conditions, Chicago Convention, UNGCP`,
    ``,
    `## Timeline`,
    ``,
    `| Date | Event |`,
    `|------|-------|`,
    `| 2024-04-04 | GRU boarding dispute with LATAM staff Marinho; precursor incident |`,
    `| 2024-07-05 | Santiago (STG) incident — false accusation, forcible removal, lifetime ban |`,
    `| 2024-07-06 | Continuation of Santiago incident; denial of accommodation, rights violations |`,
    ``,
    `## Agent Coverage`,
    ``,
    `| Category | Agent Count |`,
    `|----------|-------------|`,
    `| BR Specialists | ${agents.BR.length} |`,
    `| CL Specialists | ${agents.CL.length} |`,
    `| INT Specialists | ${agents.INT.length} |`,
    `| Meta-Agents | ${agents.meta.length} |`,
    `| **Total** | **${agents.BR.length + agents.CL.length + agents.INT.length + agents.meta.length}** |`,
    ``,
    `## Critical Violations`,
    ``,
  ];

  for (const vId of (crossRefMap.by_severity.CRITICAL || [])) {
    lines.push(`- **${vId}**`);
  }

  lines.push('');
  lines.push('## Next Steps');
  lines.push('');
  lines.push('1. Verify all law article texts against official sources');
  lines.push('2. Complete missing transcript segments');
  lines.push('3. Run adversarial testing (META_Adversarial) on critical violations');
  lines.push('4. Prepare filing roadmap (META_Prescription_Forum)');
  lines.push('5. Review gap_report.json for any evidence or documentation gaps');
  lines.push('');

  return lines.join('\n');
}

// ─── Main Consolidation ──────────────────────────────────────────────────────

function consolidate(options = {}) {
  const {
    outputDir = path.join(__dirname, '..', '..', 'LA8159_TRIAL'),
    sourceDir = LA8159_ROOT
  } = options;

  const log = [];
  const startTime = Date.now();

  function logStep(msg) {
    const entry = `[${new Date().toISOString()}] ${msg}`;
    log.push(entry);
    console.log(entry);
  }

  // ── Phase 1: Load all source data ──────────────────────────────────────────
  logStep('Phase 1: Loading source data from LA8159-incident');

  logStep('  Loading violations...');
  const { violations, byId: violationsById } = loadViolations();
  const totalViolations = violations.BR.length + violations.CL.length + violations.INT.length;
  logStep(`  Loaded ${totalViolations} violations (BR: ${violations.BR.length}, CL: ${violations.CL.length}, INT: ${violations.INT.length})`);

  logStep('  Loading law articles...');
  const lawArticles = loadLawArticles();
  const lawCount = Object.keys(lawArticles.byELI).length;
  logStep(`  Loaded ${lawCount} law articles across ${Object.keys(lawArticles.articles.BR).length + Object.keys(lawArticles.articles.CL).length + Object.keys(lawArticles.articles.INT).length} frameworks`);

  logStep('  Loading agents...');
  const agents = loadAgents();
  const agentCount = agents.BR.length + agents.CL.length + agents.INT.length + agents.meta.length;
  logStep(`  Loaded ${agentCount} agents (BR: ${agents.BR.length}, CL: ${agents.CL.length}, INT: ${agents.INT.length}, meta: ${agents.meta.length})`);

  logStep('  Loading agent mapping...');
  const mapping = readJSON(path.join(sourceDir, '0_agents', 'mapping.json'));
  logStep(`  Mapping loaded: ${mapping ? Object.keys(mapping.BR || {}).length + Object.keys(mapping.CL || {}).length + Object.keys(mapping.INT || {}).length : 0} violation→agent entries`);

  logStep('  Loading evidence index...');
  const evidenceItems = loadEvidenceIndex();
  logStep(`  Evidence items found: ${evidenceItems.length}`);

  logStep('  Loading case management data...');
  const masterViolationIndex = readJSON(path.join(sourceDir, '00_CASE_MANAGEMENT', 'master_violation_index.json'));
  const crossRefGraph = readJSON(path.join(sourceDir, '00_CASE_MANAGEMENT', 'cross_reference_graph.json'));
  const violationEvidenceMap = readJSON(path.join(sourceDir, '00_CASE_MANAGEMENT', 'violation_evidence_map.json'));
  const chronologicalTimeline = readText(path.join(sourceDir, '00_CASE_MANAGEMENT', 'CHRONOLOGICAL_TIMELINE.md'));

  // ── Phase 2: Build consolidated structures ──────────────────────────────────
  logStep('Phase 2: Building consolidated structures');

  logStep('  Building case graph...');
  const caseGraph = buildCaseGraph(violations, lawArticles, mapping);

  logStep('  Building cross-reference map...');
  const crossRefMap = buildCrossReferenceMap(violations);

  logStep('  Building agent-violation map...');
  const agentViolationMap = buildAgentViolationMap(mapping);

  logStep('  Building master index...');
  const masterIndex = buildMasterIndex(violations, lawArticles, agents, evidenceItems, mapping, caseGraph);

  // ── Phase 3: Write output ──────────────────────────────────────────────────
  logStep(`Phase 3: Writing consolidated output to ${outputDir}`);

  // Create output directory
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  // Write case graph
  writeJSON(path.join(outputDir, 'case_graph.json'), caseGraph);
  logStep('  Wrote case_graph.json');

  // Write master index
  writeJSON(path.join(outputDir, 'master_index.json'), masterIndex);
  logStep('  Wrote master_index.json');

  // Write cross-reference map
  writeJSON(path.join(outputDir, 'cross_reference_map.json'), crossRefMap);
  logStep('  Wrote cross_reference_map.json');

  // Write agent-violation map
  writeJSON(path.join(outputDir, 'agents', 'agent_violation_map.json'), agentViolationMap);
  logStep('  Wrote agents/agent_violation_map.json');

  // Copy violations organized by jurisdiction
  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      writeJSON(path.join(outputDir, 'violations', 'by_jurisdiction', jur, `${v.violation_id}.json`), v);
    }
  }
  logStep('  Copied violations by jurisdiction');

  // Copy violations by severity
  for (const [sev, vIds] of Object.entries(crossRefMap.by_severity)) {
    const sevDir = path.join(outputDir, 'violations', 'by_severity', sev);
    for (const vId of vIds) {
      const v = violationsById[vId];
      if (v) writeJSON(path.join(sevDir, `${vId}.json`), v);
    }
  }
  logStep('  Copied violations by severity');

  // Copy law articles
  for (const jur of ['BR', 'CL', 'INT']) {
    const baseDir = path.join(outputDir, 'law', jur, 'json');
    for (const [framework, articles] of Object.entries(lawArticles.articles[jur] || {})) {
      writeJSON(path.join(baseDir, `${framework}.json`), articles);
    }
  }
  writeJSON(path.join(outputDir, 'law', 'registry.json'), {
    by_eli: Object.fromEntries(
      Object.entries(lawArticles.byELI).map(([eli, art]) => [eli, {
        jurisdiction: art.jurisdiction,
        framework: art.framework_code,
        article_number: art.article_number,
        theme: art.theme,
        norm_type: art.norm_type
      }])
    )
  });
  logStep('  Copied law articles');

  // Copy OliviaLegal canonical source markdowns (law texts with full provenance)
  const oliviaSourcesDir = path.join(sourceDir, '..', '..', '..', 'leandrodisconzi', 'work', 'OliviaLegal', 'agents', 'agents-groups', 'la8159', 'source', 'sources');
  const altOliviaSourcesDir = '/Users/leandrodisconzi/work/OliviaLegal/agents/agents-groups/la8159/source/sources';
  const oliviaSrc = fs.existsSync(oliviaSourcesDir) ? oliviaSourcesDir : (fs.existsSync(altOliviaSourcesDir) ? altOliviaSourcesDir : null);

  if (oliviaSrc) {
    for (const jur of ['BR', 'CL', 'INT']) {
      const srcDir = path.join(oliviaSrc, jur);
      const destDir = path.join(outputDir, 'law', 'sources_md', jur);
      if (fs.existsSync(srcDir)) {
        const copied = copyDir(srcDir, destDir);
        logStep(`  Copied ${copied} source law markdowns for ${jur}`);
      }
    }
  } else {
    logStep('  OliviaLegal source markdowns not found — skipping');
  }

  // Copy agent specs
  for (const category of ['BR', 'CL', 'INT', 'meta']) {
    for (const agent of agents[category]) {
      const agentDestDir = path.join(outputDir, 'agents', category, agent.id);
      writeText(path.join(agentDestDir, 'agent.md'), agent.spec);
    }
  }
  writeText(path.join(outputDir, 'agents', 'INDEX.md'), readText(path.join(sourceDir, '0_agents', 'INDEX.md')) || '');
  writeText(path.join(outputDir, 'agents', 'README.md'), readText(path.join(sourceDir, '0_agents', 'README.md')) || '');
  writeText(path.join(outputDir, 'agents', 'PLAN.md'), readText(path.join(sourceDir, '0_agents', 'PLAN.md')) || '');
  writeJSON(path.join(outputDir, 'agents', 'mapping.json'), mapping || {});
  logStep('  Copied agent specifications');

  // Copy evidence
  const evidenceCopied = copyDir(
    path.join(sourceDir, '03_EVIDENCE'),
    path.join(outputDir, 'evidence')
  );
  logStep(`  Copied ${evidenceCopied} evidence files`);

  // Write evidence log
  writeJSON(path.join(outputDir, 'evidence', 'evidence_log.json'), evidenceItems);
  logStep('  Wrote evidence log');

  // Copy transcripts
  const transcriptsCopied = copyDir(
    path.join(sourceDir, '11_TranscriptTimeline'),
    path.join(outputDir, 'evidence', 'transcripts', 'full')
  );
  logStep(`  Copied ${transcriptsCopied} transcript files`);

  // Copy reports
  const reportsBrCopied = copyDir(
    path.join(sourceDir, '12_LegaReports'),
    path.join(outputDir, 'reports', 'BR')
  );
  const reportsClCopied = copyDir(
    path.join(sourceDir, '15_BR_PT_Reports'),
    path.join(outputDir, 'reports', 'CL')
  );
  logStep(`  Copied ${reportsBrCopied + reportsClCopied} report files`);

  // Copy incident data
  const incidentsCopied = copyDir(
    path.join(sourceDir, '01_INCIDENTS'),
    path.join(outputDir, 'incidents')
  );
  copyDir(
    path.join(sourceDir, 'incident-1-gru'),
    path.join(outputDir, 'incidents', 'incident-1-gru')
  );
  // Copy incident metadata
  writeJSON(path.join(outputDir, 'incidents', 'incident_index.json'), {
    source: path.join(sourceDir, '01_INCIDENTS'),
    incidents: fs.readdirSync(path.join(sourceDir, '01_INCIDENTS')).filter(f => !f.startsWith('.')),
    gru_precursor: 'incident-1-gru'
  });
  logStep(`  Copied incident data`);

  // Copy personnel data
  copyDir(
    path.join(sourceDir, '0_agents', 'personnel'),
    path.join(outputDir, 'personnel')
  );
  // Copy mapping personnel section
  if (mapping?.personnel) {
    writeJSON(path.join(outputDir, 'personnel', 'registry.json'), mapping.personnel);
  }
  logStep('  Copied personnel data');

  // Copy case management reference data
  if (masterViolationIndex) writeJSON(path.join(outputDir, 'reference', 'master_violation_index.json'), masterViolationIndex);
  if (crossRefGraph) writeJSON(path.join(outputDir, 'reference', 'cross_reference_graph.json'), crossRefGraph);
  if (violationEvidenceMap) writeJSON(path.join(outputDir, 'reference', 'violation_evidence_map.json'), violationEvidenceMap);
  if (chronologicalTimeline) writeText(path.join(outputDir, 'reference', 'CHRONOLOGICAL_TIMELINE.md'), chronologicalTimeline);
  logStep('  Copied case management reference data');

  // Generate CASE_SUMMARY.md
  const caseSummary = generateCaseSummary(caseGraph, crossRefMap, agentViolationMap, agents);
  writeText(path.join(outputDir, 'CASE_SUMMARY.md'), caseSummary);
  logStep('  Generated CASE_SUMMARY.md');

  // Generate timeline JSON from violations
  const timeline = buildTimelineFromViolations(violations, chronologicalTimeline);
  writeJSON(path.join(outputDir, 'timeline.json'), timeline);
  logStep('  Generated timeline.json');

  // Generate gap report
  const gapReport = buildGapReport(violations, lawArticles, agents, evidenceItems);
  writeJSON(path.join(outputDir, 'gap_report.json'), gapReport);
  logStep('  Generated gap_report.json');

  // ── Phase 4: Summary ────────────────────────────────────────────────────────
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  logStep(`Phase 4: Consolidation complete in ${elapsed}s`);

  return {
    ok: true,
    outputDir,
    stats: {
      total_violations: totalViolations,
      total_law_articles: lawCount,
      total_agents: agentCount,
      total_evidence_items: evidenceItems.length,
      total_reports: reportsBrCopied + reportsClCopied,
      elapsed_seconds: parseFloat(elapsed)
    },
    log
  };
}

// ─── Timeline Builder ─────────────────────────────────────────────────────────

function buildTimelineFromViolations(violations, chronologicalTimelineText) {
  const events = [];

  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      for (const seg of (v.facts?.segments || [])) {
        if (seg.timeStart) {
          events.push({
            time: seg.timeStart,
            endTime: seg.timeEnd || null,
            speaker: seg.speaker,
            text: (seg.text || '').slice(0, 300),
            violation_id: v.violation_id,
            jurisdiction: jur,
            segment_id: seg.segment_id
          });
        }
      }
    }
  }

  // Sort by time
  events.sort((a, b) => a.time.localeCompare(b.time));

  // Group by date
  const byDate = {};
  for (const evt of events) {
    const date = evt.time.slice(0, 10);
    if (!byDate[date]) byDate[date] = [];
    byDate[date].push(evt);
  }

  return {
    generated_at: new Date().toISOString(),
    total_events: events.length,
    date_range: {
      start: events.length > 0 ? events[0].time : null,
      end: events.length > 0 ? events[events.length - 1].time : null
    },
    by_date: byDate,
    events,
    chronological_markdown: chronologicalTimelineText ? '(see reference/CHRONOLOGICAL_TIMELINE.md)' : null
  };
}

// ─── Gap Report Builder ───────────────────────────────────────────────────────

function buildGapReport(violations, lawArticles, agents, evidenceItems) {
  const gaps = [];

  // Check for violations without segments
  for (const jur of ['BR', 'CL', 'INT']) {
    for (const v of violations[jur]) {
      if (!v.facts?.segments || v.facts.segments.length === 0) {
        gaps.push({
          type: 'MISSING_SEGMENTS',
          severity: 'HIGH',
          violation_id: v.violation_id,
          description: 'Violation has no transcript segments'
        });
      }

      // Check for violations without law references
      if (!v.legal_basis?.frameworks || v.legal_basis.frameworks.length === 0) {
        gaps.push({
          type: 'MISSING_LEGAL_BASIS',
          severity: 'CRITICAL',
          violation_id: v.violation_id,
          description: 'Violation has no legal framework references'
        });
      }

      // Check for articles without verified text
      for (const fw of (v.legal_basis?.frameworks || [])) {
        for (const art of (fw.articles || [])) {
          if (!art.article_text || art.article_text.length === 0) {
            gaps.push({
              type: 'MISSING_ARTICLE_TEXT',
              severity: 'MEDIUM',
              violation_id: v.violation_id,
              article_id: art.article_id,
              description: 'Article referenced but text not provided'
            });
          }
        }
      }
    }
  }

  // Check evidence coverage
  if (evidenceItems.length === 0) {
    gaps.push({
      type: 'NO_EVIDENCE',
      severity: 'CRITICAL',
      description: 'No evidence files found in 03_EVIDENCE'
    });
  }

  return {
    generated_at: new Date().toISOString(),
    total_gaps: gaps.length,
    high_priority_gaps: gaps.filter(g => g.severity === 'CRITICAL').length,
    by_type: {
      MISSING_SEGMENTS: gaps.filter(g => g.type === 'MISSING_SEGMENTS').length,
      MISSING_LEGAL_BASIS: gaps.filter(g => g.type === 'MISSING_LEGAL_BASIS').length,
      MISSING_ARTICLE_TEXT: gaps.filter(g => g.type === 'MISSING_ARTICLE_TEXT').length,
      NO_EVIDENCE: gaps.filter(g => g.type === 'NO_EVIDENCE').length
    },
    gaps
  };
}

module.exports = {
  consolidate,
  loadViolations,
  loadLawArticles,
  loadAgents,
  loadEvidenceIndex,
  buildCaseGraph,
  buildMasterIndex,
  buildCrossReferenceMap,
  buildAgentViolationMap,
  buildTimelineFromViolations,
  buildGapReport,
  generateCaseSummary
};
