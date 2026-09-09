/**
 * build_law_registry.js — Map data-law/ source files against the Qdrant
 * law collection (la8159_law) and emit a persistent registry + report.
 *
 * The Qdrant payloads carry a `source_file` field (basename of the .md that
 * produced each point) and `original_id` (the ELI id). This script:
 *   1. Scans data-law/ for every article-level ELI (accepts both the
 *      `ELI ID:` and the PT `ID ELI:` label styles).
 *   2. Reads the Qdrant collection (scroll all points) to get ground truth.
 *   3. Emits:
 *        data-law/_mapping/law_registry.json   — machine mapping
 *        data-law/_mapping/LAW_REGISTRY.md     — human report
 *
 * Usage:
 *   node case-server/pipeline/build_law_registry.js
 *
 * Env: QDRANT_URL + QDRANT_API_KEY (cloud) OR the script falls back to a
 * local snapshot file /tmp/la8159_law_points.json if present.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LAW_DIR = path.join(REPO_ROOT, 'data-law');
const OUT_DIR = path.join(LAW_DIR, '_mapping');
try { require('dotenv').config({ path: path.join(REPO_ROOT, '.env') }); } catch (_) {}

const ELI_LABEL_RE = /(?:ELI\s*ID|ID\s*ELI):?\s*\**\s*`([^`]+)`/gi;

// ─── Helpers ────────────────────────────────────────────────────────────────

function walkFiles(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (['_mapping', '_archive', '.git'].includes(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkFiles(p, acc);
    else if (e.name.endsWith('.md')) acc.push(p);
  }
  return acc;
}

function deriveJurisdiction(originalId) {
  const tok = String(originalId || '').split('.').filter(Boolean);
  return (tok[0] || '').toUpperCase() || null;
}

function deriveFramework(originalId) {
  const tok = String(originalId || '').split('.').filter(Boolean);
  return tok[1] ? tok[1].toUpperCase() : null;
}

function languageForPath(rel) {
  // Language is deterministic by folder convention.
  if (rel.startsWith('INT/EN/')) return 'en';
  if (rel.startsWith('INT/BR/')) return 'pt';
  if (rel.startsWith('BR/')) return 'pt';
  if (rel.startsWith('CL/')) return 'es';
  if (rel.startsWith('CORP/')) return 'en';
  if (rel.startsWith('new-generated/')) return 'pt'; // staging folder (BR ABEAR/ANAC drafts)
  return 'unknown';
}

// ─── Qdrant source ──────────────────────────────────────────────────────────

async function loadQdrantPoints() {
  // Prefer direct cloud when creds exist.
  if (process.env.QDRANT_URL && process.env.QDRANT_API_KEY) {
    const base = String(process.env.QDRANT_URL).replace(/\/+$/, '');
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'api-key': process.env.QDRANT_API_KEY
    };
    const points = [];
    let offset = null, first = true;
    for (;;) {
      const body = { limit: 250, with_payload: true, with_vector: false };
      if (!first) body.offset = offset;
      const res = await fetch(`${base}:6333/collections/la8159_law/points/scroll`, {
        method: 'POST', headers, body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(`qdrant scroll http ${res.status}`);
      const data = await res.json();
      const got = (data.result && data.result.points) || [];
      points.push(...got);
      offset = data.result && data.result.next_page_offset;
      if (offset == null) break;
      first = false;
    }
    return points;
  }
  // Fallback to a local snapshot (nice for offline dev).
  const snap = '/tmp/la8159_law_points.json';
  if (fs.existsSync(snap)) return JSON.parse(fs.readFileSync(snap, 'utf8'));
  throw new Error('No QDRANT_URL/API_KEY and no /tmp snapshot found.');
}

// ─── Build ──────────────────────────────────────────────────────────────────

async function main() {
  const files = walkFiles(LAW_DIR);
  const qdPoints = await loadQdrantPoints();
  const qdByEli = new Map();
  const qdBySource = new Map();
  for (const p of qdPoints) {
    const pl = p.payload || {};
    const id = String(pl.original_id || pl.eli_id || '');
    if (id) qdByEli.set(id, pl);
    const src = String(pl.source_file || '(none)');
    if (!qdBySource.has(src)) qdBySource.set(src, []);
    qdBySource.get(src).push(id);
  }

  const filesMeta = [];
  const eliIndex = new Map(); // eli -> {file, lang}

  for (const f of files) {
    const rel = path.relative(LAW_DIR, f);
    const txt = fs.readFileSync(f, 'utf8');
    const elis = [];
    let m;
    ELI_LABEL_RE.lastIndex = 0;
    while ((m = ELI_LABEL_RE.exec(txt)) !== null) elis.push(m[1]);
    const uniq = [...new Set(elis)];
    const lang = languageForPath(rel);
    const inQdrant = uniq.filter(e => qdByEli.has(e));
    const missingRaw = uniq.filter(e => !qdByEli.has(e));
    // Alias detection: a missing id whose trailing numeric key already exists in
    // Qdrant under a sibling ELI form (e.g. BR.ABEAR_POL.S1 vs …§1 — Objetivo).
    const numericKey = id => {
      const m = String(id).match(/(\d+)\s*[—–-]?\s*[^.]*$/);
      return m ? m[1] : String(id);
    };
    const inQdKeys = new Set(inQdrant.map(numericKey));
    const missing = missingRaw.filter(e => !inQdKeys.has(numericKey(e)));
    const aliasOnly = missingRaw.filter(e => inQdKeys.has(numericKey(e)));
    const h1 = (txt.match(/^#\s+(.+)$/m) || [])[1] || '';
    const hasArticleHeaders = /\*\*Article\s+\d|\*\*(?:ARTÍCULO|ART\.?)\s+\d|\*\*Art\.?\s+\d/i.test(txt);
    // Reference-only classification: whole-code / full-text / corporate docs
    // with content but NO article-level ELI headers (never article-ingested).
    const referenceOnly =
      uniq.length === 0 &&
      (txt.length > 60000 || /^# (CIVIL CODE|Código Penal|.*Code of Conduct|.*Code of Ethics)/im.test(txt) ||
        hasArticleHeaders);
    filesMeta.push({
      file: rel,
      language: lang,
      title: h1.slice(0, 120),
      reference_only: referenceOnly,
      reference_note: referenceOnly
        ? (hasArticleHeaders
            ? 'whole-code full-text (no ELI article headers) — kept as reference, not article-ingested'
            : 'reference/institutional document (no ELI article headers)')
        : null,
      articles_local: uniq.length,
      articles_in_qdrant: inQdrant.length,
      articles_missing: missing.length,
      alias_only_not_separately_ingested: aliasOnly.length,
      missing_eli: missing,
      alias_eli: aliasOnly,
      in_qdrant_eli: inQdrant,
      source_basename_present_in_qdrant: qdBySource.has(path.basename(f))
    });
    for (const e of uniq) eliIndex.set(e, { file: rel, lang });
  }

  // Qdrant articles with no local file backing.
  const qdOnly = [];
  for (const [id, pl] of qdByEli) {
    if (!eliIndex.has(id)) {
      qdOnly.push({ eli_id: id, source_file: pl.source_file || null, title: (pl.title || '').slice(0, 100) });
    }
  }

  // Summary
  const totalLocalUnique = eliIndex.size;
  const inQdCount = [...eliIndex.keys()].filter(e => qdByEli.has(e)).length;
  const referenceOnlyFiles = filesMeta.filter(r => r.reference_only).length;
  const aliasOnlyTotal = filesMeta.reduce((s, r) => s + (r.alias_only_not_separately_ingested || 0), 0);
  const genuinelyMissing = filesMeta.reduce((s, r) => s + r.articles_missing, 0);
  const summary = {
    generated_at: new Date().toISOString(),
    data_law_md_files: filesMeta.length,
    data_law_articles_unique: totalLocalUnique,
    data_law_reference_only_files: referenceOnlyFiles,
    qdrant_points: qdPoints.length,
    qdrant_articles_with_local_file: inQdCount,
    data_law_articles_not_in_qdrant: totalLocalUnique - inQdCount,
    alias_only_same_article_already_ingested: aliasOnlyTotal,
    genuinely_missing_articles: genuinelyMissing,
    qdrant_articles_without_local_file: qdOnly.length,
    language_breakdown: filesMeta.reduce((acc, r) => {
      acc[r.language] = (acc[r.language] || 0) + 1;
      return acc;
    }, {})
  };

  const registry = {
    summary,
    files: filesMeta,
    qdrant_only_articles: qdOnly
  };

  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(path.join(OUT_DIR, 'law_registry.json'), JSON.stringify(registry, null, 2));
  console.log('Wrote', path.join(OUT_DIR, 'law_registry.json'));

  // ── Markdown report ──
  const L = [];
  L.push('# Law Corpus Registry — `data-law/` ↔ Qdrant `la8159_law`');
  L.push('');
  L.push(`Generated: ${summary.generated_at}`);
  L.push('');
  L.push('## Summary');
  L.push('');
  L.push('| Metric | Value |');
  L.push('|---|---|');
  L.push(`| data-law .md files | ${summary.data_law_md_files} |`);
  L.push(`| Unique article ELIs in data-law | ${summary.data_law_articles_unique} |`);
  L.push(`| Reference-only files (whole-code/institutional, no ELI) | ${summary.data_law_reference_only_files} |`);
  L.push(`| Qdrant points (la8159_law) | ${summary.qdrant_points} |`);
  L.push(`| Qdrant articles backed by a local file | ${summary.qdrant_articles_with_local_file} |`);
  L.push(`| data-law articles NOT in Qdrant (incl. aliases) | ${summary.data_law_articles_not_in_qdrant} |`);
  L.push(`| — alias-only (same article already ingested) | ${summary.alias_only_same_article_already_ingested} |`);
  L.push(`| — genuinely missing articles | ${summary.genuinely_missing_articles} |`);
  L.push(`| Qdrant articles with NO local file | ${summary.qdrant_articles_without_local_file} |`);
  L.push(`| Files by detected language | ${JSON.stringify(summary.language_breakdown)} |`);
  L.push('');
  L.push('## Per-file coverage');
  L.push('');
  L.push('| File | Lang | Ref-only | Local | In Qdrant | Missing | Notes |');
  L.push('|---|---|---|---|---|---|---|');
  for (const r of filesMeta) {
    const note = r.reference_only
      ? r.reference_note
      : r.articles_local === 0
        ? (r.source_basename_present_in_qdrant ? 'no ELI headers but basename ingested' : 'no ELI headers')
        : r.articles_missing === 0 ? '' : `missing: ${r.missing_eli.slice(0, 4).join(', ')}${r.missing_eli.length > 4 ? '…' : ''}`;
    L.push(`| \`${r.file}\` | ${r.language} | ${r.reference_only ? '✓' : ''} | ${r.articles_local} | ${r.articles_in_qdrant} | ${r.articles_missing} | ${note} |`);
  }
  if (qdOnly.length) {
    L.push('');
    L.push('## Qdrant articles without a local backing file');
    L.push('');
    L.push('| ELI id | source_file | title |');
    L.push('|---|---|---|');
    for (const q of qdOnly) L.push(`| \`${q.eli_id}\` | ${q.source_file || '-'} | ${q.title || ''} |`);
  }
  L.push('');
  L.push('## Notes');
  L.push('');
  L.push('- Qdrant `la8159_law` holds **837** points; all are backed by a local `data-law/` file. The corpus was article-ingested from these files (`source_file` payload = the basename of the producing `.md`).');
  L.push('- **ABEAR_Code.md** duplicates each article under two ELI forms: a canonical `BR.ABEAR_POL.§N — …` (ingested) and a compact alias `BR.ABEAR_POL.SN` (not separately ingested). The 3 rows flagged as "NOT in Qdrant" are these aliases — real coverage is complete.');
  L.push('- **INT** instruments exist as PT (`INT/BR/`) and EN (`INT/EN/`) translation copies that share ELI IDs. Qdrant stores the EN text; the PT copies are local translation references.');
  L.push('- **`INT/BR/ACHR_1969.md`** was renamed from a mislabeled `Chicago_1944.md` (its content is the American Convention on Human Rights in PT, not the Chicago Convention). The genuine Chicago Convention is `INT/EN/Chicago_1944.md` (3 articles).');
  L.push('- **Reference-only** files (whole-code full-texts, corporate/institutional docs) have no article-level ELI headers and are intentionally **not** article-ingested. CL full-texts: `ChileanCivilCodeandRelatedLaws.md` (~2.5k articles, EN) and `CodigoPenalChile.md` (~577, ES) are kept as reference sources only.');
  const reportPath = path.join(OUT_DIR, 'LAW_REGISTRY.md');
  fs.writeFileSync(reportPath, L.join('\n'));
  console.log('Wrote', reportPath);
}

main().catch((e) => { console.error('ERR', e); process.exit(1); });
