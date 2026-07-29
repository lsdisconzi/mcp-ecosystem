/**
 * Discovery — Onboarding · Full run (P6)
 *
 * Materializes the (edited) blueprint v2 at the user-chosen destination
 * root, then COPIES files from the session workspace into the destination
 * tree according to the v2 layout. The session workspace is preserved as
 * a snapshot — nothing is moved or deleted.
 *
 * Renames between v1 (on disk) and v2 (after user edits) are resolved via
 * `plan.guardrails.renamed_paths`: a file whose source path begins with a
 * v1 segment that was renamed has its target path rewritten before
 * classification fallback runs.
 *
 * This MVP performs only the structural commit. LLM-driven layer execution
 * is left to the existing /api/intelligence/run + /api/comprehend/run
 * endpoints — the user (or an agent) can invoke them against the new
 * destination after this step succeeds.
 */

const fs = require("fs");
const path = require("path");

function clientError(message, statusCode = 400) {
  const err = new Error(message);
  err.statusCode = statusCode;
  return err;
}

/** Build a Map<old_path_prefix, new_path_prefix> from guardrail renames. */
function renameMap(plan) {
  const m = new Map();
  if (plan && plan.guardrails && Array.isArray(plan.guardrails.renamed_paths)) {
    for (const r of plan.guardrails.renamed_paths) {
      if (r && r.from && r.to && r.from !== r.to) m.set(r.from, r.to);
    }
  }
  // Sort by length desc so longest prefixes win.
  return new Map([...m.entries()].sort((a, b) => b[0].length - a[0].length));
}

function applyRenames(srcPath, renames) {
  for (const [from, to] of renames) {
    if (srcPath === from) return to;
    if (srcPath.startsWith(from + "/")) return to + srcPath.slice(from.length);
  }
  return srcPath;
}

function joinNodeWithRelative(nodePath, relPath) {
  const nodeSeg = String(nodePath || "").split("/").filter(Boolean);
  const relSeg = String(relPath || "").split("/").filter(Boolean);
  if (!nodeSeg.length) return relSeg.join("/");
  if (!relSeg.length) return nodeSeg.join("/");

  // Collapse overlap where relPath starts with the same segment sequence
  // that nodePath already ends with (e.g. UNCLASSIFIED/process + process/x).
  let overlap = 0;
  const max = Math.min(nodeSeg.length, relSeg.length);
  for (let k = 1; k <= max; k++) {
    let same = true;
    for (let i = 0; i < k; i++) {
      if (nodeSeg[nodeSeg.length - k + i] !== relSeg[i]) {
        same = false;
        break;
      }
    }
    if (same) overlap = k;
  }

  const tail = relSeg.slice(overlap);
  if (!tail.length) return nodeSeg.join("/");
  return `${nodeSeg.join("/")}/${tail.join("/")}`;
}

/** Walk the workspace and yield file metadata, skipping scaffolding. */
function* walkWorkspaceFiles(workspaceRoot) {
  const stack = [{ abs: workspaceRoot, rel: "" }];
  const skipDirs = new Set([".discovery", "_intelligence", "node_modules", ".git"]);
  while (stack.length) {
    const cur = stack.pop();
    let entries;
    try { entries = fs.readdirSync(cur.abs, { withFileTypes: true }); }
    catch (_) { continue; }
    for (const ent of entries) {
      if (ent.name.startsWith(".") && ent.name !== ".discovery") continue;
      const abs = path.join(cur.abs, ent.name);
      const rel = cur.rel ? `${cur.rel}/${ent.name}` : ent.name;
      if (ent.isDirectory()) {
        if (skipDirs.has(ent.name)) continue;
        stack.push({ abs, rel });
      } else if (ent.isFile()) {
        if (ent.name === "README.md") continue; // skeleton scaffolding
        if (ent.name === "DS_Store" || ent.name === ".DS_Store") continue; // macOS metadata
        yield { abs, rel, name: ent.name };
      }
    }
  }
}

/**
 * Decide a destination relative path for a given source file.
 * Strategy:
 *   1. Apply guardrail renames to the source rel path.
 *   2. Classify the (renamed) file against the v2 flat-node set:
 *      - if path-contained, keep the renamed path under the same v2 subtree
 *      - otherwise, preserve the renamed relative path under the selected node
 *   3. If classification fails, mirror the renamed path under UNCLASSIFIED/loose
 */
function decideTargetPath({ srcRel, renames, classifyToNode, flatNodes }) {
  const renamed = applyRenames(srcRel, renames);
  const fileSig = { file: renamed, fileName: path.basename(renamed) };
  const cls = classifyToNode(fileSig, flatNodes);
  if (cls && cls.fullPath) {
    // If the renamed source is already prefix-contained in a node, keep its
    // relative tail under that node so subdir structure is preserved.
    if (renamed === cls.fullPath || renamed.startsWith(cls.fullPath + "/")) {
      return { target: renamed, reason: "path-contained", node: cls.fullPath };
    }
    // Preserve source-relative context under the classified node to avoid
    // flattening many distinct files into the same basename target.
    return {
      target: joinNodeWithRelative(cls.fullPath, renamed),
      reason: cls.reason || "classified",
      node: cls.fullPath,
    };
  }
  // Orphan — mirror under UNCLASSIFIED/loose while preserving rel path.
  return {
    target: `UNCLASSIFIED/loose/${renamed}`,
    reason: "orphan",
    node: null,
  };
}

function safeJoinDestination(destRoot, relPath) {
  const abs = path.resolve(destRoot, relPath);
  if (!abs.startsWith(path.resolve(destRoot) + path.sep) && abs !== path.resolve(destRoot)) {
    throw clientError(`Path escape detected: ${relPath}`);
  }
  return abs;
}

/**
 * Decide whether the destination root is acceptable per collision policy.
 * Note: directory existence with the SAME blueprint structure is fine for "merge".
 */
function checkDestination(destRoot, collisionPolicy) {
  const exists = fs.existsSync(destRoot);
  if (!exists) return { exists: false };
  const entries = fs.readdirSync(destRoot);
  const empty = entries.length === 0;
  if (empty) return { exists: true, empty: true };
  if (collisionPolicy === "abort") {
    throw clientError(`destination_root "${destRoot}" already exists and is not empty (collision_policy=abort)`, 409);
  }
  return { exists: true, empty: false };
}

function ensureDestParent(absTarget) {
  fs.mkdirSync(path.dirname(absTarget), { recursive: true });
}

function copyOne(absSource, absTarget, collisionPolicy) {
  if (fs.existsSync(absTarget)) {
    if (collisionPolicy === "abort") {
      throw clientError(`File already exists at destination: ${absTarget}`, 409);
    }
    if (collisionPolicy === "rename_existing") {
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      const backup = `${absTarget}.bak-${ts}`;
      fs.renameSync(absTarget, backup);
    }
    // "merge" / "overwrite" → fall through and overwrite
  }
  ensureDestParent(absTarget);
  fs.copyFileSync(absSource, absTarget);
}

/**
 * Run the full structural commit.
 *
 * @param {object} args
 * @param {string} args.workspaceRoot
 * @param {string} args.destinationRoot
 * @param {object} args.plan
 * @param {object} args.blueprint  v2 (already saved with user edits)
 * @param {function} args.materializeBlueprint
 * @param {function} args.classifyToNode
 * @param {function} args.flattenBlueprint
 * @param {boolean}  args.dryRun
 */
function runFull({
  workspaceRoot, destinationRoot, plan, blueprint,
  materializeBlueprint, classifyToNode, flattenBlueprint,
  dryRun = false,
}) {
  if (!plan) throw clientError("No pipeline plan found.", 404);
  if (!blueprint) throw clientError("No blueprint v2 found.", 404);
  if (!destinationRoot || typeof destinationRoot !== "string") {
    throw clientError("destination_root is required");
  }

  const collisionPolicy = plan.destination_collision_policy || "abort";
  const absDest = path.resolve(destinationRoot);

  // Pre-flight on destination
  const destState = checkDestination(absDest, collisionPolicy);

  // 1. Materialize the blueprint at destination
  const materialize = materializeBlueprint(blueprint, absDest, {
    collisionPolicy: collisionPolicy === "abort" ? "merge" : collisionPolicy,
    // ↑ if abort was used as the destination check, after passing it we still
    //    need the materializer to be permissive on per-dir existence (it just
    //    created the parent itself). Use merge here.
    dryRun,
  });

  // 2. Walk workspace files and copy
  const renames = renameMap(plan);
  const flatNodes = flattenBlueprint(blueprint);

  const copied = [];
  const skipped = [];
  const errors = [];

  for (const f of walkWorkspaceFiles(workspaceRoot)) {
    let decision;
    try {
      decision = decideTargetPath({
        srcRel: f.rel, renames, classifyToNode, flatNodes,
      });
    } catch (e) {
      errors.push({ source: f.rel, error: e.message });
      continue;
    }

    let absTarget;
    try { absTarget = safeJoinDestination(absDest, decision.target); }
    catch (e) {
      errors.push({ source: f.rel, error: e.message });
      continue;
    }

    if (dryRun) {
      copied.push({
        source: f.rel,
        target: decision.target,
        node: decision.node,
        reason: decision.reason,
        status: "planned",
      });
      continue;
    }

    try {
      copyOne(f.abs, absTarget, collisionPolicy);
      copied.push({
        source: f.rel,
        target: decision.target,
        node: decision.node,
        reason: decision.reason,
        status: "copied",
      });
    } catch (e) {
      if (e.statusCode === 409 && collisionPolicy === "abort") {
        skipped.push({ source: f.rel, target: decision.target, reason: "collision-abort" });
      } else {
        errors.push({ source: f.rel, target: decision.target, error: e.message });
      }
    }
  }

  // 3. Manifest
  const manifest = {
    spec_version: "1.0.0",
    session_id: plan.session_id,
    plan_ref: ".discovery/pipeline_plan.json",
    blueprint_ref: ".discovery/tree_blueprint.v2.json",
    destination_root: absDest,
    destination_collision_policy: collisionPolicy,
    destination_pre_state: destState,
    generated_at: new Date().toISOString(),
    dry_run: !!dryRun,
    materialize: {
      dirs_created: materialize.dirs_created.length,
      readmes_written: materialize.readmes_written.length,
      readmes_skipped: materialize.skipped.length,
    },
    summary: {
      total_files: copied.length + skipped.length + errors.length,
      copied: copied.length,
      skipped: skipped.length,
      errors: errors.length,
      orphans: copied.filter((c) => c.reason === "orphan").length,
      renames_applied: renames.size,
    },
    files: copied,
    skipped,
    errors,
    renames: [...renames.entries()].map(([from, to]) => ({ from, to })),
  };
  return manifest;
}

function saveFullRunManifest(workspaceRoot, manifest) {
  const dir = path.resolve(workspaceRoot, "_intelligence");
  fs.mkdirSync(dir, { recursive: true });
  const dst = path.join(dir, "full_run_manifest.json");
  fs.writeFileSync(dst, JSON.stringify(manifest, null, 2) + "\n");
  return dst;
}

function loadFullRunManifest(workspaceRoot) {
  const f = path.resolve(workspaceRoot, "_intelligence", "full_run_manifest.json");
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

module.exports = {
  runFull,
  saveFullRunManifest,
  loadFullRunManifest,
  renameMap,
  applyRenames,
  decideTargetPath,
};
