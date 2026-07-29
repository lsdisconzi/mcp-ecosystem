/**
 * Discovery — Onboarding helpers
 *
 * Owns the storage and materialization of the three onboarding artifacts:
 *   intake_spec.json, tree_blueprint.v1.json, tree_blueprint.v2.json,
 *   plus pipeline_plan.json (consumed in later phases).
 *
 * Validation here is intentionally light. The JSON Schemas in ./schemas/
 * are the source of truth; full schema validation can be plugged in later
 * (AJV) without changing this module's surface.
 */

const fs = require("fs");
const path = require("path");

const TEMPLATES_DIR = path.resolve(__dirname, "templates");

const META_DIR = ".discovery";
const FILE_INTAKE = "intake_spec.json";
const FILE_BLUEPRINT_V1 = "tree_blueprint.v1.json";
const FILE_BLUEPRINT_V2 = "tree_blueprint.v2.json";
const FILE_PIPELINE_PLAN = "pipeline_plan.json";

const VALID_INTAKE_MODES = new Set(["form", "agent", "hybrid"]);
const VALID_DOMAINS = new Set([
  "legal_case", "research", "business_records", "technical_docs",
  "personal_archive", "investigation", "mixed", "other"
]);

function metaDir(workspaceRoot) {
  return path.resolve(workspaceRoot, META_DIR);
}

function clientError(message, statusCode = 400) {
  const err = new Error(message);
  err.statusCode = statusCode;
  return err;
}

function listTemplates() {
  if (!fs.existsSync(TEMPLATES_DIR)) return [];
  return fs.readdirSync(TEMPLATES_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      const tpl = JSON.parse(fs.readFileSync(path.join(TEMPLATES_DIR, f), "utf8"));
      const id = (tpl.source && tpl.source.template_id) || path.basename(f, ".json");
      return {
        id,
        label: tpl.root_label,
        notes: tpl.notes || "",
        node_count: countNodes(tpl.nodes || []),
      };
    });
}

function loadTemplate(templateId) {
  if (typeof templateId !== "string" || !templateId.length) {
    throw clientError("template_id is required");
  }
  const safe = templateId.replace(/[^A-Za-z0-9_-]/g, "");
  if (safe !== templateId) {
    throw clientError(`Invalid template_id: ${templateId}`);
  }
  const file = path.join(TEMPLATES_DIR, `${safe}.json`);
  if (!fs.existsSync(file)) {
    throw clientError(`Unknown template: ${safe}`, 404);
  }
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function countNodes(nodes) {
  let n = 0;
  const walk = (arr) => {
    for (const x of arr) {
      n++;
      if (Array.isArray(x.children)) walk(x.children);
    }
  };
  walk(nodes);
  return n;
}

// ----- IntakeSpec -----

function validateIntakeSpec(spec) {
  if (!spec || typeof spec !== "object") throw clientError("intake_spec must be an object");
  if (spec.spec_version && spec.spec_version !== "1.0.0") {
    throw clientError(`Unsupported spec_version: ${spec.spec_version}`);
  }
  if (!VALID_DOMAINS.has(spec.domain)) {
    throw clientError(`domain must be one of: ${[...VALID_DOMAINS].join(", ")}`);
  }
  if (!spec.goal || typeof spec.goal.summary !== "string" || !spec.goal.summary.trim()) {
    throw clientError("goal.summary is required");
  }
  if (!VALID_INTAKE_MODES.has(spec.intake_mode)) {
    throw clientError(`intake_mode must be one of: ${[...VALID_INTAKE_MODES].join(", ")}`);
  }
  if (typeof spec.template_id !== "string" || !spec.template_id.length) {
    throw clientError("template_id is required");
  }
}

function normalizeIntakeSpec(input, sessionId) {
  const now = new Date().toISOString();
  const spec = {
    spec_version: "1.0.0",
    session_id: sessionId,
    created_at: input.created_at || now,
    updated_at: now,
    intake_mode: input.intake_mode,
    template_id: input.template_id,
    domain: input.domain,
    domain_other: input.domain_other,
    goal: input.goal,
    jurisdictions: Array.isArray(input.jurisdictions) ? input.jurisdictions : [],
    timeframe: input.timeframe,
    parties_of_interest: Array.isArray(input.parties_of_interest) ? input.parties_of_interest : [],
    expected_file_kinds: Array.isArray(input.expected_file_kinds) ? input.expected_file_kinds : [],
    privacy_level: input.privacy_level || "confidential",
    preferred_llm_provider: input.preferred_llm_provider,
    reference_attachments: Array.isArray(input.reference_attachments) ? input.reference_attachments : [],
    agent_transcript: input.agent_transcript,
    open_questions: Array.isArray(input.open_questions) ? input.open_questions : [],
  };
  // Strip undefined keys for cleaner JSON.
  for (const k of Object.keys(spec)) if (spec[k] === undefined) delete spec[k];
  return spec;
}

function saveIntakeSpec(workspaceRoot, spec) {
  const dir = metaDir(workspaceRoot);
  fs.mkdirSync(dir, { recursive: true });
  const dst = path.join(dir, FILE_INTAKE);
  fs.writeFileSync(dst, JSON.stringify(spec, null, 2) + "\n");
  return dst;
}

function loadIntakeSpec(workspaceRoot) {
  const f = path.join(metaDir(workspaceRoot), FILE_INTAKE);
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

// ----- TreeBlueprint -----

function validateBlueprintNode(node, ancestorPath) {
  if (!node || typeof node !== "object") {
    throw clientError(`Invalid node at ${ancestorPath || "<root>"}`);
  }
  if (typeof node.path !== "string" || !node.path.length || /[\\/]/.test(node.path) || node.path === "." || node.path === "..") {
    throw clientError(`Invalid node.path "${node.path}" at ${ancestorPath || "<root>"}`);
  }
  if (typeof node.purpose !== "string" || !node.purpose.trim()) {
    throw clientError(`node.purpose is required at ${ancestorPath}/${node.path}`);
  }
  if (node.children !== undefined && !Array.isArray(node.children)) {
    throw clientError(`node.children must be an array at ${ancestorPath}/${node.path}`);
  }
  if (Array.isArray(node.children)) {
    for (const c of node.children) validateBlueprintNode(c, `${ancestorPath}/${node.path}`);
  }
}

function validateBlueprint(bp) {
  if (!bp || typeof bp !== "object") throw clientError("blueprint must be an object");
  if (bp.spec_version && bp.spec_version !== "1.0.0") {
    throw clientError(`Unsupported spec_version: ${bp.spec_version}`);
  }
  if (!["template", "v1", "v2"].includes(bp.blueprint_version)) {
    throw clientError(`blueprint_version must be one of template|v1|v2`);
  }
  if (typeof bp.root_label !== "string" || !bp.root_label.length) {
    throw clientError("root_label is required");
  }
  if (!Array.isArray(bp.nodes) || !bp.nodes.length) {
    throw clientError("blueprint.nodes must be a non-empty array");
  }
  for (const n of bp.nodes) validateBlueprintNode(n, "");
}

function generateBlueprintV1(intakeSpec, template) {
  const blueprint = JSON.parse(JSON.stringify(template));
  blueprint.spec_version = "1.0.0";
  blueprint.blueprint_version = "v1";
  blueprint.generated_at = new Date().toISOString();
  blueprint.source = {
    kind: "intake",
    template_id: (template.source && template.source.template_id) || intakeSpec.template_id,
    intake_spec_ref: `${META_DIR}/${FILE_INTAKE}`,
  };
  const goal = (intakeSpec.goal && intakeSpec.goal.summary) ? intakeSpec.goal.summary.trim() : "";
  if (goal) {
    blueprint.notes = `Generated from intake on ${blueprint.generated_at}. Goal: ${goal.slice(0, 240)}`;
  }
  if (intakeSpec.case_label && typeof intakeSpec.case_label === "string") {
    blueprint.root_label = intakeSpec.case_label;
  }
  return blueprint;
}

function saveBlueprint(workspaceRoot, blueprint) {
  validateBlueprint(blueprint);
  const dir = metaDir(workspaceRoot);
  fs.mkdirSync(dir, { recursive: true });
  const fileName = blueprint.blueprint_version === "v2" ? FILE_BLUEPRINT_V2 : FILE_BLUEPRINT_V1;
  const dst = path.join(dir, fileName);
  fs.writeFileSync(dst, JSON.stringify(blueprint, null, 2) + "\n");
  return dst;
}

function loadBlueprint(workspaceRoot, version) {
  const fileName = version === "v2" ? FILE_BLUEPRINT_V2 : FILE_BLUEPRINT_V1;
  const f = path.join(metaDir(workspaceRoot), fileName);
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

// ----- Materialization -----

function generateReadme(node, ancestorRel) {
  const fullRel = ancestorRel ? `${ancestorRel}/${node.path}` : node.path;
  const lines = [];
  lines.push(`# ${node.path}`);
  lines.push("");
  lines.push(`> ${node.purpose}`);
  lines.push("");

  if (Array.isArray(node.expected_contents) && node.expected_contents.length) {
    lines.push("## Expected contents");
    lines.push("");
    for (const item of node.expected_contents) lines.push(`- ${item}`);
    lines.push("");
  }

  if (node.naming_convention) {
    lines.push("## Naming convention");
    lines.push("");
    lines.push("`" + node.naming_convention + "`");
    lines.push("");
  }

  if (Array.isArray(node.pipeline_layers) && node.pipeline_layers.length) {
    lines.push("## Discovery pipeline");
    lines.push("");
    lines.push("Layers run by default: " + node.pipeline_layers.map((l) => "`" + l + "`").join(", "));
    lines.push("");
  }

  if (node.pipeline_hints && Object.keys(node.pipeline_hints).length) {
    lines.push("## Pipeline hints");
    lines.push("");
    lines.push("```json");
    lines.push(JSON.stringify(node.pipeline_hints, null, 2));
    lines.push("```");
    lines.push("");
  }

  if (Array.isArray(node.tags) && node.tags.length) {
    lines.push("Tags: " + node.tags.map((t) => "`" + t + "`").join(", "));
    lines.push("");
  }

  if (node.readme_seed) {
    lines.push(node.readme_seed.trim());
    lines.push("");
  }

  if (node.required) {
    lines.push("> ⚑ This directory is marked **required** by the blueprint. The user may delete it during P4, but the override will be recorded in `pipeline_plan.guardrails`.");
    lines.push("");
  }

  lines.push(`*Path:* \`${fullRel}\``);
  lines.push("");
  return lines.join("\n");
}

function safeSegment(seg) {
  if (typeof seg !== "string" || !seg.length || seg.includes("/") || seg.includes("\\") || seg === "." || seg === "..") {
    throw clientError(`Invalid path segment: ${JSON.stringify(seg)}`);
  }
  return seg;
}

/**
 * Materialize a blueprint at `root`. Creates directories and per-folder READMEs.
 * Does NOT move uploaded files — that is a separate classification step.
 *
 * options.collisionPolicy: "merge" (default) | "abort" | "overwrite"
 *   - merge: create missing dirs, leave existing READMEs in place
 *   - abort: fail if any blueprint dir already exists
 *   - overwrite: replace existing READMEs
 * options.dryRun: boolean — when true, only reports what would happen
 */
function materializeBlueprint(blueprint, root, options = {}) {
  validateBlueprint(blueprint);
  const policy = options.collisionPolicy || "merge";
  const dryRun = Boolean(options.dryRun);
  const absRoot = path.resolve(root);

  const dirs_created = [];
  const readmes_written = [];
  const skipped = [];

  function visit(node, parentAbs, parentRel) {
    const seg = safeSegment(node.path);
    const abs = path.resolve(parentAbs, seg);
    const rel = parentRel ? `${parentRel}/${seg}` : seg;

    if (abs !== absRoot && !abs.startsWith(absRoot + path.sep)) {
      throw clientError(`Path escape detected for ${rel}`);
    }

    const existed = fs.existsSync(abs);
    if (existed && policy === "abort") {
      throw clientError(`Path already exists at ${rel} (collision_policy=abort)`, 409);
    }
    if (!dryRun) fs.mkdirSync(abs, { recursive: true });
    if (!existed) dirs_created.push(rel);

    const readmePath = path.resolve(abs, "README.md");
    const readmeExisted = fs.existsSync(readmePath);
    if (readmeExisted && policy !== "overwrite") {
      skipped.push(`${rel}/README.md`);
    } else {
      const body = generateReadme(node, parentRel);
      if (!dryRun) fs.writeFileSync(readmePath, body);
      readmes_written.push(`${rel}/README.md`);
    }

    if (Array.isArray(node.children)) {
      for (const child of node.children) visit(child, abs, rel);
    }
  }

  if (!dryRun) fs.mkdirSync(absRoot, { recursive: true });
  for (const node of blueprint.nodes) visit(node, absRoot, "");

  return {
    root: absRoot,
    dry_run: dryRun,
    collision_policy: policy,
    dirs_created,
    readmes_written,
    skipped,
  };
}

// ----- PipelinePlan (loader only at this stage) -----

function loadPipelinePlan(workspaceRoot) {
  const f = path.join(metaDir(workspaceRoot), FILE_PIPELINE_PLAN);
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

const refine = require("./refine");
const plan = require("./plan");
const pilot = require("./pilot");
const fullRun = require("./full_run");
const agentIntake = require("./agent_intake");

module.exports = {
  META_DIR,
  FILE_INTAKE,
  FILE_BLUEPRINT_V1,
  FILE_BLUEPRINT_V2,
  FILE_PIPELINE_PLAN,
  listTemplates,
  loadTemplate,
  validateIntakeSpec,
  normalizeIntakeSpec,
  saveIntakeSpec,
  loadIntakeSpec,
  validateBlueprint,
  generateBlueprintV1,
  saveBlueprint,
  loadBlueprint,
  materializeBlueprint,
  generateReadme,
  loadPipelinePlan,
  // refine
  refineBlueprint: refine.refineBlueprint,
  diffBlueprints: refine.diffBlueprints,
  classifyFileToNode: refine.classifyFileToNode,
  flattenBlueprint: refine.flattenBlueprint,
  // plan
  computeGuardrails: plan.computeGuardrails,
  validatePipelinePlan: plan.validatePipelinePlan,
  buildPipelinePlan: plan.buildPipelinePlan,
  savePipelinePlan: plan.savePipelinePlan,
  VALID_LAYERS: plan.VALID_LAYERS,
  VALID_COLLISION: plan.VALID_COLLISION,
  VALID_SAMPLE_STRATEGY: plan.VALID_SAMPLE_STRATEGY,
  // pilot
  runPilot: pilot.runPilot,
  savePilotReport: pilot.savePilotReport,
  loadPilotReport: pilot.loadPilotReport,
  // full run
  runFull: fullRun.runFull,
  saveFullRunManifest: fullRun.saveFullRunManifest,
  loadFullRunManifest: fullRun.loadFullRunManifest,
  // agent intake
  agentIntakeStart: agentIntake.startSession,
  agentIntakeReply: agentIntake.applyReply,
  agentIntakeState: agentIntake.getState,
  agentIntakeClear: agentIntake.clearState,
  agentIntakeFinalSpec: agentIntake.buildFinalSpec,
};