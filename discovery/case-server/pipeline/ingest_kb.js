#!/usr/bin/env node
/**
 * Pipeline — Knowledge Base Ingestion Script
 *
 * One-shot script to populate Qdrant + Neo4j from LA8159 materials.
 *
 * Sources ingested:
 *   1. Agent .md files — extract article tables (parseAgentFile)
 *   2. Source files    — raw statute texts from source/BR/, source/CL/, source/INT/
 *   3. Violation JSON  — validated violation-to-article mappings
 *
 * Usage:
 *   node ingest_kb.js [--dry-run] [--agents-dir <path>] [--source-dir <path>]
 *
 * Environment:
 *   KB_ENABLED=true
 *   QDRANT_URL=http://localhost:6333
 *   NEO4J_URL=bolt://localhost:7687
 *   NEO4J_USER=neo4j
 *   NEO4J_PASSWORD=neo4j
 *   EMBEDDING_ENDPOINT=https://api.openai.com/v1/embeddings  (optional)
 *   EMBEDDING_API_KEY=sk-...                                   (optional)
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const {
  readConfig,
  parseAgentFile,
  ingestAgentKnowledge,
  upsertArticles,
  neo4jWrite,
  isAvailable
} = require('./legal_kb');

// ─── CLI argument parsing ──────────────────────────────────────────────────

const args = process.argv.slice(2);
const opts = {
  dryRun:     args.includes('--dry-run'),
  agentsDir:  argValue('--agents-dir', args) || process.env.LA8159_AGENTS_DIR,
  sourceDir:  argValue('--source-dir', args) || process.env.LA8159_SOURCE_DIR,
  violationsDir: argValue('--violations-dir', args),
  help:       args.includes('--help') || args.includes('-h')
};

function argValue(flag, argv) {
  const idx = argv.indexOf(flag);
  return idx >= 0 && idx + 1 < argv.length ? argv[idx + 1] : null;
}

if (opts.help) {
  console.log(`
Usage: node ingest_kb.js [options]

Options:
  --dry-run          Parse and report without writing to Qdrant/Neo4j
  --agents-dir <path>  Directory containing LA8159 agent .md files
  --source-dir <path>  Directory containing LA8159 source subdirectories (BR/, CL/, INT/)
  --violations-dir <path>  Directory containing validated violation JSONs
  --help, -h         Show this help

Environment:
  KB_ENABLED=true
  QDRANT_URL         (default: http://localhost:6333)
  NEO4J_URL          (default: bolt://localhost:7687)
  NEO4J_USER, NEO4J_PASSWORD
  EMBEDDING_ENDPOINT  OpenAI-compatible embeddings endpoint
  EMBEDDING_API_KEY   API key for embeddings
`);
  process.exit(0);
}

// ─── Default paths — derive from LA8159 group location ─────────────────────

const OLIVIALEGAL_ROOT = process.env.OLIVIALEGAL_ROOT
  || path.resolve(__dirname, '..', '..', '..', '..', 'leandrodisconzi', 'work', 'OliviaLegal');

const LA8159_ROOT = path.join(OLIVIALEGAL_ROOT, 'agents', 'agents-groups', 'la8159');

if (!opts.agentsDir) {
  opts.agentsDir = path.join(LA8159_ROOT, 'agents');
}
if (!opts.sourceDir) {
  opts.sourceDir = path.join(LA8159_ROOT, 'source');
}
if (!opts.violationsDir) {
  opts.violationsDir = path.join(LA8159_ROOT, 'source', '10_violations_json', 'validated');
}

// ─── Main ──────────────────────────────────────────────────────────────────

async function main() {
  const config = readConfig();

  console.log('=== LA8159 Knowledge Base Ingestion ===\n');
  console.log(`Dry run: ${opts.dryRun}`);
  console.log(`Agents dir: ${opts.agentsDir}`);
  console.log(`Source dir: ${opts.sourceDir}`);
  console.log(`Violations dir: ${opts.violationsDir}`);
  console.log(`KB enabled: ${config.enabled}`);
  console.log(`Qdrant URL: ${config.qdrantUrl}`);
  console.log(`Neo4j URL: ${config.neo4jUrl}`);
  console.log(`Embeddings: ${config.embeddingEndpoint ? 'configured' : 'not configured (will skip vectors)'}`);
  console.log('');

  // ── Health check ─────────────────────────────────────────────────────────
  const health = await isAvailable();
  console.log(`Health check: Qdrant=${health.qdrant} Neo4j=${health.neo4j}\n`);

  if (!health.qdrant && !health.neo4j && !opts.dryRun) {
    console.log('[WARN] Neither Qdrant nor Neo4j are available. Run with --dry-run to preview parsing.');
    if (!config.enabled) {
      console.log('[INFO] Set KB_ENABLED=true to enable KB connections.');
    }
  }

  const results = {
    agents:   { parsed: 0, articles: 0, upserted: 0, errors: 0 },
    source:   { files: 0, articles: 0, upserted: 0, errors: 0 },
    violations: { mapped: 0, persisted: 0 }
  };

  // ── Step 1: Ingest agent knowledge ───────────────────────────────────────
  console.log('--- Step 1: Agent Knowledge ---');

  if (fs.existsSync(opts.agentsDir)) {
    const agentFiles = fs.readdirSync(opts.agentsDir).filter(f => f.endsWith('.agent.md'));
    console.log(`Found ${agentFiles.length} agent files`);

    const allArticles = [];
    for (const file of agentFiles) {
      const filePath = path.join(opts.agentsDir, file);
      const articles = parseAgentFile(filePath);
      if (articles.length > 0) {
        console.log(`  ${file}: ${articles.length} articles`);
        allArticles.push(...articles);
      }
    }

    results.agents.parsed = agentFiles.length;
    results.agents.articles = allArticles.length;

    if (!opts.dryRun && allArticles.length > 0) {
      const { upserted, errors } = await upsertArticles(allArticles);
      results.agents.upserted = upserted;
      results.agents.errors = errors;
      console.log(`  Upserted ${upserted} articles to Qdrant (${errors} errors)`);
    } else {
      console.log(`  [DRY RUN] Would upsert ${allArticles.length} articles`);
    }
  } else {
    console.log(`  Agents dir not found: ${opts.agentsDir}`);
  }

  // ── Step 2: Ingest source files ──────────────────────────────────────────
  console.log('\n--- Step 2: Source Files ---');

  if (fs.existsSync(opts.sourceDir)) {
    const sourceResults = await ingestSourceFiles(opts.sourceDir, opts.dryRun);
    results.source = sourceResults;
  } else {
    console.log(`  Source dir not found: ${opts.sourceDir}`);
  }

  // ── Step 3: Ingest violation-to-article mappings ──────────────────────────
  console.log('\n--- Step 3: Violation Mappings ---');

  if (fs.existsSync(opts.violationsDir)) {
    const violResults = await ingestViolationMappings(opts.violationsDir, opts.dryRun, config);
    results.violations = violResults;
  } else {
    console.log(`  Violations dir not found: ${opts.violationsDir}`);
  }

  // ── Summary ──────────────────────────────────────────────────────────────
  console.log('\n=== Ingestion Summary ===');
  console.log(`  Agent files parsed:    ${results.agents.parsed}`);
  console.log(`  Agent articles found:  ${results.agents.articles}`);
  console.log(`  Agent articles stored: ${results.agents.upserted}`);
  console.log(`  Source files:          ${results.source.files}`);
  console.log(`  Source articles:       ${results.source.articles}`);
  console.log(`  Violation mappings:    ${results.violations.mapped}`);
  console.log(`  Violations persisted:  ${results.violations.persisted}`);
}

// ─── Source file ingestion ─────────────────────────────────────────────────

async function ingestSourceFiles(sourceDir, dryRun) {
  const allArticles = [];
  const jurisdictions = ['BR', 'CL', 'INT', 'meta'];

  for (const jur of jurisdictions) {
    const jurDir = path.join(sourceDir, jur);
    if (!fs.existsSync(jurDir)) continue;

    const entries = fs.readdirSync(jurDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (entry.name.startsWith('_') || entry.name.startsWith('.')) continue;

      const agentDir = path.join(jurDir, entry.name);
      const agentMd = path.join(agentDir, 'agent.md');
      const sourcesDir = path.join(agentDir, 'sources');

      // Try to load agent.md first (has article tables like the top-level agents)
      if (fs.existsSync(agentMd)) {
        const content = fs.readFileSync(agentMd, 'utf-8');

        // Look for article verifications in the source agent.md
        // Format can be: "Art. N — <text>" or table rows
        const articleLines = content.match(/Art\.?\s*\d+[^.]*\./g) || [];
        for (const line of articleLines) {
          const numMatch = line.match(/Art\.?\s*(\d+[A-Za-z°º§]*)/);
          if (!numMatch) continue;
          const articleNum = numMatch[1];

          const textMatch = content.match(
            new RegExp(`Art\\.?\\s*${escapeRegex(articleNum)}[^.]*\\.\\s*([^.]+(?:\\.[^.]+)?)`)
          );
          const articleText = textMatch?.[1]?.trim() || `${jur} ${entry.name} Art. ${articleNum}`;

          allArticles.push({
            eli_id: `${jur}.${entry.name}.Art.${articleNum.replace(/[°º§]/g, '')}`,
            article_number: articleNum,
            article_text: articleText.slice(0, 2000),
            article_reference: `${entry.name}, Art. ${articleNum}`,
            framework_code: entry.name,
            framework_name: entry.name.replace(/_/g, ' '),
            jurisdiction: jur,
            verification_status: 'pending',
            source_file: agentMd
          });
        }
      }

      // Also check for raw sources
      if (fs.existsSync(sourcesDir)) {
        const sourceFiles = fs.readdirSync(sourcesDir);
        for (const sf of sourceFiles) {
          if (sf.startsWith('.') || sf.endsWith('.json')) continue;
          // These are typically markdown or text files with statute text
          // We don't parse them article-by-article here; they're ingested as
          // whole documents via the framework-level embedding
        }
      }
    }
  }

  if (!dryRun && allArticles.length > 0) {
    const { upserted, errors } = await upsertArticles(allArticles);
    return { files: allArticles.length, articles: allArticles.length, upserted, errors };
  }

  return { files: allArticles.length, articles: allArticles.length, upserted: 0, errors: 0 };
}

// ─── Violation mapping ingestion ───────────────────────────────────────────

async function ingestViolationMappings(violationsDir, dryRun, config) {
  let mapped = 0;
  let persisted = 0;

  // Walk the violations directory
  function walkDir(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith('.')) {
        walkDir(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.json')) {
        try {
          const data = JSON.parse(fs.readFileSync(fullPath, 'utf-8'));

          // These files contain validated violation records
          // Each violation may reference law articles
          if (Array.isArray(data)) {
            for (const item of data) {
              mapped++;
            }
          } else if (data.violations || data.articles) {
            mapped += (data.violations || data.articles || []).length;
          }
        } catch (_) { /* skip unparseable files */ }
      }
    }
  }

  try {
    walkDir(violationsDir);
  } catch (_) {
    return { mapped: 0, persisted: 0 };
  }

  if (!dryRun && mapped > 0) {
    // Create co-citation relationships in Neo4j
    // For now, we note the count — detailed co-citation building happens
    // when actual case graphs are persisted via persistCaseGraph()
    persisted = 0; // Co-citations built dynamically during case persistence
  }

  return { mapped, persisted };
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ─── Run ───────────────────────────────────────────────────────────────────

// Only run when executed directly, not when required
if (require.main === module) {
  main().catch(err => {
    console.error('Ingestion failed:', err.message);
    process.exit(1);
  });
}

module.exports = { main, ingestSourceFiles, ingestViolationMappings };
