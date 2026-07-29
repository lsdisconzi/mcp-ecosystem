/**
 * Pipeline Layer 5 — Deduplication
 * 
 * Two-pass deduplication:
 *   Pass 1 — Exact: group files by SHA-256 (already computed in L0).
 *   Pass 2 — Near: shingle-based Jaccard similarity for text files.
 *             Files with similarity ≥ NEAR_DUP_THRESHOLD are clustered.
 *             The canonical file in each cluster is the largest (most content).
 * 
 * Output per file:
 *   dedup: {
 *     is_exact_duplicate: bool,
 *     is_near_duplicate:  bool,
 *     duplicate_of:       file_ref | null,
 *     cluster_id:         string | null,
 *     canonical:          bool,
 *     similarity_score:   float | null
 *   }
 * 
 * Single Responsibility: determine canonical vs redundant. No extraction here.
 */

'use strict';

const NEAR_DUP_THRESHOLD = 0.82; // Jaccard similarity above this = near-duplicate
const SHINGLE_SIZE       = 3;    // 3-word shingles
const MIN_WORDS_FOR_NEAR = 50;   // skip near-dup check on very short files
const MAX_SHINGLES       = 400;  // cap shingles for large files (performance)

// ─── Shingle Helpers ────────────────────────────────────────────────────────

function normalizeText(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\u00c0-\u024f\s]/g, ' ')  // keep accented chars
    .replace(/\s+/g, ' ')
    .trim();
}

function buildShingles(text) {
  const words = normalizeText(text).split(' ').filter(Boolean);
  if (words.length < SHINGLE_SIZE) return new Set(words);
  const shingles = new Set();
  const step = words.length > MAX_SHINGLES * SHINGLE_SIZE
    ? Math.floor(words.length / MAX_SHINGLES)
    : 1;
  for (let i = 0; i <= words.length - SHINGLE_SIZE; i += step) {
    shingles.add(words.slice(i, i + SHINGLE_SIZE).join('_'));
  }
  return shingles;
}

function jaccardSimilarity(setA, setB) {
  if (setA.size === 0 && setB.size === 0) return 1.0;
  if (setA.size === 0 || setB.size === 0) return 0.0;
  let intersection = 0;
  for (const item of setA) {
    if (setB.has(item)) intersection++;
  }
  const union = setA.size + setB.size - intersection;
  return intersection / union;
}

// ─── Main Export ─────────────────────────────────────────────────────────────

/**
 * @param {Array<{file_ref: string, layers: Object}>} files
 *   Each file must have layers.L0 (sha256, size_bytes) and
 *   layers.L1 (preview, word_count) from earlier pipeline stages.
 * @param {Object} options
 *   - skipNearDuplicates: if true, runs exact-duplicate pass only.
 * @returns {Object} Map of file_ref → dedup result
 */
function runDedup(files, options = {}) {
  const { skipNearDuplicates = false } = options;
  const results = {};

  // ── Pass 1: Exact duplicates ───────────────────────────────────────────────
  const hashGroups = {}; // sha256 → [file_ref, ...]

  for (const file of files) {
    const sha = file.layers?.L0?.sha256;
    if (!sha) continue;
    if (!hashGroups[sha]) hashGroups[sha] = [];
    hashGroups[sha].push(file.file_ref);
  }

  const exactDupOf = {}; // file_ref → canonical_file_ref (for exact dups)

  for (const [sha, group] of Object.entries(hashGroups)) {
    if (group.length <= 1) continue;
    // Canonical = first seen (stable ordering)
    const canonical = group[0];
    for (let i = 1; i < group.length; i++) {
      exactDupOf[group[i]] = canonical;
    }
  }

  const nearDupCanonical = {}; // file_ref → canonical_file_ref
  const clusterIds = {};       // file_ref → cluster_id string
  const nearDupScores = {};    // "refA|||refB" → score
  let clusterCounter = 0;

  if (!skipNearDuplicates) {
    // ── Pass 2: Near-duplicates (text files only, not already exact dups) ───
    const textCandidates = files.filter(f => {
      if (exactDupOf[f.file_ref]) return false; // already exact dup, skip
      const wordCount = f.layers?.L1?.word_count || 0;
      const preview   = f.layers?.L1?.preview || '';
      return wordCount >= MIN_WORDS_FOR_NEAR && preview.length > 0;
    });

    // Build shingle sets — expensive, so only for candidates
    const shingleMap = {}; // file_ref → Set<string>
    for (const file of textCandidates) {
      const text = file.layers?.L1?.preview || '';
      shingleMap[file.file_ref] = buildShingles(text);
    }

    // Union-Find for cluster assignment
    const parent = {};
    function find(x) {
      if (!parent[x]) parent[x] = x;
      if (parent[x] !== x) parent[x] = find(parent[x]);
      return parent[x];
    }
    function union(x, y) {
      const px = find(x), py = find(y);
      if (px !== py) parent[px] = py;
    }

    // O(n²) comparison — acceptable for typical case folders (<5000 text files)
    // For very large sets this should be replaced with LSH
    const refs = textCandidates.map(f => f.file_ref);

    for (let i = 0; i < refs.length; i++) {
      for (let j = i + 1; j < refs.length; j++) {
        const score = jaccardSimilarity(shingleMap[refs[i]], shingleMap[refs[j]]);
        if (score >= NEAR_DUP_THRESHOLD) {
          union(refs[i], refs[j]);
          nearDupScores[`${refs[i]}|||${refs[j]}`] = score;
        }
      }
    }

    // Group by cluster root
    const clusters = {}; // root → [file_ref, ...]
    for (const ref of refs) {
      const root = find(ref);
      if (!clusters[root]) clusters[root] = [];
      clusters[root].push(ref);
    }

    // Determine canonical per near-dup cluster (largest word count wins)
    for (const group of Object.values(clusters)) {
      if (group.length <= 1) continue; // singleton = no near dup

      clusterCounter++;
      const clusterId = `NDUP_${String(clusterCounter).padStart(4, '0')}`;

      // Canonical = file with most words
      const fileObjs = group.map(ref => files.find(f => f.file_ref === ref));
      const canonical = fileObjs.reduce((best, f) => {
        const wc = f?.layers?.L1?.word_count || 0;
        return wc > (best?.layers?.L1?.word_count || 0) ? f : best;
      }, fileObjs[0]);

      for (const ref of group) {
        clusterIds[ref] = clusterId;
        if (ref !== canonical.file_ref) {
          nearDupCanonical[ref] = canonical.file_ref;
        }
      }
    }
  }

  // ── Assemble results ───────────────────────────────────────────────────────
  for (const file of files) {
    const ref = file.file_ref;
    const isExact = !!exactDupOf[ref];
    const isNear  = !!nearDupCanonical[ref];

    // Find best similarity score for near dups
    let simScore = null;
    if (isNear) {
      const canon = nearDupCanonical[ref];
      simScore = nearDupScores[`${ref}|||${canon}`]
              || nearDupScores[`${canon}|||${ref}`]
              || null;
    }

    results[ref] = {
      is_exact_duplicate: isExact,
      is_near_duplicate:  isNear,
      duplicate_of:       exactDupOf[ref] || nearDupCanonical[ref] || null,
      cluster_id:         clusterIds[ref] || null,
      canonical:          !isExact && !isNear,
      similarity_score:   simScore
    };
  }

  // ── Summary stats ──────────────────────────────────────────────────────────
  const stats = {
    total:            files.length,
    exact_duplicates: Object.values(results).filter(r => r.is_exact_duplicate).length,
    near_duplicates:  Object.values(results).filter(r => r.is_near_duplicate && !r.is_exact_duplicate).length,
    near_dup_clusters: clusterCounter,
    canonical_files:  Object.values(results).filter(r => r.canonical).length,
    near_dup_skipped: skipNearDuplicates
  };

  return { results, stats };
}

module.exports = { runDedup };
