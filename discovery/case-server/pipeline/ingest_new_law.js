/**
 * ingest_new_law.js — Ingest the newly-added article-level law files
 * (data-law/BR/*.md) into Qdrant:
 *   - la8159_law       (exact-lookup payload store; requires a 768-dim dense
 *                       vector per point — a deterministic unit vector is used
 *                       as a placeholder since the original embedding model is
 *                       no longer available; exact lookup is payload-based)
 *   - la8159_law_bm25  (active BM25 search store; server computes sparse vector)
 *
 * Also deletes the 3 obsolete BR.ABEAR_POL.* points (ABEAR_Code.md was archived;
 * POL/PMD is superseded by ABEAR_PMD_TratamentoRelatos.md).
 *
 * Deterministic UUIDv5 point ids derived from original_id → idempotent upserts.
 *
 * Usage:
 *   node case-server/pipeline/ingest_new_law.js [--files a,b,c] [--dry-run]
 * Env: QDRANT_URL + QDRANT_API_KEY
 */

'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LAW_DIR = path.join(REPO_ROOT, 'data-law', 'BR');
try { require('dotenv').config({ path: path.join(REPO_ROOT, '.env') }); } catch (_) {}

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const onlyArg = args.find(a => a.startsWith('--files='));
const onlyFiles = onlyArg ? onlyArg.split('=')[1].split(',').map(s => s.trim()).filter(Boolean) : null;

// ── deterministic helpers ──────────────────────────────────────────────────
const NS = '6f1e6a9d-2a0a-4c0c-9e1e-a1b2c3d4e5f6'; // namespace for v5 ids
function uuid5(name) {
  const ns = Buffer.from(NS.replace(/-/g, ''), 'hex');
  const hash = crypto.createHash('sha1').update(ns).update(String(name)).digest();
  hash[6] = (hash[6] & 0x0f) | 0x50;
  hash[8] = (hash[8] & 0x3f) | 0x80;
  const b = hash.slice(0, 16);
  const s = b.toString('hex');
  return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`;
}
function hashInt(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
// deterministic 768-dim unit vector (placeholder for la8159_law dense field)
function placeholderVector(originalId) {
  const seed = hashInt(originalId);
  let s = seed;
  const rand = () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
  const v = [];
  let norm = 0;
  for (let i = 0; i < 768; i++) { const x = rand() * 2 - 1; v.push(x); norm += x * x; }
  norm = Math.sqrt(norm) || 1;
  return v.map(x => x / norm);
}

// ── Qdrant client ──────────────────────────────────────────────────────────
const BASE = String(process.env.QDRANT_URL || '').replace(/\/+$/, '');
const HEADERS = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'api-key': process.env.QDRANT_API_KEY || '' };
async function q(method, apiPath, body) {
  const r = await fetch(`${BASE}:6333${apiPath}`, { method, headers: HEADERS, body: body ? JSON.stringify(body) : undefined });
  let t = null; try { t = await r.json(); } catch (_) {}
  return { status: r.status, body: t };
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── parse article-level md into ingest records ─────────────────────────────
function docTypeFor(filename) {
  if (/^R\d+_ANAC/.test(filename)) return 'Resolution';
  if (/^D\d+/.test(filename)) return 'unknown';
  if (/^ABEAR/.test(filename)) return 'Internal';
  return 'unknown';
}
function parseFile(file) {
  const txt = fs.readFileSync(file, 'utf8');
  const base = path.basename(file);
  const lines = txt.split('\n');
  const records = [];
  let i = 0;
  while (i < lines.length) {
    if (/^### /.test(lines[i])) {
      const heading = lines[i].replace(/^### /, '').trim();
      const block = [];
      let j = i + 1;
      while (j < lines.length && !/^### /.test(lines[j]) && !/^## Metadata/.test(lines[j]) && lines[j].trim() !== '## Articles') {
        block.push(lines[j]); j++;
      }
      const bt = block.join('\n');
      const eli = (bt.match(/ELI\s*ID:?\s*\**\s*`([^`]+)`/) || [])[1];
      const theme = (bt.match(/Theme:\s*\**\s*([^\n*]+)/) || [])[1] || '';
      const tags = (bt.match(/Tags:\s*\**\s*([^\n]+)/) || [])[1] || '';
      // body = everything after the Tags line
      const tagIdx = block.findIndex(l => /^[*_-]*\s*Tags:/i.test(l.trim()));
      const bodyLines = tagIdx >= 0 ? block.slice(tagIdx + 1) : block.slice(1);
      let body = bodyLines.join('\n').trim();
      body = body.replace(/\n{3,}/g, '\n\n').replace(/^\s*---+$/m, '').trim();
      const jur = (eli || '').split('.')[0] || 'BR';
      const fw = (eli || '').split('.')[1] || null;
      if (eli && body) {
        records.push({
          original_id: eli,
          title: heading,
          theme,
          tags,
          text: body,
          content: body,
          source_file: base,
          jurisdiction: jur,
          framework_code: fw,
          doc_type: docTypeFor(base)
        });
      }
      i = j;
      continue;
    }
    i++;
  }
  return records;
}

// ── main ───────────────────────────────────────────────────────────────────
async function upsertBatch(collection, points, label) {
  for (let i = 0; i < points.length; i += 24) {
    const chunk = points.slice(i, i + 24);
    const res = await q('PUT', `/collections/${collection}/points`, { points: chunk, wait: true });
    const ok = res.status === 200 && (res.body?.result?.status === 'completed' || res.body?.status === 'ok' || res.body?.result?.status === 'acknowledged');
    if (!ok) console.log(`  [FAIL ${collection}] ${label} batch@${i}: ${res.status} ${JSON.stringify(res.body).slice(0,140)}`);
  }
}

(async () => {
  if (!BASE || !HEADERS['api-key']) { console.error('Need QDRANT_URL + QDRANT_API_KEY'); process.exit(1); }

  // Only the newly-added files should be ingested. Re-ingesting pre-existing
  // files (D11129, D2181, R400, etc.) would overwrite their real dense vectors
  // with placeholder vectors — never do that.
  const NEW_FILES = [
    'ABEAR_CodigoConduta.md', 'ABEAR_PMD_TratamentoRelatos.md',
    'ABEAR_PoliticaAnticorrupcao.md', 'ABEAR_PoliticaCartoesCorporativos.md',
    'ABEAR_PoliticaComprasDueDiligence.md', 'ABEAR_PoliticaInteracaoAgentesPublicos.md',
    'ABEAR_PoliticaPresentesEntretenimento.md', 'ABEAR_PoliticaViagemReembolso.md',
    'ABEAR_RegimentoComiteCompliance.md', 'D1171_CodigoEticaServidor.md',
    'D6029_SistemaGestaoEtica.md', 'R029_ANAC_ComissaoEtica.md',
    'R431_ANAC_RegimentoComissaoEtica.md', 'R523_ANAC_ComissaoEtica.md',
    'R770_ANAC_CodigoEtica.md'
  ];
  const files = NEW_FILES
    .filter(f => fs.existsSync(path.join(LAW_DIR, f)))
    .filter(f => onlyFiles ? onlyFiles.includes(f) : true)
    .sort();
  console.log('Files to ingest:', files.length);
  let all = [];
  for (const f of files) {
    const recs = parseFile(path.join(LAW_DIR, f));
    console.log(`  ${f}: ${recs.length} articles`);
    all = all.concat(recs);
  }
  console.log('TOTAL new article records:', all.length);
  if (all.length === 0) { console.log('Nothing to do.'); process.exit(0); }
  if (dryRun) { console.log('DRY-RUN — no Qdrant writes.'); process.exit(0); }

  const now = new Date().toISOString();
  // la8159_law: payload + placeholder dense vector
  const densePoints = all.map(r => ({
    id: uuid5(r.original_id),
    vector: placeholderVector(r.original_id),
    payload: {
      original_id: r.original_id,
      title: r.title,
      text: r.text,
      content: r.content,
      source_file: r.source_file,
      theme: r.theme,
      tags: r.tags,
      doc_type: r.doc_type,
      metadata: { data_type: 'law', doc_type: r.doc_type, ingestion_time: now },
      original_data: { id: uuid5(r.original_id), title: r.title, source_file: r.source_file, theme: r.theme, tags: r.tags, content: r.content, original_id: r.original_id }
    }
  }));
  console.log('\nUpserting into la8159_law (payload + placeholder dense)...');
  await upsertBatch('la8159_law', densePoints, 'law');

  // la8159_law_bm25: payload (with derived jurisdiction/framework_code) + server BM25
  const bm25Points = all.map(r => ({
    id: uuid5(r.original_id),
    vector: { text: { text: r.text.slice(0, 12000), model: 'qdrant/bm25' } },
    payload: {
      original_id: r.original_id,
      title: r.title,
      text: r.text,
      content: r.content,
      source_file: r.source_file,
      theme: r.theme,
      tags: r.tags,
      doc_type: r.doc_type,
      jurisdiction: r.jurisdiction,
      framework_code: r.framework_code,
      metadata: { data_type: 'law', doc_type: r.doc_type, ingestion_time: now },
      original_data: { id: uuid5(r.original_id), title: r.title, source_file: r.source_file, theme: r.theme, tags: r.tags, content: r.content, original_id: r.original_id }
    }
  }));
  console.log('Upserting into la8159_law_bm25 (payload + qdrant/bm25)...');
  await upsertBatch('la8159_law_bm25', bm25Points, 'bm25');

  // delete obsolete ABEAR_POL points (superseded by ABEAR_PMD) — resolve their
  // real point ids by original_id scroll, then delete (UUIDs may differ from a
  // deterministic uuid5 of the original_id).
  const obsolete = ['BR.ABEAR_POL.§1 — Objetivo', 'BR.ABEAR_POL.§5 — Análise de Reportes que Representam Não Conformidades', 'BR.ABEAR_POL.§7 — Deliberação do Comitê de Compliance e Medidas Disciplinares'];
  for (const col of ['la8159_law', 'la8159_law_bm25']) {
    const found = [];
    for (const oid of obsolete) {
      const sc = await q('POST', `/collections/${col}/points/scroll`, { filter: { must: [{ key: 'original_id', match: { value: oid } }] }, limit: 5, with_payload: false });
      const pts = (sc.body?.result?.points) || [];
      for (const p of pts) found.push(p.id);
    }
    if (found.length) {
      const del = await q('POST', `/collections/${col}/points/delete`, { points: found, wait: true });
      console.log(`delete obsolete ABEAR_POL from ${col}: ${del.status} (${found.length} pts)`);
    } else {
      console.log(`delete obsolete ABEAR_POL from ${col}: none found`);
    }
  }
  console.log('\nDONE.');
})().catch(e => { console.error('ERR', e); process.exit(1); });
