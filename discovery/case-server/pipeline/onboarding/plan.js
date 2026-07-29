/**
 * Discovery — Onboarding plan (P4 / P4.5)
 *
 * Saves the user-edited blueprint v2 plus the per-directory pipeline
 * configuration and the chosen destination root. Computes guardrail
 * diffs (deleted/renamed required paths) so overrides are auditable.
 */

const fs = require("fs");
const path = require("path");

const VALID_LAYERS = new Set(["L1-L3", "L4", "L5-L7", "comprehend"]);
const VALID_COLLISION = new Set(["abort", "merge", "rename_existing", "overwrite"]);
const VALID_SAMPLE_STRATEGY = new Set(["first", "random", "largest", "most_recent", "user_picked"]);

function clientError(message, statusCode = 400) {
  const err = new Error(message);
  err.statusCode = statusCode;
  return err;
}

/** Walk a blueprint and return a Map<rel_path, node>. */
function flattenNodes(nodes, parentRel = "") {
  const out = new Map();
  for (const n of nodes || []) {
    const rel = parentRel ? `${parentRel}/${n.path}` : n.path;
    out.set(rel, n);
    if (Array.isArray(n.children) && n.children.length) {
      for (const [k, v] of flattenNodes(n.children, rel)) out.set(k, v);
    }
  }
  return out;
}

/**
 * Compare two blueprints to compute guardrail records.
 *  - deleted_required_paths: nodes that were `required:true` in `original` but absent in `edited`
 *  - renamed_paths: best-effort detection (same parent + same purpose, different leaf)
 */
function computeGuardrails(originalBlueprint, editedBlueprint, reasons = {}) {
  const orig = flattenNodes(originalBlueprint.nodes || []);
  const edited = flattenNodes(editedBlueprint.nodes || []);

  const deleted_required_paths = [];
  const renamed_paths = [];

  // Detect renames first: same parent + same purpose with different leaf segment.
  // Used to avoid false-flagging renames as deletions.
  const renamedFrom = new Set();
  for (const [origPath, origNode] of orig.entries()) {
    if (edited.has(origPath)) continue;
    const parent = origPath.includes("/") ? origPath.slice(0, origPath.lastIndexOf("/")) : "";
    for (const [editedPath, editedNode] of edited.entries()) {
      if (orig.has(editedPath)) continue;
      const eParent = editedPath.includes("/") ? editedPath.slice(0, editedPath.lastIndexOf("/")) : "";
      if (eParent === parent && editedNode.purpose && editedNode.purpose === origNode.purpose) {
        renamed_paths.push({ from: origPath, to: editedPath });
        renamedFrom.add(origPath);
        break;
      }
    }
  }

  for (const [origPath, origNode] of orig.entries()) {
    if (edited.has(origPath)) continue;
    if (renamedFrom.has(origPath)) continue;
    if (origNode.required === true) {
      deleted_required_paths.push({
        path: origPath,
        reason: (reasons && reasons[origPath]) || "User removed required directory during P4 review.",
      });
    }
  }

  return { deleted_required_paths, renamed_paths };
}

function validateMainDirectory(md, idx, editedPaths) {
  if (!md || typeof md !== "object") {
    throw clientError(`main_directories[${idx}] must be an object`);
  }
  if (typeof md.path !== "string" || !md.path.length) {
    throw clientError(`main_directories[${idx}].path is required`);
  }
  if (!editedPaths.has(md.path)) {
    throw clientError(`main_directories[${idx}].path "${md.path}" is not present in the blueprint`);
  }
  if (!Array.isArray(md.layers)) {
    throw clientError(`main_directories[${idx}].layers must be an array`);
  }
  for (const l of md.layers) {
    if (!VALID_LAYERS.has(l)) {
      throw clientError(`main_directories[${idx}].layers contains invalid layer "${l}"`);
    }
  }
  if (md.pilot) {
    if (md.pilot.sample_strategy && !VALID_SAMPLE_STRATEGY.has(md.pilot.sample_strategy)) {
      throw clientError(`main_directories[${idx}].pilot.sample_strategy invalid`);
    }
    if (md.pilot.sample_strategy === "user_picked" &&
        (!Array.isArray(md.pilot.user_picked_files) || md.pilot.user_picked_files.length === 0)) {
      throw clientError(`main_directories[${idx}].pilot.user_picked_files required when sample_strategy=user_picked`);
    }
    if (md.pilot.sample_count !== undefined && (!Number.isInteger(md.pilot.sample_count) || md.pilot.sample_count < 1)) {
      throw clientError(`main_directories[${idx}].pilot.sample_count must be integer ≥ 1`);
    }
  }
}

function normalizeMainDirectory(md) {
  const out = {
    path: md.path,
    layers: [...md.layers],
  };
  if (md.options && typeof md.options === "object") out.options = md.options;
  if (md.pilot && typeof md.pilot === "object") {
    const p = {};
    if (md.pilot.sample_count != null) p.sample_count = md.pilot.sample_count;
    if (md.pilot.sample_strategy) p.sample_strategy = md.pilot.sample_strategy;
    if (Array.isArray(md.pilot.user_picked_files)) p.user_picked_files = [...md.pilot.user_picked_files];
    if (typeof md.pilot.deeper_sample === "boolean") p.deeper_sample = md.pilot.deeper_sample;
    if (Object.keys(p).length) out.pilot = p;
  }
  return out;
}

function validatePipelinePlan(plan, editedBlueprint) {
  if (!plan || typeof plan !== "object") throw clientError("pipeline_plan must be an object");
  if (plan.spec_version && plan.spec_version !== "1.0.0") {
    throw clientError(`Unsupported spec_version: ${plan.spec_version}`);
  }
  if (typeof plan.destination_root !== "string" || !plan.destination_root.trim()) {
    throw clientError("destination_root is required");
  }
  if (plan.destination_collision_policy &&
      !VALID_COLLISION.has(plan.destination_collision_policy)) {
    throw clientError(`destination_collision_policy must be one of ${[...VALID_COLLISION].join(", ")}`);
  }
  if (!Array.isArray(plan.main_directories) || plan.main_directories.length === 0) {
    throw clientError("main_directories must be a non-empty array");
  }
  if (!plan.global_options || typeof plan.global_options !== "object") {
    throw clientError("global_options is required");
  }
  if (typeof plan.global_options.llm_provider !== "string" || !plan.global_options.llm_provider.length) {
    throw clientError("global_options.llm_provider is required");
  }
  const editedPaths = flattenNodes(editedBlueprint.nodes || []);
  plan.main_directories.forEach((md, i) => validateMainDirectory(md, i, editedPaths));
}

function buildPipelinePlan({
  sessionId,
  editedBlueprint,
  originalBlueprint,
  destinationRoot,
  destinationCollisionPolicy,
  mainDirectories,
  globalOptions,
  guardrailReasons,
  existingPlan,
}) {
  const now = new Date().toISOString();
  const guardrails = computeGuardrails(originalBlueprint, editedBlueprint, guardrailReasons || {});

  const plan = {
    spec_version: "1.0.0",
    session_id: sessionId,
    blueprint_ref: ".discovery/tree_blueprint.v2.json",
    destination_root: destinationRoot,
    destination_collision_policy: destinationCollisionPolicy || "abort",
    main_directories: mainDirectories.map(normalizeMainDirectory),
    global_options: {
      llm_provider: globalOptions.llm_provider,
      max_concurrency: Number.isInteger(globalOptions.max_concurrency)
        ? globalOptions.max_concurrency : 4,
      halt_on_error: !!globalOptions.halt_on_error,
      dry_run: !!globalOptions.dry_run,
    },
    guardrails,
    created_at: existingPlan && existingPlan.created_at ? existingPlan.created_at : now,
    updated_at: now,
  };
  if (typeof globalOptions.cost_ceiling_usd === "number") {
    plan.global_options.cost_ceiling_usd = globalOptions.cost_ceiling_usd;
  }
  return plan;
}

function savePipelinePlan(workspaceRoot, plan) {
  const dir = path.resolve(workspaceRoot, ".discovery");
  fs.mkdirSync(dir, { recursive: true });
  const dst = path.join(dir, "pipeline_plan.json");
  fs.writeFileSync(dst, JSON.stringify(plan, null, 2) + "\n");
  return dst;
}

module.exports = {
  flattenNodes,
  computeGuardrails,
  validatePipelinePlan,
  buildPipelinePlan,
  savePipelinePlan,
  VALID_LAYERS: [...VALID_LAYERS],
  VALID_COLLISION: [...VALID_COLLISION],
  VALID_SAMPLE_STRATEGY: [...VALID_SAMPLE_STRATEGY],
};
