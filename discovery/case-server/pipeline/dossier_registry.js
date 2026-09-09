/**
 * dossier_registry.js — Local law/violation registry built from the dossier library
 *
 * The `violations/` corpus (BR-*, CL-*, INT-*) contains curated legal dossiers.
 * Confirmed roles (decision #1): these are BOTH
 *   (a) the grounding reference for law resolution, and
 *   (b) the expected outputs the pipeline should reproduce.
 *
 * This module indexes them into a local, serializable registry so that:
 *   - L6 law resolution can resolve transcript `violations_cited` codes locally
 *     (no Qdrant/Neo4j required), and
 *   - an evaluation/coverage pass can measure how well the transcripts and the
 *     registry agree (decision #5 eval harness).
 *
 * Trust tiers (decision #3): only confidence>0 + verbatim legal basis (Tier A)
 * may anchor "established" citations; confidence==0 dossiers are candidate-only.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const {
  decodeLegalDossier,
  normalizeLawCode,
  isExcludedRelativePath
} = require('./document_decode');

/**
 * Read and decode one dossier file.
 * @returns {object|null} decoded entry (see decodeLegalDossier().entry)
 */
function readDossierEntry(absPath, fileRef) {
  try {
    const text = fs.readFileSync(absPath, 'utf8');
    const parsed = JSON.parse(text);
    const { entry } = decodeLegalDossier(parsed, fileRef);
    return entry;
  } catch (err) {
    return {
      code: fileRef,
      title: '(unreadable dossier)',
      error: err.message,
      jurisdiction: null,
      case_ids: [],
      legal_basis: [],
      trust_tier: 'C'
    };
  }
}

/**
 * Gather dossier entries from a list of pipeline store file records.
 * A record is a dossier when its L1.structured_kind is 'legal_dossier'
 * (or, for legacy stores, its content parses as one).
 *
 * @param {Array<object>} allFiles  - Object.values(store.getAllFiles())
 * @param {string} rootDir          - Absolute workspace root
 * @returns {Promise<Array<object>>} decoded entries (with file_ref)
 */
async function gatherDossierEntries(allFiles, rootDir) {
  const out = [];
  for (const rec of allFiles || []) {
    const rel = rec.file_ref;
    if (!rel || isExcludedRelativePath(rel)) continue;
    const kind = rec.layers?.L1?.structured_kind || rec.layers?.L1?.structured?.kind;
    if (kind === 'legal_dossier') {
      const abs = path.resolve(rootDir, rel);
      const entry = readDossierEntry(abs, rel);
      out.push({ ...entry, file_ref: rel });
    }
  }
  return out;
}

/**
 * Build a registry (indexed by normalized code) from dossier entries.
 */
function buildRegistry(entries) {
  const byCode = {};
  const byCase = {};
  const byJurisdiction = {};
  const byTier = { A: 0, B: 0, C: 0 };

  for (const entry of entries) {
    const code = normalizeLawCode(entry.code);
    if (code) byCode[code] = entry;

    const tier = entry.trust_tier || 'C';
    byTier[tier] = (byTier[tier] || 0) + 1;

    const jur = entry.jurisdiction || '?';
    byJurisdiction[jur] = (byJurisdiction[jur] || 0) + 1;

    for (const cid of entry.case_ids || []) {
      if (!byCase[cid]) byCase[cid] = [];
      if (!byCase[cid].includes(code)) byCase[cid].push(code);
    }
  }

  return { total: entries.length, byCode, byCase, byJurisdiction, byTier };
}

function findDossier(registry, code) {
  const normalized = normalizeLawCode(code);
  if (!normalized) return null;
  return registry.byCode[normalized] || null;
}

/**
 * Coverage/evaluation pass (S5, decision #1 = both).
 * Compares codes cited by the evidence transcripts against the available
 * dossier registry. Only canonical codes (CL-### / BR-### / INT-###) are
 * matched; long-form descriptive citations (e.g. "LPDC Art. 3(b) — …") are
 * counted separately so they don't distort the coverage ratio.
 *
 * @param {Array<object>} transcriptFiles - store records for evidence files
 * @param {object} registry
 */
function buildDossierCoverage(transcriptFiles, registry) {
  const citedByFile = {};
  const codedCited = new Set();
  const otherCited = new Set();
  const CODED_RE = /^(CL|BR|INT)-\d+$/i;

  for (const rec of transcriptFiles || []) {
    const cited = rec.layers?.L1?.structured?.violations_cited || [];
    const coded = [];
    const others = [];
    for (const raw of cited) {
      const norm = normalizeLawCode(raw);
      if (!norm) continue;
      if (CODED_RE.test(norm)) coded.push(norm);
      else others.push(norm);
    }
    const distinctCoded = [...new Set(coded)];
    if (distinctCoded.length || others.length) {
      citedByFile[rec.file_ref] = { coded: distinctCoded, other: others };
    }
    for (const c of distinctCoded) codedCited.add(c);
    for (const c of others) otherCited.add(c);
  }

  const covered = [];
  const missing = [];
  for (const code of codedCited) {
    const dossier = registry.byCode[code];
    if (dossier) {
      covered.push({ code, title: dossier.title, tier: dossier.trust_tier, confidence: dossier.confidence?.value });
    } else {
      missing.push({ code });
    }
  }

  // Dossiers not referenced by any canonical transcript code in this run.
  const uncitedDossiers = Object.keys(registry.byCode)
    .filter(code => !codedCited.has(code))
    .map(code => ({ code, title: registry.byCode[code].title, tier: registry.byCode[code].trust_tier }))
    .sort((a, b) => a.code.localeCompare(b.code));

  return {
    transcripts_with_citations: Object.keys(citedByFile).length,
    cited_codes_total: codedCited.size,
    other_descriptive_citations: otherCited.size,
    covered_by_dossier: covered.length,
    missing_dossier: missing.length,
    uncited_dossiers: uncitedDossiers.length,
    citations: { covered, missing },
    uncited_dossiers_list: uncitedDossiers.slice(0, 500),
    by_file: citedByFile
  };
}

function writeRegistryFiles(registry, coverage, outputDir) {
  const registryPath = path.join(outputDir, 'law_dossier_registry.json');
  const coveragePath = path.join(outputDir, 'dossier_coverage.json');
  fs.writeFileSync(registryPath, JSON.stringify({
    total: registry.total,
    by_case: registry.byCase,
    by_jurisdiction: registry.byJurisdiction,
    by_tier: registry.byTier,
    entries: Object.values(registry.byCode).map(e => ({
      code: e.code,
      title: e.title,
      jurisdiction: e.jurisdiction,
      case_ids: e.case_ids,
      severity: e.severity,
      category: e.category,
      is_seed: e.is_seed,
      has_broken_refs: e.has_broken_refs,
      trust_tier: e.trust_tier,
      confidence: e.confidence,
      legal_basis: (e.legal_basis || []).map(b => ({
        article_id: b.article_id,
        article_name: b.article_name,
        status: b.status,
        applicability: b.applicability,
        has_verbatim_text: Boolean(b.verbatim_text)
      })),
      element_grid_keys: (e.element_grid_keys || []).slice(0, 40),
      related_violations: (e.related_violations || []).slice(0, 20)
    }))
  }, null, 2));
  fs.writeFileSync(coveragePath, JSON.stringify(coverage, null, 2));
  return { registry: registryPath, coverage: coveragePath };
}

module.exports = {
  readDossierEntry,
  gatherDossierEntries,
  buildRegistry,
  findDossier,
  buildDossierCoverage,
  writeRegistryFiles
};
