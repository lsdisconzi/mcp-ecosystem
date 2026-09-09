/**
 * dossier_code_resolver.js — code → legal provisions / frameworks (Layer 6 helper)
 *
 * Violation dossier codes (CL-014, BR-001, INT-003, …) are NOT legal provisions:
 * they are internal codes whose legal grounding lives in each dossier's
 * `legal_basis` array (e.g. "CL.CACH.Art.133" + verbatim text). This module lets
 * L6 normalization expand a cited code into real, resolved law references so the
 * case graph gains LegalArticle + LegalFramework nodes and the narrative reports
 * actual provisions/frameworks instead of "0 legal provisions / 0 frameworks".
 *
 * Two sources are merged:
 *   - a static SEED (data/dossier_code_index.json) generated once from the
 *     82-dossier library — this makes single-transcript runs resolve even when
 *     the dossiers are not uploaded to the session; and
 *   - the runtime dossier registry (byCode) when dossiers ARE present.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { normalizeLawCode } = require('./document_decode');

const SEED_PATH = path.join(__dirname, 'data', 'dossier_code_index.json');

let seedCache = null;
function loadSeed() {
  if (seedCache !== null) return seedCache;
  seedCache = {};
  try {
    const raw = JSON.parse(fs.readFileSync(SEED_PATH, 'utf8'));
    seedCache = raw.codes || raw || {};
  } catch {
    seedCache = {};
  }
  return seedCache;
}

// Human-readable framework names by the framework segment of an ELI-ish article
// id (the token right after the jurisdiction, e.g. "CACH" in "CL.CACH.Art.133").
const FRAMEWORK_NAMES = {
  // Chile
  CACH: 'Código Aeronáutico de Chile',
  L16752: 'Ley 16.752 (DGAC Chile)',
  L18575: 'Ley 18.575 (Bases Generales de la Administración)',
  CONST: 'Constitución Política de Chile',
  LPDC: 'Ley 19.496 (Protección de los Derechos del Consumidor)',
  CHIPENCOD: 'Código Penal de Chile',
  DFL221: 'DFL Nº 221 — Ley de Navegación Aérea',
  DGAC: 'Regulamentación DGAC Chile',
  // Brazil
  CDC: 'Código de Defesa do Consumidor',
  CF88: 'Constituição Federal de 1988',
  CBA: 'Código Brasileiro de Aeronáutica',
  LEI7565: 'Lei 7.565/1986 (Código Brasileiro de Aeronáutica)',
  LEI8078: 'Lei 8.078/1990 (Código de Defesa do Consumidor)',
  ANAC400: 'Resolução ANAC nº 400',
  ANAC280: 'Resolução ANAC nº 280',
  R400: 'Resolução ANAC nº 400',
  CP: 'Código Penal Brasileiro',
  // International
  ICAO: 'ICAO Standards (Annex 9)',
  MC99: 'Montreal Convention 1999',
  WC29: 'Warsaw Convention 1929',
  EC261: 'EC Regulation 261/2004'
};

/**
 * Parse an article id ("CL.CACH.Art.133", "BR.CDC.T4.C2.Art.14",
 * "CL.LPDC.Art.3.b", "CL.CONST.T1.C3.P3.Art.19.4") into parts.
 */
function parseArticleId(articleId) {
  const s = String(articleId || '').trim();
  if (!s) return null;
  const tokens = s.split('.').filter(Boolean);
  if (tokens.length < 2) return null;
  const jurisdiction = String(tokens[0]).toUpperCase();
  const frameworkCode = String(tokens[1]).toUpperCase();
  const artIdx = tokens.findIndex(t => /^art$/i.test(t));
  const articleHint = artIdx >= 0
    ? tokens.slice(artIdx + 1).join('.')
    : tokens.slice(2).join('.');
  return {
    jurisdiction,
    frameworkCode,
    frameworkName: FRAMEWORK_NAMES[frameworkCode] || frameworkCode,
    articleHint: articleHint || null
  };
}

function normalizeBasis(legalBasis) {
  if (!Array.isArray(legalBasis)) return [];
  return legalBasis
    .filter(b => b && typeof b === 'object' && b.article_id)
    .map(b => ({
      article_id: String(b.article_id).trim(),
      article_name: b.article_name || null,
      status: b.status || null,
      applicability: b.applicability || null,
      verbatim_text: (b.verbatim_text || '') ? String(b.verbatim_text).slice(0, 4000) : null
    }));
}

function normalizeIndexEntry(code, entry) {
  return {
    code: normalizeLawCode(code),
    jurisdiction: entry.jurisdiction || null,
    case_ids: entry.case_ids || [],
    severity: entry.severity || null,
    category: entry.category || null,
    title: entry.title || code,
    trust_tier: entry.trust_tier || 'C',
    legal_basis: normalizeBasis(entry.legal_basis)
  };
}

/**
 * Build the merged code index: seed first, then runtime dossier registry (byCode)
 * overrides/adds entries.
 * @param {Object} [runtimeByCode] - dossier_registry byCode (code -> dossier entry)
 */
function buildIndex(runtimeByCode) {
  const index = { ...loadSeed() };
  if (runtimeByCode && typeof runtimeByCode === 'object') {
    for (const [code, entry] of Object.entries(runtimeByCode)) {
      if (!entry) continue;
      const key = normalizeLawCode(code);
      if (key) index[key] = normalizeIndexEntry(code, entry);
    }
  }
  return index;
}

/**
 * Turn one dossier legal-basis item into a resolved law reference for L6.
 */
function toResolvedLawRef(code, basis, dossierEntry) {
  const parts = parseArticleId(basis.article_id);
  const jurisdiction = parts ? parts.jurisdiction : (dossierEntry.jurisdiction || null);
  const frameworkCode = parts ? parts.frameworkCode : null;
  const frameworkName = parts ? parts.frameworkName : (frameworkCode || 'other');
  const articleHint = parts ? parts.articleHint : null;
  return {
    raw_text: code,
    framework_code: frameworkCode || 'UNKNOWN',
    framework_name: frameworkName,
    jurisdiction: jurisdiction || 'other',
    article_hint: articleHint,
    eli_id: basis.article_id,
    article_text: basis.verbatim_text || null,
    resolved: true,
    needs_argus: false,
    article_name: basis.article_name || null,
    enriched_from: 'dossier_code_index'
  };
}

/**
 * Expand a violation's raw law references: bare dossier codes (CL-014, …) that
 * exist in the index become one resolved law ref PER legal-basis provision.
 * Everything else passes through unchanged.
 * @param {Array} refs - violation._law_references
 * @param {Object} index - buildIndex() result
 * @returns {Array} expanded refs (mixed: resolved dossier refs + original raw refs)
 */
function expandRefs(refs, index) {
  if (!Array.isArray(refs)) return [];
  const out = [];
  for (const raw of refs) {
    if (!raw || typeof raw !== 'object') continue;
    if (raw.eli_id) { out.push(raw); continue; } // already resolved
    const code = normalizeLawCode(raw.raw_text || raw.code || '');
    if (code && /^(CL|BR|INT)-\d+$/i.test(code) && index[code]) {
      const dossier = index[code];
      const basis = normalizeBasis(dossier.legal_basis);
      if (basis.length === 0) {
        out.push(raw); // no provision map available — keep raw for review
      } else {
        for (const b of basis) out.push(toResolvedLawRef(code, b, dossier));
      }
    } else {
      out.push(raw);
    }
  }
  return out;
}

module.exports = {
  buildIndex,
  expandRefs,
  parseArticleId,
  toResolvedLawRef,
  FRAMEWORK_NAMES,
  SEED_PATH
};
