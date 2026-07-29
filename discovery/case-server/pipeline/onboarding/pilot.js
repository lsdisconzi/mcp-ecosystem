/**
 * Discovery — Onboarding · Pilot run (P5)
 *
 * Picks a sample of files per main directory from the pipeline plan and
 * produces a structured pilot_report.json. This MVP does NOT invoke the
 * intelligence/comprehend pipelines — it validates that:
 *   - each main directory has at least one matching file in the corpus
 *   - sample files exist on disk and are non-empty
 *   - configured layers reference known pipeline stages
 *
 * That is enough to gate the full run: if any main directory has zero
 * samples, the user knows to ingest more or remap before P6.
 *
 * Sample strategies:
 *   first        — alphabetical order
 *   random       — Math.random shuffle
 *   largest      — by file size desc
 *   most_recent  — by mtime desc
 *   user_picked  — exact relative paths from pilot.user_picked_files
 *
 * deeper_sample: when true, also picks one sample per first-level child
 * subdirectory (Q2: "deeper sample" toggle).
 */

const fs = require("fs");
const path = require("path");

const KNOWN_LAYERS = new Set(["L1-L3", "L4", "L5-L7", "comprehend"]);

function clientError(message, statusCode = 400) {
  const err = new Error(message);
  err.statusCode = statusCode;
  return err;
}

/** Return all candidate files for a given main_directory path. */
function collectCandidates({ workspaceRoot, plan, mainDir, classifyToNode, flatNodes }) {
  // Strategy: enumerate every file in workspaceRoot (skipping .discovery / _intelligence
  // / README.md skeleton artifacts) and classify each into a node. Match against the
  // mainDir path so renames between v1 (on disk) and v2 (edited) resolve correctly.
  const out = [];
  const skipDirs = new Set([".discovery", "_intelligence", "node_modules", ".git"]);

  function walk(absDir, relDir) {
    let entries;
    try { entries = fs.readdirSync(absDir, { withFileTypes: true }); }
    catch (_) { return; }
    for (const ent of entries) {
      if (ent.name.startsWith(".") && ent.name !== ".discovery") continue;
      const abs = path.join(absDir, ent.name);
      const rel = relDir ? `${relDir}/${ent.name}` : ent.name;
      if (ent.isDirectory()) {
        if (skipDirs.has(ent.name)) continue;
        walk(abs, rel);
      } else if (ent.isFile()) {
        // Skip skeleton READMEs — they're scaffolding, not corpus.
        if (ent.name === "README.md") continue;
        let stat;
        try { stat = fs.statSync(abs); } catch (_) { continue; }
        const fileSig = {
          file: rel,
          fileName: ent.name,
          // category/kind unknown without the pipeline store; classification
          // falls back to path containment + filename tokens.
        };
        const cls = classifyToNode(fileSig, flatNodes);
        if (!cls) continue;
        // Accept the file if its assigned node path is the mainDir or descends from it.
        const ok = cls.fullPath === mainDir.path || cls.fullPath.startsWith(mainDir.path + "/");
        if (!ok) continue;
        out.push({
          relPath: rel,
          absPath: abs,
          size: stat.size,
          mtime: stat.mtime.toISOString(),
          assignedNodePath: cls.fullPath,
          classifyReason: cls.reason,
        });
      }
    }
  }

  walk(workspaceRoot, "");
  return out;
}

function selectSamples(candidates, pilotConfig, workspaceRoot) {
  const cfg = pilotConfig || {};
  const strategy = cfg.sample_strategy || "random";
  const count = Number.isInteger(cfg.sample_count) && cfg.sample_count >= 1 ? cfg.sample_count : 1;

  if (strategy === "user_picked") {
    const picked = Array.isArray(cfg.user_picked_files) ? cfg.user_picked_files : [];
    const out = [];
    for (const rel of picked) {
      const abs = path.resolve(workspaceRoot, rel);
      if (!abs.startsWith(workspaceRoot)) continue;
      if (!fs.existsSync(abs)) {
        out.push({ relPath: rel, absPath: abs, missing: true });
        continue;
      }
      const stat = fs.statSync(abs);
      out.push({
        relPath: rel,
        absPath: abs,
        size: stat.size,
        mtime: stat.mtime.toISOString(),
        assignedNodePath: null,
        classifyReason: "user-picked",
      });
    }
    return out;
  }

  let sorted = [...candidates];
  if (strategy === "first") sorted.sort((a, b) => a.relPath.localeCompare(b.relPath));
  else if (strategy === "largest") sorted.sort((a, b) => b.size - a.size);
  else if (strategy === "most_recent") sorted.sort((a, b) => b.mtime.localeCompare(a.mtime));
  else { // random
    for (let i = sorted.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [sorted[i], sorted[j]] = [sorted[j], sorted[i]];
    }
  }
  return sorted.slice(0, count);
}

function deeperSamples(candidates, mainDir) {
  // One file per first-level child subdir under mainDir.
  const byChild = new Map();
  for (const c of candidates) {
    if (!c.assignedNodePath) continue;
    if (c.assignedNodePath === mainDir.path) continue;
    if (!c.assignedNodePath.startsWith(mainDir.path + "/")) continue;
    const tail = c.assignedNodePath.slice(mainDir.path.length + 1);
    const childSeg = tail.split("/")[0];
    if (!byChild.has(childSeg)) byChild.set(childSeg, c);
  }
  return [...byChild.values()];
}

/**
 * @param {object} args
 * @param {string} args.workspaceRoot
 * @param {object} args.plan       — pipeline_plan.json
 * @param {object} args.blueprint  — current v2 blueprint
 * @param {function} args.classifyToNode  — refine.classifyFileToNode
 * @param {function} args.flattenBlueprint — refine.flattenBlueprint
 */
function runPilot({ workspaceRoot, plan, blueprint, classifyToNode, flattenBlueprint }) {
  if (!plan) throw clientError("No pipeline plan found. Run POST /api/onboarding/plan first.", 404);
  if (!blueprint) throw clientError("No blueprint v2 found.", 404);

  const flatNodes = flattenBlueprint(blueprint);

  const samples = [];
  const summary = {
    main_directories: plan.main_directories.length,
    sampled_files: 0,
    main_directories_with_samples: 0,
    main_directories_empty: 0,
    files_missing: 0,
    layers_unknown: 0,
  };
  const warnings = [];

  for (const mainDir of plan.main_directories) {
    const candidates = collectCandidates({
      workspaceRoot, plan, mainDir, classifyToNode, flatNodes,
    });
    const picked = selectSamples(candidates, mainDir.pilot, workspaceRoot);
    let extras = [];
    if (mainDir.pilot && mainDir.pilot.deeper_sample && mainDir.pilot.sample_strategy !== "user_picked") {
      extras = deeperSamples(candidates, mainDir);
    }
    const all = [...picked, ...extras];

    if (!all.length) {
      summary.main_directories_empty++;
      warnings.push({
        kind: "empty_main_directory",
        path: mainDir.path,
        message: `No corpus files matched main directory "${mainDir.path}".`,
      });
    } else {
      summary.main_directories_with_samples++;
    }

    // Validate layers
    const unknownLayers = (mainDir.layers || []).filter((l) => !KNOWN_LAYERS.has(l));
    if (unknownLayers.length) {
      summary.layers_unknown += unknownLayers.length;
      warnings.push({
        kind: "unknown_layers",
        path: mainDir.path,
        layers: unknownLayers,
      });
    }

    for (const s of all) {
      const status = s.missing ? "missing" : "planned";
      if (s.missing) summary.files_missing++;
      else summary.sampled_files++;
      samples.push({
        main_directory: mainDir.path,
        file: s.relPath,
        size: s.size || 0,
        mtime: s.mtime || null,
        assigned_node_path: s.assignedNodePath || null,
        classify_reason: s.classifyReason || null,
        layers: [...(mainDir.layers || [])],
        pilot_strategy: (mainDir.pilot && mainDir.pilot.sample_strategy) || "random",
        deeper_extra: extras.includes(s),
        status,
      });
    }
  }

  const ok = summary.main_directories_empty === 0
    && summary.files_missing === 0
    && summary.layers_unknown === 0;

  return {
    spec_version: "1.0.0",
    session_id: plan.session_id,
    plan_ref: ".discovery/pipeline_plan.json",
    blueprint_ref: ".discovery/tree_blueprint.v2.json",
    generated_at: new Date().toISOString(),
    ok,
    summary,
    samples,
    warnings,
  };
}

function savePilotReport(workspaceRoot, report) {
  const dir = path.resolve(workspaceRoot, "_intelligence");
  fs.mkdirSync(dir, { recursive: true });
  const dst = path.join(dir, "pilot_report.json");
  fs.writeFileSync(dst, JSON.stringify(report, null, 2) + "\n");
  return dst;
}

function loadPilotReport(workspaceRoot) {
  const f = path.resolve(workspaceRoot, "_intelligence", "pilot_report.json");
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

module.exports = {
  runPilot,
  savePilotReport,
  loadPilotReport,
  collectCandidates,
  selectSamples,
};
