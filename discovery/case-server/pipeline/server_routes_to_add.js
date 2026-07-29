/**
 * Intelligence Pipeline API Endpoints
 * Add these routes to auto_server_builder.js
 * 
 * Paste this block after the existing /api/pipeline/* routes.
 */

// ─── L5b–L7: Intelligence Pipeline Trigger ───────────────────────────────────

/**
 * POST /api/intelligence/run
 * Trigger the full L5–L7 intelligence pipeline on already-ingested data.
 * 
 * Body: {
 *   api_key:     string,   // Anthropic API key
 *   model?:      string,   // default: deepseek-v4-pro
 *   concurrency?: number,  // default: 3
 *   skip_dedup?:  boolean  // default: false
 * }
 */
app.post('/api/intelligence/run', async (req, res) => {
  const { api_key, model, concurrency, skip_dedup } = req.body || {};

  if (!api_key) {
    return res.status(400).json({ error: 'api_key required' });
  }

  try {
    const { runIntelligencePipeline, extendStore } = require('./pipeline');
    const pipelineStore = extendStore(currentStore); // currentStore = your existing store instance

    const result = await runIntelligencePipeline(pipelineStore, currentRootDir, {
      apiKey:      api_key,
      model:       model || 'deepseek-v4-pro',
      concurrency: concurrency || 3,
      skipDedup:   skip_dedup || false,
      outputDir:   path.join(currentRootDir, '_intelligence'),
      onProgress:  (stage, detail) => console.log(`[${stage}] ${detail}`)
    });

    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /api/intelligence/run-stream
 * Same as /run but streams progress via Server-Sent Events.
 */
app.get('/api/intelligence/run-stream', async (req, res) => {
  const { api_key, model } = req.query;

  res.setHeader('Content-Type',  'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection',    'keep-alive');

  const send = (stage, data) => {
    res.write(`data: ${JSON.stringify({ stage, ...data })}\n\n`);
  };

  if (!api_key) {
    send('error', { message: 'api_key required' });
    return res.end();
  }

  try {
    const { runIntelligencePipeline, extendStore } = require('./pipeline');
    const pipelineStore = extendStore(currentStore);

    const result = await runIntelligencePipeline(pipelineStore, currentRootDir, {
      apiKey:   api_key,
      model:    model || 'deepseek-v4-pro',
      outputDir: path.join(currentRootDir, '_intelligence'),
      onProgress: (stage, detail) => send('progress', { stage, detail })
    });

    send('complete', result);
    res.end();
  } catch (err) {
    send('error', { message: err.message });
    res.end();
  }
});

// ─── Intelligence Output Endpoints ───────────────────────────────────────────

/**
 * GET /api/intelligence/case-graph
 * Returns the full ontology v2.4 compliant case graph.
 */
app.get('/api/intelligence/case-graph', (req, res) => {
  const graphPath = path.join(currentRootDir, '_intelligence', 'case_graph.json');
  if (!fs.existsSync(graphPath)) {
    return res.status(404).json({ error: 'Case graph not yet generated. Run /api/intelligence/run first.' });
  }
  res.json(JSON.parse(fs.readFileSync(graphPath, 'utf8')));
});

/**
 * GET /api/intelligence/violations
 * Returns article-mapped violations with confidence scores.
 * Query params: ?severity=high|medium|low  ?min_confidence=0.7
 */
app.get('/api/intelligence/violations', (req, res) => {
  const violsPath = path.join(currentRootDir, '_intelligence', 'violations.json');
  if (!fs.existsSync(violsPath)) {
    return res.status(404).json({ error: 'Violations not yet generated.' });
  }

  let violations = JSON.parse(fs.readFileSync(violsPath, 'utf8'));

  if (req.query.severity) {
    violations = violations.filter(v => v.severity === req.query.severity);
  }
  if (req.query.min_confidence) {
    const min = parseFloat(req.query.min_confidence);
    violations = violations.filter(v => v.confidence >= min);
  }

  res.json({ total: violations.length, violations });
});

/**
 * GET /api/intelligence/timeline
 * Returns the chronological event timeline.
 */
app.get('/api/intelligence/timeline', (req, res) => {
  const tlPath = path.join(currentRootDir, '_intelligence', 'timeline.json');
  if (!fs.existsSync(tlPath)) {
    return res.status(404).json({ error: 'Timeline not yet generated.' });
  }
  res.json(JSON.parse(fs.readFileSync(tlPath, 'utf8')));
});

/**
 * GET /api/intelligence/narrative
 * Returns the case narrative as markdown text.
 */
app.get('/api/intelligence/narrative', (req, res) => {
  const nPath = path.join(currentRootDir, '_intelligence', 'narrative.md');
  if (!fs.existsSync(nPath)) {
    return res.status(404).json({ error: 'Narrative not yet generated.' });
  }
  const markdown = fs.readFileSync(nPath, 'utf8');
  const format   = req.query.format || 'json';
  if (format === 'md') {
    res.setHeader('Content-Type', 'text/markdown');
    return res.send(markdown);
  }
  res.json({ markdown });
});

/**
 * GET /api/intelligence/gap-report
 * Returns the gap analysis against ontology invariants.
 */
app.get('/api/intelligence/gap-report', (req, res) => {
  const gapPath = path.join(currentRootDir, '_intelligence', 'gap_report.json');
  if (!fs.existsSync(gapPath)) {
    return res.status(404).json({ error: 'Gap report not yet generated.' });
  }
  res.json(JSON.parse(fs.readFileSync(gapPath, 'utf8')));
});

/**
 * GET /api/intelligence/law-registry
 * Returns all resolved and unresolved law references.
 * Query params: ?resolved=true|false  ?needs_argus=true
 */
app.get('/api/intelligence/law-registry', (req, res) => {
  const lawPath = path.join(currentRootDir, '_intelligence', 'law_registry.json');
  if (!fs.existsSync(lawPath)) {
    return res.status(404).json({ error: 'Law registry not yet generated.' });
  }

  let registry = JSON.parse(fs.readFileSync(lawPath, 'utf8'));

  if (req.query.resolved !== undefined) {
    const want = req.query.resolved === 'true';
    registry = registry.filter(r => r.resolved === want);
  }
  if (req.query.needs_argus === 'true') {
    registry = registry.filter(r => r.needs_argus);
  }

  res.json({ total: registry.length, registry });
});

/**
 * GET /api/intelligence/dedup-report
 * Returns deduplication statistics and cluster details.
 */
app.get('/api/intelligence/dedup-report', (req, res) => {
  const dedupPath = path.join(currentRootDir, '_intelligence', 'dedup_report.json');
  if (!fs.existsSync(dedupPath)) {
    return res.status(404).json({ error: 'Dedup report not yet generated.' });
  }

  const data    = JSON.parse(fs.readFileSync(dedupPath, 'utf8'));
  const summary = req.query.summary === 'true';

  if (summary) {
    return res.json({ stats: data.stats });
  }
  res.json(data);
});

/**
 * GET /api/intelligence/summary
 * Returns the pipeline run summary with all stats and output file paths.
 */
app.get('/api/intelligence/summary', (req, res) => {
  const summaryPath = path.join(currentRootDir, '_intelligence', 'pipeline_summary.json');
  if (!fs.existsSync(summaryPath)) {
    return res.status(404).json({
      error:   'Intelligence pipeline has not been run yet.',
      hint:    'POST /api/intelligence/run with your API key',
      example: { api_key: 'YOUR_ANTHROPIC_API_KEY', model: 'deepseek-v4-pro' }
    });
  }
  res.json(JSON.parse(fs.readFileSync(summaryPath, 'utf8')));
});
