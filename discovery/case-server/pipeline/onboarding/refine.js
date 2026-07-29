/**
 * Discovery — Onboarding · Refine
 *
 * Produces blueprint v2 by reading what's actually in the corpus and
 * annotating / extending the v1 tree.
 *
 * Inputs: the v1 blueprint plus a `signals` bundle:
 *   { files:    [{file, fileName, category, kind, contentGroup, ...}],
 *     stats:    /api/pipeline/stats payload (optional),
 *     comprehend: /api/comprehend/groups payload (optional) }
 *
 * Heuristics (in order of strength):
 *   1. Path containment — file already lives inside a v1 folder.
 *   2. Category → tag/hint match against node tags + pipeline_hints.
 *   3. Filename token overlap with node.path or node.expected_contents.
 *
 * Files that match no node become "orphans" and are gathered under a new
 * top-level UNCLASSIFIED branch, grouped by category. Existing nodes are
 * never deleted at this stage — empty ones get `corpus_match_count: 0`
 * so the user can decide in P4.
 */

function deepClone(x) { return JSON.parse(JSON.stringify(x)); }

function flattenBlueprint(bp) {
  const out = [];
  function walk(node, parentPath, depth) {
    const fullPath = parentPath ? `${parentPath}/${node.path}` : node.path;
    out.push({ fullPath, parentPath, depth, node });
    if (Array.isArray(node.children)) {
      for (const c of node.children) walk(c, fullPath, depth + 1);
    }
  }
  for (const n of bp.nodes) walk(n, "", 0);
  return out;
}

function tokenize(s) {
  return String(s || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 2);
}

function intersects(a, b) {
  const set = new Set(a);
  for (const x of b) if (set.has(x)) return true;
  return false;
}

function nodeKeywords(node) {
  const out = new Set();
  for (const t of tokenize(node.path)) out.add(t);
  for (const tag of node.tags || []) for (const t of tokenize(tag)) out.add(t);
  for (const ec of node.expected_contents || []) for (const t of tokenize(ec)) out.add(t);
  const hints = node.pipeline_hints || {};
  for (const ep of hints.entity_priorities || []) for (const t of tokenize(ep)) out.add(t);
  for (const f of hints.intelligence_focus || []) for (const t of tokenize(f)) out.add(t);
  return out;
}

/**
 * Pick the best-matching node for a file.
 * Returns { node, fullPath, score, reason } or null.
 */
function classifyFileToNode(file, flatNodes) {
  const filePath = String(file.file || "").replace(/\\/g, "/");
  if (!filePath) return null;

  // 1. Path containment — pick the deepest node whose fullPath is a prefix.
  const prefixHits = flatNodes
    .filter(({ fullPath }) => fullPath && (filePath === fullPath || filePath.startsWith(fullPath + "/")))
    .sort((a, b) => b.fullPath.length - a.fullPath.length);
  if (prefixHits.length) {
    const top = prefixHits[0];
    return { node: top.node, fullPath: top.fullPath, score: 1.0, reason: "path-contained" };
  }

  // Build the candidate signal: filename tokens + category + kind + contentGroup.
  const fileTokens = new Set([
    ...tokenize(file.fileName || ""),
    ...tokenize(file.file || ""),
    ...tokenize(file.category || ""),
    ...tokenize(file.kind || ""),
    ...tokenize(file.contentGroup || ""),
  ]);

  let best = null;
  for (const entry of flatNodes) {
    const kw = nodeKeywords(entry.node);
    if (!kw.size) continue;
    let score = 0;
    let hits = 0;
    for (const t of fileTokens) if (kw.has(t)) hits++;
    if (!hits) continue;
    // Weight: more hits = better; deeper node = slightly better (more specific).
    score = hits + entry.depth * 0.1;
    if (!best || score > best.score) {
      best = { node: entry.node, fullPath: entry.fullPath, score, reason: `keyword-match(${hits})` };
    }
  }
  if (best && best.score >= 1) return best;
  return null;
}

function annotateNode(node, count, samples) {
  node.corpus_match_count = count;
  if (samples && samples.length) node.corpus_sample_files = samples.slice(0, 5);
  else delete node.corpus_sample_files;
}

function buildUnclassifiedNode(orphans) {
  if (!orphans.length) return null;
  const byCategory = new Map();
  for (const f of orphans) {
    const cat = String(f.category || "general") || "general";
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat).push(f);
  }
  const children = [];
  for (const [cat, files] of byCategory) {
    children.push({
      path: cat || "general",
      purpose: `${files.length} file(s) classified as "${cat}" but not yet routed to a blueprint folder.`,
      required: false,
      tags: ["unclassified", `category:${cat}`],
      corpus_match_count: files.length,
      corpus_sample_files: files.slice(0, 5).map((f) => f.fileName || f.file),
    });
  }
  return {
    path: "UNCLASSIFIED",
    purpose: `Refinement could not place ${orphans.length} file(s). Move them into the right folders during P4.`,
    required: false,
    tags: ["unclassified"],
    corpus_match_count: orphans.length,
    children,
  };
}

/**
 * Refine v1 → v2.
 * @param {object} v1
 * @param {object} signals - { files: [...], stats?: {...}, comprehend?: {...} }
 * @returns {{ v2, diff, stats }}
 */
/**
 * Should this file be excluded from refinement counting?
 * - Auto-generated README.md files at every materialized blueprint folder.
 * - Discovery's own metadata files under .discovery/ and _intelligence/.
 */
function isSkeletonArtifact(file, v1FullPaths) {
  const filePath = String(file.file || "").replace(/\\/g, "/");
  if (!filePath) return true;
  if (filePath.startsWith(".discovery/") || filePath.startsWith("_intelligence/")) return true;
  if ((file.fileName || "").toLowerCase() === "readme.md") {
    const parent = filePath.replace(/\/[^/]+$/, "");
    if (v1FullPaths.has(parent)) return true;
  }
  return false;
}

function refineBlueprint(v1, signals) {
  if (!v1 || !Array.isArray(v1.nodes)) {
    throw new Error("refineBlueprint: v1 blueprint required");
  }
  const v2 = deepClone(v1);
  v2.spec_version = "1.0.0";
  v2.blueprint_version = "v2";
  v2.generated_at = new Date().toISOString();

  const signalsUsed = ["pipeline_stats"];
  if (signals.comprehend) signalsUsed.push("comprehend_groups");

  v2.source = {
    kind: "corpus_refinement",
    template_id: (v1.source && v1.source.template_id) || undefined,
    intake_spec_ref: (v1.source && v1.source.intake_spec_ref) || undefined,
    previous_blueprint_ref: ".discovery/tree_blueprint.v1.json",
    corpus_signals_used: signalsUsed,
  };

  const flatV2 = flattenBlueprint(v2);
  const v1FullPaths = new Set(flattenBlueprint(v1).map((x) => x.fullPath));
  const counts = new Map();   // fullPath -> count
  const samples = new Map();  // fullPath -> [filename]
  const orphans = [];
  let skipped = 0;

  const allFiles = Array.isArray(signals.files) ? signals.files : [];
  const files = allFiles.filter((f) => {
    if (isSkeletonArtifact(f, v1FullPaths)) { skipped++; return false; }
    return true;
  });
  for (const file of files) {
    const m = classifyFileToNode(file, flatV2);
    if (m) {
      counts.set(m.fullPath, (counts.get(m.fullPath) || 0) + 1);
      const arr = samples.get(m.fullPath) || [];
      if (arr.length < 5) arr.push(file.fileName || file.file);
      samples.set(m.fullPath, arr);
    } else {
      orphans.push(file);
    }
  }

  for (const { fullPath, node } of flatV2) {
    const c = counts.get(fullPath) || 0;
    annotateNode(node, c, samples.get(fullPath));
  }

  const unclassified = buildUnclassifiedNode(orphans);
  if (unclassified) v2.nodes.push(unclassified);

  const populatedNodes = [...counts.values()].filter((c) => c > 0).length;
  const totalV1Nodes = flatV2.length;
  const noteParts = [
    `Refined from ${files.length} file(s) on ${v2.generated_at}.`,
    `${populatedNodes}/${totalV1Nodes} v1 node(s) had matches.`,
  ];
  if (orphans.length) noteParts.push(`${orphans.length} file(s) routed to UNCLASSIFIED.`);
  v2.notes = noteParts.join(" ");

  const diff = diffBlueprints(v1, v2);
  return {
    v2,
    diff,
    stats: {
      total_files: files.length,
      skeleton_artifacts_skipped: skipped,
      populated_v1_nodes: populatedNodes,
      empty_v1_nodes: totalV1Nodes - populatedNodes,
      orphan_count: orphans.length,
    },
  };
}

function diffBlueprints(v1, v2) {
  const v1Flat = flattenBlueprint(v1);
  const v2Flat = flattenBlueprint(v2);
  const v1Paths = new Set(v1Flat.map((x) => x.fullPath));
  const v2Paths = new Set(v2Flat.map((x) => x.fullPath));

  const added = [];
  const annotated = [];
  for (const { fullPath, node } of v2Flat) {
    if (!v1Paths.has(fullPath)) {
      added.push({ path: fullPath, purpose: node.purpose, corpus_match_count: node.corpus_match_count || 0 });
    } else if (typeof node.corpus_match_count === "number") {
      annotated.push({ path: fullPath, corpus_match_count: node.corpus_match_count });
    }
  }
  const removed = v1Flat
    .map((x) => x.fullPath)
    .filter((p) => !v2Paths.has(p))
    .map((p) => ({ path: p }));

  return {
    added,
    removed,
    annotated_count: annotated.length,
    empty_paths: annotated.filter((a) => a.corpus_match_count === 0).map((a) => a.path),
    populated_paths: annotated.filter((a) => a.corpus_match_count > 0).map((a) => a.path),
  };
}

module.exports = {
  flattenBlueprint,
  classifyFileToNode,
  refineBlueprint,
  diffBlueprints,
};
