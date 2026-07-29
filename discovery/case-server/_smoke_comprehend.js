'use strict';
const { groupFiles, sampleGroup, buildFileSummary } = require('./pipeline/comprehend');
const { runPipeline, runIntelligencePipeline, runComprehension, extendStore, enrichEndpoint } = require('./pipeline');

const checks = { groupFiles, sampleGroup, buildFileSummary, runPipeline, runIntelligencePipeline, runComprehension, extendStore, enrichEndpoint };
for (const [k, v] of Object.entries(checks)) console.log(k + ': ' + typeof v);

const store     = require('./pipeline/store');
const fs        = require('fs');
const storeFile = '/Users/leandrodisconzi/Documents/sa_server/latam-manus 2/workspace/latam/.discovery/pipeline_store.json';
if (fs.existsSync(storeFile)) {
  store.load(storeFile);
  const all    = Object.values(store.getAllFiles());
  const groups = groupFiles(all);
  console.log('\nGroups by domain (largest first):');
  Object.entries(groups)
    .sort((a, b) => b[1].count - a[1].count)
    .forEach(([k, g]) => console.log('  ' + k.padEnd(28) + String(g.count).padStart(5) + ' files  ' + String(g.totalWords).padStart(9) + ' words'));
  const sampleKey = Object.keys(groups).sort((a, b) => groups[b].count - groups[a].count)[0];
  const samples   = sampleGroup(groups[sampleKey].files, 5);
  console.log('\nTop sample group "' + sampleKey + '": chose ' + samples.length + ' of ' + groups[sampleKey].count + ' files');
  const s = buildFileSummary(samples[0]);
  console.log('  path: ' + s.path + '  ext: ' + s.extension + '  words: ' + s.word_count);
} else {
  console.log('(store file not found — export type check passed)');
}
