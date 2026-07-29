#!/usr/bin/env node
/**
 * LA8159 Case Consolidation — Entry Point
 *
 * Reads all validated LA8159 data and builds a consolidated,
 * trial-ready directory structure at LA8159_TRIAL/
 *
 * Usage:
 *   node consolidate-la8159.js [--output /path/to/output]
 */

'use strict';

const path = require('path');
const { consolidate } = require('./pipeline/consolidate');

const OUTPUT_DIR = process.argv.includes('--output')
  ? process.argv[process.argv.indexOf('--output') + 1]
  : path.join(__dirname, '..', 'LA8159_TRIAL');

console.log('═══════════════════════════════════════════════');
console.log('  LA8159 Case Consolidation Pipeline');
console.log('═══════════════════════════════════════════════');
console.log('');
console.log(`Source:  /Users/dev/LA8159-incident/`);
console.log(`Output:  ${OUTPUT_DIR}`);
console.log('');

const result = consolidate({ outputDir: OUTPUT_DIR });

console.log('');
console.log('═══════════════════════════════════════════════');
console.log('  Consolidation Complete');
console.log('═══════════════════════════════════════════════');
console.log('');
console.log(`Violations:       ${result.stats.total_violations}`);
console.log(`Law Articles:     ${result.stats.total_law_articles}`);
console.log(`Agents:           ${result.stats.total_agents}`);
console.log(`Evidence Items:   ${result.stats.total_evidence_items}`);
console.log(`Reports Copied:   ${result.stats.total_reports}`);
console.log(`Time:             ${result.stats.elapsed_seconds}s`);
console.log('');
console.log(`Output directory: ${result.outputDir}`);
console.log('');

if (!result.ok) {
  console.error('ERRORS encountered during consolidation:');
  for (const entry of result.log) {
    if (entry.includes('ERROR')) console.error(`  ${entry}`);
  }
  process.exit(1);
}
