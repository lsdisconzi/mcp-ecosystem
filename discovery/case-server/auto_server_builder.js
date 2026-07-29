/**
 *  Discovery — AUTO SERVER BUILDER
 *  Maps any local folder to structured, well-described REST endpoints.
 *  Identifies file types, extracts metadata, categorizes, and generates
 *  human-readable descriptions — making every file semantically accessible.
 *
 *  Supports hot-rebuild via POST /api/rebuild to point at a new directory.
 */

require('dotenv').config();

const express = require("express");
const fs = require("fs");
const path = require("path");
const cors = require("cors");
const crypto = require("crypto");
const multer = require("multer");
const { runPipeline, runIntelligencePipeline, runComprehension, formalizeEvents, evaluateCaseState, extendStore, enrichEndpoint } = require("./pipeline");
const {
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile
} = require("./pipeline/analysis_profile");
const onboarding = require("./pipeline/onboarding");

// ********** CONFIG ************
const PORT = process.env.PORT || 3010;
const INVENTORY_FILE = process.env.INVENTORY_FILE || "endpoints_inventory.json";
const UI_FILE = process.env.UI_FILE || path.resolve(__dirname, "../ui/discovery_ui.html");
const ONBOARDING_UI_FILE = process.env.ONBOARDING_UI_FILE || path.resolve(__dirname, "../ui/onboarding.html");
const AGENT_WORKSPACE_FILE = process.env.AGENT_WORKSPACE_FILE || path.resolve(__dirname, "../ui/agent_workspace.html");
const AWARENESS_AGENT_WORKSPACE_FILE = process.env.AWARENESS_AGENT_WORKSPACE_FILE || path.resolve(__dirname, "../ui/awareness_agent_workspace.html");
const UI_ASSETS_DIR = process.env.UI_ASSETS_DIR || path.resolve(__dirname, "../ui/assets");
const ARGUS_BASE_URL = process.env.ARGUS_BASE_URL || "http://localhost:8029";

const STATIC_DIR_CANDIDATES = [
  process.env.UI_STATIC_DIR,
  path.resolve(__dirname, "../../frontend-public/static"),
  path.resolve(__dirname, "../../gateway/static"),
  path.resolve(__dirname, "../../awareness/static"),
].filter(Boolean);

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
  "script-src-elem 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
  "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com",
  "img-src 'self' data: blob: http://127.0.0.1:* http://localhost:*",
  "connect-src 'self' http://127.0.0.1:* http://localhost:* https://api.deepseek.com",
  "media-src 'self' data: blob:",
  "worker-src 'self' blob: https://cdn.jsdelivr.net"
].join('; ');

function resolveStaticDir() {
  for (const dir of STATIC_DIR_CANDIDATES) {
    if (fs.existsSync(dir) && fs.statSync(dir).isDirectory()) {
      return dir;
    }
  }
  return null;
}

const UI_STATIC_DIR = resolveStaticDir();

const PIPELINE_STORE_OVERRIDE = process.env.PIPELINE_STORE || null;
const DISCOVERY_STRICT_ISOLATION = (process.env.DISCOVERY_STRICT_ISOLATION || "true") !== "false";
const DISCOVERY_ALLOW_GLOBAL_ROOT = (process.env.DISCOVERY_ALLOW_GLOBAL_ROOT || "false") === "true";
const WORKSPACE_BASE_DIR = path.resolve(process.env.DISCOVERY_WORKSPACE_BASE_DIR || path.resolve("./documents_scanned/sessions"));
const DEFAULT_UPLOAD_ROOT = path.resolve(process.env.DEFAULT_UPLOAD_ROOT || path.resolve("./documents_scanned"));
const SESSION_ID_RE = /^[A-Za-z0-9._-]{1,80}$/;
const WORKSPACE_META_DIR = ".discovery";
const WORKSPACE_EXPORT_FORMAT = "awareness-discovery-workspace-export";
const WORKSPACE_EXPORT_VERSION = "2.0";

// ********** MUTABLE STATE ************
let currentRootDir = process.env.ROOT_DIR || path.resolve("./documents_scanned");
let endpoints = [];
let fileRouter = express.Router();
let buildCount = 0;
let pipelineStore = null;
let lastPipelineStats = null;

function isAllowedRootDir(rootDir) {
  const resolved = path.resolve(rootDir);
  if (!DISCOVERY_STRICT_ISOLATION || DISCOVERY_ALLOW_GLOBAL_ROOT) {
    return true;
  }

  // Only allow session workspaces in strict mode:
  //   <workspace_base>/<session_id>/workspace
  const relative = path.relative(WORKSPACE_BASE_DIR, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return false;
  }

  const parts = relative.split(path.sep).filter(Boolean);
  return parts.length >= 2 && parts[parts.length - 1] === "workspace";
}

function getPipelineStoreFile(rootDir = currentRootDir) {
  if (PIPELINE_STORE_OVERRIDE) {
    return path.resolve(PIPELINE_STORE_OVERRIDE);
  }
  return path.join(path.resolve(rootDir), WORKSPACE_META_DIR, "pipeline_store.json");
}

function ensurePipelineStore() {
  if (pipelineStore) {
    pipelineStore = extendStore(pipelineStore);
    return pipelineStore;
  }

  if (!fs.existsSync(currentRootDir) || !fs.statSync(currentRootDir).isDirectory()) {
    throw new Error(`Root directory is not available: ${currentRootDir}`);
  }

  const allFiles = walkDir(currentRootDir);
  const { store, stats } = runPipeline(allFiles, currentRootDir, {
    storeFile: getPipelineStoreFile(currentRootDir),
    incremental: true,
  });

  pipelineStore = extendStore(store);
  lastPipelineStats = stats;
  return pipelineStore;
}

function readIntelligenceJson(fileName) {
  const filePath = path.join(currentRootDir, "_intelligence", fileName);
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readComprehendFile(fileName, asText = false) {
  const filePath = path.join(currentRootDir, "_intelligence", fileName);
  if (!fs.existsSync(filePath)) return null;
  return asText ? fs.readFileSync(filePath, "utf8") : JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function getBaseUrl(req) {
  return process.env.PUBLIC_BASE_URL || `${req.protocol}://${req.get("host")}`;
}

function serializeEndpoint(endpoint, baseUrl) {
  return {
    ...endpoint,
    url: `${baseUrl}${endpoint.route}`,
  };
}

// ===================================================================
// HELPERS
// ===================================================================

function randomId(len = 10) {
  return crypto.randomBytes(len).toString("base64url").slice(0, len);
}

function getSafeSessionId(userId) {
  const raw = String(userId || "").trim();
  return SESSION_ID_RE.test(raw) ? raw : "default";
}

function getSessionUserId(req, payload = {}) {
  return payload.user_id || req.get("X-Discovery-User-Id");
}

function resolveUploadRoot(userId) {
  const sessionId = getSafeSessionId(userId);
  if (sessionId === "default") {
    const err = new Error("Missing or invalid X-Discovery-User-Id");
    err.statusCode = 400;
    throw err;
  }

  const sessionRoot = path.resolve(DEFAULT_UPLOAD_ROOT, "sessions", sessionId);
  const workspaceRoot = path.resolve(sessionRoot, "workspace");
  const legacyRoot = path.resolve(sessionRoot, "documents_scanned");

  if (fs.existsSync(legacyRoot) && !fs.existsSync(workspaceRoot)) {
    fs.mkdirSync(path.dirname(workspaceRoot), { recursive: true });
    fs.renameSync(legacyRoot, workspaceRoot);
  }

  return { sessionId, workspaceRoot };
}

function cleanupGeneratedArtifacts(workspaceRoot) {
  for (const rel of [WORKSPACE_META_DIR, "_intelligence"]) {
    const target = path.resolve(workspaceRoot, rel);
    fs.rmSync(target, { recursive: true, force: true });
  }
}

function assertSafeRelativePath(incomingPath) {
  const normalized = path.posix.normalize(String(incomingPath || "").replace(/\\/g, "/")).replace(/^\/+/, "");
  if (!normalized || normalized === "." || normalized.includes("\0") || normalized.startsWith("../")) {
    throw new Error(`Invalid file path: ${incomingPath}`);
  }
  return normalized;
}

function normalizePathSegment(segment, fallback = "file") {
  const raw = String(segment || "").trim();
  if (!raw) return fallback;

  let value = raw
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/[\\/:*?"<>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  // Keep naming portable and deterministic across shells/filesystems.
  value = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._ -]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  value = value.replace(/^\.+/, "").replace(/[. ]+$/g, "");
  if (!value || value === "." || value === "..") return fallback;
  return value;
}

function normalizeRelativeUploadPath(incomingPath) {
  const safeRelative = assertSafeRelativePath(incomingPath);
  const parts = safeRelative.split("/").filter(Boolean);
  if (!parts.length) {
    throw new Error(`Invalid file path: ${incomingPath}`);
  }

  const normalizedParts = parts.map((part, idx) => {
    const isLast = idx === parts.length - 1;
    if (!isLast) {
      return normalizePathSegment(part, "folder");
    }

    const ext = path.extname(part);
    const stem = ext ? part.slice(0, -ext.length) : part;
    const normalizedStem = normalizePathSegment(stem, "file");
    const extBody = normalizePathSegment(ext.replace(/^\./, ""), "").replace(/ /g, "").toLowerCase();
    const normalizedExt = extBody ? `.${extBody}` : "";
    return normalizedExt ? `${normalizedStem}${normalizedExt}` : normalizedStem;
  });

  return normalizedParts.join("/");
}

function ensureUniqueRelativePath(relativePath, workspaceRoot, reserved = new Set()) {
  const dir = path.posix.dirname(relativePath);
  const ext = path.extname(relativePath);
  const stem = ext ? path.posix.basename(relativePath, ext) : path.posix.basename(relativePath);

  let candidate = relativePath;
  let counter = 2;
  while (
    reserved.has(candidate) ||
    fs.existsSync(path.resolve(workspaceRoot, candidate))
  ) {
    const nextBase = `${stem}_${counter}${ext}`;
    candidate = dir === "." ? nextBase : `${dir}/${nextBase}`;
    counter += 1;
  }

  reserved.add(candidate);
  return candidate;
}

function walkDir(dir, files = []) {
  let items;
  try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch { return files; }
  for (const item of items) {
    if (item.name.startsWith(".")) continue; // skip hidden files/dirs
    if (DISCOVERY_STRICT_ISOLATION && item.isDirectory() && item.name === "sessions" && !DISCOVERY_ALLOW_GLOBAL_ROOT) {
      // In strict mode, never traverse the shared sessions container.
      continue;
    }
    const fullPath = path.join(dir, item.name);
    item.isDirectory() ? walkDir(fullPath, files) : files.push(fullPath);
  }
  return files;
}

function toPosixPath(value) {
  return String(value || "").replace(/\\/g, "/");
}

function walkDirAll(dir, files = []) {
  let items;
  try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch { return files; }
  for (const item of items) {
    const fullPath = path.join(dir, item.name);
    if (item.isSymbolicLink()) continue;
    if (item.isDirectory()) {
      walkDirAll(fullPath, files);
    } else if (item.isFile()) {
      files.push(fullPath);
    }
  }
  return files;
}

function isGeneratedWorkspaceArtifact(relativePath) {
  const rel = toPosixPath(relativePath);
  return (
    rel.startsWith("_intelligence/") ||
    rel.startsWith(`${WORKSPACE_META_DIR}/`) ||
    rel === "pipeline_store.json"
  );
}

function buildWorkspaceExportPayload(sessionId, workspaceRoot, baseUrl) {
  const serializedEndpoints = endpoints.map((endpoint) => serializeEndpoint(endpoint, baseUrl));
  const endpointByFile = new Map(
    serializedEndpoints.map((endpoint) => [toPosixPath(endpoint.file), endpoint])
  );

  const workspaceFiles = walkDirAll(workspaceRoot).map((absolutePath) => {
    const relativePath = toPosixPath(path.relative(workspaceRoot, absolutePath));
    const bytes = fs.readFileSync(absolutePath);
    const stats = getFileStats(absolutePath);
    const endpoint = endpointByFile.get(relativePath) || null;

    return {
      relative_path: relativePath,
      size_bytes: bytes.length,
      sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
      generated: isGeneratedWorkspaceArtifact(relativePath),
      endpoint_url: endpoint ? endpoint.url : null,
      endpoint_route: endpoint ? endpoint.route : null,
      endpoint_id: endpoint ? endpoint.id : null,
      modified_at: stats.modified_at,
      created_at: stats.created_at,
      content_base64: bytes.toString("base64"),
    };
  });

  const categories = summarizeCategories();
  const generatedFiles = workspaceFiles.filter((entry) => entry.generated).length;

  return {
    _format: WORKSPACE_EXPORT_FORMAT,
    _version: WORKSPACE_EXPORT_VERSION,
    exported_at: new Date().toISOString(),
    user_id: sessionId,
    root_path: workspaceRoot,
    summary: {
      workspace_files: workspaceFiles.length,
      generated_files: generatedFiles,
      endpoint_files: serializedEndpoints.length,
      categories: Object.keys(categories).length,
      total_bytes: workspaceFiles.reduce((sum, entry) => sum + (entry.size_bytes || 0), 0),
    },
    manifest: {
      discovery: "Discovery",
      version: "2.0.0",
      root_dir: workspaceRoot,
      base_url: baseUrl,
      total_files: serializedEndpoints.length,
      build: buildCount,
      categories,
    },
    endpoints: serializedEndpoints,
    files: workspaceFiles,
  };
}

function parseBooleanFlag(value, defaultValue = false) {
  if (value === undefined || value === null || value === "") return defaultValue;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "n", "off"].includes(normalized)) return false;
  return defaultValue;
}

function humanSize(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0, size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function cleanDisplayName(baseName) {
  return baseName
    .replace(/[_\-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

// ===================================================================
// FILE TYPE IDENTIFICATION
// ===================================================================

const MIME_MAP = {
  ".pdf": "application/pdf", ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xls": "application/vnd.ms-excel",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".ppt": "application/vnd.ms-powerpoint",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".txt": "text/plain", ".md": "text/markdown", ".html": "text/html",
  ".htm": "text/html", ".css": "text/css", ".js": "application/javascript",
  ".ts": "application/typescript", ".json": "application/json",
  ".xml": "application/xml", ".yaml": "text/yaml", ".yml": "text/yaml",
  ".csv": "text/csv", ".tsv": "text/tab-separated-values",
  ".py": "text/x-python", ".java": "text/x-java", ".c": "text/x-c",
  ".cpp": "text/x-c++", ".h": "text/x-c", ".sh": "application/x-sh",
  ".sql": "application/sql", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml",
  ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav",
  ".ogg": "audio/ogg", ".mp4": "video/mp4", ".avi": "video/x-msvideo",
  ".mov": "video/quicktime", ".zip": "application/zip",
  ".gz": "application/gzip", ".tar": "application/x-tar",
  ".rar": "application/vnd.rar", ".7z": "application/x-7z-compressed",
  ".toml": "application/toml", ".rtf": "application/rtf",
  ".log": "text/plain", ".ini": "text/plain", ".cfg": "text/plain",
  ".env": "text/plain",
};

const KIND_MAP = {
  ".pdf": "PDF Document", ".doc": "Word Document", ".docx": "Word Document",
  ".xls": "Spreadsheet", ".xlsx": "Spreadsheet",
  ".ppt": "Presentation", ".pptx": "Presentation",
  ".txt": "Plain Text", ".md": "Markdown", ".html": "HTML Page",
  ".htm": "HTML Page", ".css": "Stylesheet",
  ".js": "JavaScript", ".ts": "TypeScript", ".json": "JSON Data",
  ".xml": "XML Document", ".yaml": "YAML Config", ".yml": "YAML Config",
  ".csv": "CSV Data", ".tsv": "TSV Data",
  ".py": "Python Source", ".java": "Java Source", ".c": "C Source",
  ".cpp": "C++ Source", ".h": "Header File", ".sh": "Shell Script",
  ".sql": "SQL Script", ".png": "Image (PNG)", ".jpg": "Image (JPEG)",
  ".jpeg": "Image (JPEG)", ".gif": "Image (GIF)", ".svg": "Image (SVG)",
  ".webp": "Image (WebP)", ".mp3": "Audio (MP3)", ".wav": "Audio (WAV)",
  ".ogg": "Audio (OGG)", ".mp4": "Video (MP4)", ".avi": "Video (AVI)",
  ".mov": "Video (MOV)", ".zip": "ZIP Archive", ".gz": "GZip Archive",
  ".tar": "TAR Archive", ".rar": "RAR Archive", ".7z": "7-Zip Archive",
  ".toml": "TOML Config", ".rtf": "Rich Text",
  ".log": "Log File", ".ini": "Config File", ".cfg": "Config File",
  ".env": "Environment Config",
};

const CONTENT_GROUP = {
  document: [".pdf", ".doc", ".docx", ".rtf", ".txt", ".md", ".html", ".htm"],
  data: [".json", ".xml", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".sql"],
  code: [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".sh", ".css"],
  image: [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"],
  audio: [".mp3", ".wav", ".ogg"],
  video: [".mp4", ".avi", ".mov"],
  archive: [".zip", ".gz", ".tar", ".rar", ".7z"],
  config: [".ini", ".cfg", ".env", ".log"],
};

function getMimeType(ext) { return MIME_MAP[ext.toLowerCase()] || "application/octet-stream"; }
function getFileKind(ext) { return KIND_MAP[ext.toLowerCase()] || "File"; }

function getContentGroup(ext) {
  const e = ext.toLowerCase();
  for (const [group, exts] of Object.entries(CONTENT_GROUP)) {
    if (exts.includes(e)) return group;
  }
  return "other";
}

function getFileStats(filePath) {
  try {
    const stats = fs.statSync(filePath);
    return {
      size_bytes: stats.size,
      size_human: humanSize(stats.size),
      created_at: stats.birthtime.toISOString(),
      modified_at: stats.mtime.toISOString(),
    };
  } catch {
    return { size_bytes: 0, size_human: "0 B", created_at: null, modified_at: null };
  }
}

// ===================================================================
// CATEGORIZATION ENGINE
// ===================================================================

const CATEGORY_KEYWORDS = {
  legal_frameworks: ["anac", "law", "cdc", "legal", "ley", "decreto", "resolucion", "normativa", "regulacion"],
  constitution: ["constitution", "constitucion"],
  penal_code: ["penal_code", "codigo_penal", "penal"],
  pdi: ["pdi"],
  dgac: ["dgac"],
  passenger_notes: ["passenger", "pasajero"],
  incident_summary: ["incident_context", "incident_summary", "incidente"],
  incident_narrative: ["narrative", "narrativa"],
  transcript: ["segment", "transcript", "transcripcion", "audio", "aeropuerto"],
  evidence: ["evidence", "prueba", "evidencia"],
  timeline: ["timeline", "cronologia", "chronology"],
  correspondence: ["email", "carta", "letter", "memo", "memorandum"],
  media: ["photo", "foto", "video", "imagen", "image"],
  report: ["report", "informe", "analisis"],
};

function inferCategory(fp) {
  const parts = fp.toLowerCase().split(path.sep);
  for (const p of parts) {
    for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
      if (keywords.includes(p)) return cat;
    }
  }
  // Fallback: parent directory name
  return parts[parts.length - 2] || "general";
}

function formatCategoryLabel(cat) {
  return cat.replace(/[_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ===================================================================
// DESCRIPTION GENERATOR
// ===================================================================

function generateDescription(rel, category, kind, displayName) {
  const dirParts = path.dirname(rel).split(path.sep).filter(Boolean);
  const location = dirParts.length > 0 ? dirParts.join(" / ") : "root";
  return `${kind}: "${displayName}" — ${formatCategoryLabel(category)} (${location})`;
}

// ===================================================================
// ROUTE NAMING
// ===================================================================

function buildSafeRoute(rel, category, baseName) {
  const routeSafeSegment = (value, fallback = "file") => {
    const normalized = String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^[_\.]+|[_\.]+$/g, "");
    return normalized || fallback;
  };

  const safeCategory = routeSafeSegment(category, "general").toLowerCase();
  const ext = path.extname(baseName);
  const stem = ext ? baseName.slice(0, -ext.length) : baseName;
  const safeStem = routeSafeSegment(stem, "file");
  const safeExt = routeSafeSegment(ext.replace(/^\./, ""), "").toLowerCase();
  const relHash = crypto.createHash("sha1").update(String(rel || baseName)).digest("hex").slice(0, 8);
  const safeFile = safeExt
    ? `${safeStem}_${relHash}.${safeExt}`
    : `${safeStem}_${relHash}`;

  return `/api/files/${safeCategory}/${safeFile}`;
}

// ===================================================================
// REBUILD ENGINE
// ===================================================================

function rebuildFromDir(rootDir) {
  const resolvedRoot = path.resolve(rootDir);
  if (!fs.existsSync(resolvedRoot) || !fs.statSync(resolvedRoot).isDirectory()) {
    throw new Error(`Not a valid directory: ${rootDir}`);
  }
  if (!isAllowedRootDir(resolvedRoot)) {
    throw new Error(`Root directory is not allowed in strict isolation mode: ${resolvedRoot}`);
  }

  currentRootDir = resolvedRoot;
  endpoints = [];
  const newRouter = express.Router();
  const allFiles = walkDir(resolvedRoot);

  for (const filePath of allFiles) {
    const rel = path.relative(resolvedRoot, filePath);
    const ext = path.extname(filePath);
    const baseName = path.basename(filePath, ext);
    const category = inferCategory(filePath);
    const displayName = cleanDisplayName(baseName);
    const kind = getFileKind(ext);
    const safeRoute = buildSafeRoute(rel, category, path.basename(filePath));

    const absPath = path.resolve(filePath);
    newRouter.get(safeRoute, (req, res, next) => {
      res.sendFile(absPath, (err) => err && next(err));
    });

    endpoints.push({
      id: randomId(12),
      file: rel,
      fileName: path.basename(filePath),
      displayName,
      route: safeRoute,
      category,
      categoryLabel: formatCategoryLabel(category),
      kind,
      contentGroup: getContentGroup(ext),
      mimeType: getMimeType(ext),
      extension: ext || "(none)",
      description: generateDescription(rel, category, kind, displayName),
      location: path.dirname(rel) || ".",
      ...getFileStats(filePath),
    });
  }

  fileRouter = newRouter;
  buildCount++;

  try { fs.writeFileSync(INVENTORY_FILE, JSON.stringify(endpoints, null, 2)); } catch (_) {}

  console.log(`🔄 Build #${buildCount}: ${endpoints.length} files from ${resolvedRoot}`);

  // ── Run Pipeline ───────────────────────────────────────────────
  try {
    const { store, stats } = runPipeline(allFiles, resolvedRoot, {
      storeFile: getPipelineStoreFile(resolvedRoot),
      incremental: true,
    });
    pipelineStore = extendStore(store);
    lastPipelineStats = stats;
    console.log(`📊 Pipeline: ${stats.processed} enriched, ${stats.skipped} cached, ${stats.failed} failed`);
  } catch (err) {
    console.error("Pipeline failed (server continues without enrichment):", err.message);
  }

  return {
    root_dir: resolvedRoot,
    total_files: endpoints.length,
    build: buildCount,
    categories: summarizeCategories(),
    pipeline: lastPipelineStats,
  };
}

function summarizeCategories() {
  const cats = {};
  for (const ep of endpoints) {
    if (!cats[ep.category]) cats[ep.category] = { label: ep.categoryLabel, count: 0, kinds: {} };
    cats[ep.category].count++;
    cats[ep.category].kinds[ep.kind] = (cats[ep.category].kinds[ep.kind] || 0) + 1;
  }
  return cats;
}

function buildArgusUrl(upstreamPath, query = {}) {
  const base = ARGUS_BASE_URL.endsWith("/") ? ARGUS_BASE_URL.slice(0, -1) : ARGUS_BASE_URL;
  const cleanPath = upstreamPath.startsWith("/") ? upstreamPath : `/${upstreamPath}`;
  const url = new URL(`${base}${cleanPath}`);

  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.append(key, String(value));
    }
  }

  return url.toString();
}

async function proxyArgusJson(req, res, upstreamPath) {
  const url = buildArgusUrl(upstreamPath, req.query || {});

  try {
    const upstream = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
    });

    const contentType = upstream.headers.get("content-type") || "";
    const payloadText = await upstream.text();

    if (!upstream.ok) {
      if (contentType.includes("application/json")) {
        try {
          return res.status(upstream.status).json(JSON.parse(payloadText));
        } catch {
          // Fall through to normalized error below.
        }
      }

      return res.status(upstream.status).json({
        error: "Argus upstream error",
        upstream: ARGUS_BASE_URL,
        status: upstream.status,
        detail: payloadText.slice(0, 800),
      });
    }

    if (contentType.includes("application/json")) {
      try {
        return res.json(JSON.parse(payloadText));
      } catch {
        return res.status(502).json({
          error: "Invalid JSON returned by Argus",
          upstream: ARGUS_BASE_URL,
        });
      }
    }

    return res.type(contentType || "text/plain").send(payloadText);
  } catch (err) {
    return res.status(503).json({
      error: "Argus service not reachable",
      upstream: ARGUS_BASE_URL,
      detail: err.message,
    });
  }
}

// ===================================================================
// SERVER
// ===================================================================

function createDiscoveryApp() {
  const app = express();
  const upload = multer({
    storage: multer.memoryStorage(),
    preservePath: true,
  });

  app.use((req, res, next) => {
    // Applies a strict baseline without unsafe-eval, which removes Electron CSP warnings.
    res.setHeader("Content-Security-Policy", CONTENT_SECURITY_POLICY);
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    next();
  });

  app.use(cors());
  app.use(express.json({ limit: "10mb" }));
  app.use("/assets", express.static(UI_ASSETS_DIR));

  if (UI_STATIC_DIR) {
    app.use("/static", express.static(UI_STATIC_DIR));
    console.log(`🧩 Serving /static from ${UI_STATIC_DIR}`);
  } else {
    console.warn("⚠️  UI static directory not found. /static/* requests may fail.");
  }

  // Swappable file-serving router
  app.use((req, res, next) => fileRouter(req, res, next));

  app.get("/health", (req, res) => {
    res.json({
      status: "ok",
      service: "discovery",
      timestamp: new Date().toISOString(),
    });
  });

  // ── Hot Rebuild ──────────────────────────────────────────────────
  app.post("/api/rebuild", (req, res) => {
    const rootDir = req.body.root_dir;
    if (!rootDir || typeof rootDir !== "string") {
      return res.status(400).json({ error: "Missing or invalid root_dir" });
    }
    const resolved = path.resolve(rootDir);
    if (!fs.existsSync(resolved)) return res.status(400).json({ error: `Directory not found: ${rootDir}` });
    if (!fs.statSync(resolved).isDirectory()) return res.status(400).json({ error: `Not a directory: ${rootDir}` });
    if (!isAllowedRootDir(resolved)) {
      return res.status(403).json({
        error: "root_dir not allowed in strict isolation mode",
        root_dir: resolved,
        workspace_base: WORKSPACE_BASE_DIR,
      });
    }
    try {
      const result = rebuildFromDir(rootDir);
      res.json({ ok: true, ...result });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post("/organize", (req, res) => {
    const rootDir = req.body && req.body.root_dir;
    if (!rootDir || typeof rootDir !== "string") {
      return res.status(400).json({ error: "Missing or invalid root_dir" });
    }
    const resolved = path.resolve(rootDir);
    if (!fs.existsSync(resolved)) return res.status(400).json({ error: `Directory not found: ${rootDir}` });
    if (!fs.statSync(resolved).isDirectory()) return res.status(400).json({ error: `Not a directory: ${rootDir}` });
    if (!isAllowedRootDir(resolved)) {
      return res.status(403).json({
        error: "root_dir not allowed in strict isolation mode",
        root_dir: resolved,
        workspace_base: WORKSPACE_BASE_DIR,
      });
    }
    try {
      const result = rebuildFromDir(rootDir);
      return res.json({ ok: true, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  });

  // ── Session workspace lifecycle ───────────────────────────────
  app.post("/api/discovery/init-session", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const resetGenerated = Boolean(payload.reset_generated);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      fs.mkdirSync(workspaceRoot, { recursive: true });
      if (resetGenerated) cleanupGeneratedArtifacts(workspaceRoot);

      const rebuild = rebuildFromDir(workspaceRoot);
      return res.json({
        ok: true,
        user_id: sessionId,
        root_dir: workspaceRoot,
        layout: {
          workspace: workspaceRoot,
          artifacts: {
            pipeline_store: path.join(workspaceRoot, WORKSPACE_META_DIR, "pipeline_store.json"),
            intelligence_dir: path.join(workspaceRoot, "_intelligence"),
          },
        },
        rebuild: { ok: true, ...rebuild },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.post("/api/discovery/reset-session", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const clearFiles = Boolean(payload.clear_files);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      fs.mkdirSync(workspaceRoot, { recursive: true });
      if (clearFiles) {
        fs.rmSync(workspaceRoot, { recursive: true, force: true });
        fs.mkdirSync(workspaceRoot, { recursive: true });
      } else {
        cleanupGeneratedArtifacts(workspaceRoot);
      }

      const rebuild = rebuildFromDir(workspaceRoot);
      return res.json({
        ok: true,
        user_id: sessionId,
        root_dir: workspaceRoot,
        reset: {
          clear_files: clearFiles,
          generated_cleared: true,
        },
        rebuild: { ok: true, ...rebuild },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.post("/api/discovery/upload", upload.array("files"), (req, res) => {
    try {
      const files = Array.isArray(req.files) ? req.files : [];
      if (!files.length) {
        return res.status(400).json({ error: "No files uploaded" });
      }

      const userId = getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      fs.mkdirSync(workspaceRoot, { recursive: true });

      const savedFiles = [];
      const reservedPaths = new Set();
      for (const file of files) {
        const incomingName = file.originalname || file.filename || "unnamed-file";
        const normalizedPath = normalizeRelativeUploadPath(incomingName);
        const relativePath = ensureUniqueRelativePath(normalizedPath, workspaceRoot, reservedPaths);
        const destination = path.resolve(workspaceRoot, relativePath);
        if (destination !== workspaceRoot && !destination.startsWith(`${workspaceRoot}${path.sep}`)) {
          return res.status(400).json({ error: `Invalid file path: ${incomingName}` });
        }

        fs.mkdirSync(path.dirname(destination), { recursive: true });
        fs.writeFileSync(destination, file.buffer);
        savedFiles.push({
          name: path.basename(relativePath),
          original_name: path.basename(assertSafeRelativePath(incomingName)),
          original_relative_path: assertSafeRelativePath(incomingName),
          relative_path: relativePath,
          normalized: relativePath !== assertSafeRelativePath(incomingName),
          size: file.size,
        });
      }

      const rebuild = rebuildFromDir(workspaceRoot);
      return res.json({
        ok: true,
        user_id: sessionId,
        root_dir: workspaceRoot,
        files: savedFiles,
        rebuild: { ok: true, ...rebuild },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ---------- Onboarding (P0–P1) ----------
  // Templates listing — does not require a session.
  app.get("/api/onboarding/templates", (req, res) => {
    try {
      return res.json({ ok: true, templates: onboarding.listTemplates() });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/intake", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const spec = onboarding.loadIntakeSpec(workspaceRoot);
      return res.json({ ok: true, user_id: sessionId, root_dir: workspaceRoot, intake_spec: spec });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // P0 → P1. Stores the IntakeSpec, materializes the v1 blueprint from the named template,
  // and writes both to <workspace>/.discovery/. Does NOT create folders on disk yet — that
  // is /api/onboarding/blueprint/materialize.
  app.post("/api/onboarding/intake", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      fs.mkdirSync(workspaceRoot, { recursive: true });

      const rawSpec = payload.intake_spec || payload;
      onboarding.validateIntakeSpec(rawSpec);
      const spec = onboarding.normalizeIntakeSpec(rawSpec, sessionId);

      const template = onboarding.loadTemplate(spec.template_id);
      const blueprintV1 = onboarding.generateBlueprintV1(spec, template);

      const intakePath = onboarding.saveIntakeSpec(workspaceRoot, spec);
      const blueprintPath = onboarding.saveBlueprint(workspaceRoot, blueprintV1);

      return res.json({
        ok: true,
        user_id: sessionId,
        root_dir: workspaceRoot,
        intake_spec: spec,
        blueprint: blueprintV1,
        artifacts: {
          intake_spec: path.relative(workspaceRoot, intakePath),
          blueprint_v1: path.relative(workspaceRoot, blueprintPath),
        },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ---------- Agent-driven intake (Q1 stretch) ----------
  // Conversational flow: agent asks questions one at a time, parses replies,
  // assembles an intake_spec, then commits the same artifacts as POST /intake.
  app.post("/api/onboarding/intake/agent/start", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      fs.mkdirSync(workspaceRoot, { recursive: true });

      // If a session already exists and caller didn't pass reset=true, resume.
      if (!payload.reset && onboarding.agentIntakeState(workspaceRoot)) {
        const state = onboarding.agentIntakeState(workspaceRoot);
        return res.json({
          ok: true,
          user_id: sessionId,
          resumed: true,
          completed: !!state.completed,
          partial_spec: state.partial_spec,
          question: state.pending,
          history: state.history,
        });
      }

      onboarding.agentIntakeClear(workspaceRoot);
      const templates = onboarding.listTemplates();
      const { state, question } = onboarding.agentIntakeStart({
        workspaceRoot,
        sessionId,
        templates,
      });
      return res.json({
        ok: true,
        user_id: sessionId,
        resumed: false,
        completed: false,
        partial_spec: state.partial_spec,
        question,
        history: state.history,
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/intake/agent", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const state = onboarding.agentIntakeState(workspaceRoot);
      if (!state) {
        return res.json({ ok: true, user_id: sessionId, started: false });
      }
      return res.json({
        ok: true,
        user_id: sessionId,
        started: true,
        completed: !!state.completed,
        partial_spec: state.partial_spec,
        question: state.pending,
        history: state.history,
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.post("/api/onboarding/intake/agent/reply", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const replyText = String(payload.reply == null ? "" : payload.reply);
      const templates = onboarding.listTemplates();

      const result = onboarding.agentIntakeReply({
        workspaceRoot,
        replyText,
        templates,
      });

      const response = {
        ok: true,
        user_id: sessionId,
        completed: !!result.completed,
        restarted: !!result.restarted,
        partial_spec: result.state.partial_spec,
        question: result.question,
        history: result.state.history,
      };

      // If agent flow finished AND user confirmed, commit the spec via the
      // same flow as the form-mode endpoint (saveIntakeSpec + generate v1).
      if (result.completed && result.confirmed) {
        const finalSpec = onboarding.agentIntakeFinalSpec(result.state);
        onboarding.validateIntakeSpec(finalSpec);
        const normalized = onboarding.normalizeIntakeSpec(finalSpec, sessionId);
        const template = onboarding.loadTemplate(normalized.template_id);
        const blueprintV1 = onboarding.generateBlueprintV1(normalized, template);
        const intakePath = onboarding.saveIntakeSpec(workspaceRoot, normalized);
        const blueprintPath = onboarding.saveBlueprint(workspaceRoot, blueprintV1);
        response.intake_spec = normalized;
        response.blueprint = blueprintV1;
        response.artifacts = {
          intake_spec: path.relative(workspaceRoot, intakePath),
          blueprint_v1: path.relative(workspaceRoot, blueprintPath),
        };
      }

      return res.json(response);
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.post("/api/onboarding/intake/agent/cancel", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      onboarding.agentIntakeClear(workspaceRoot);
      return res.json({ ok: true, user_id: sessionId, cleared: true });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/blueprint", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const version = req.query.version === "v2" ? "v2" : "v1";
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const blueprint = onboarding.loadBlueprint(workspaceRoot, version);
      return res.json({ ok: true, user_id: sessionId, version, blueprint });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // Creates directories + per-folder README.md from the saved blueprint.
  // target=workspace materializes inside the session workspace (P1, default).
  // target=destination materializes at body.destination_root (P6).
  app.post("/api/onboarding/blueprint/materialize", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const version = payload.blueprint_version === "v2" ? "v2" : "v1";
      const blueprint = onboarding.loadBlueprint(workspaceRoot, version);
      if (!blueprint) {
        const err = new Error(`No saved blueprint found for version=${version}. Run POST /api/onboarding/intake first.`);
        err.statusCode = 404;
        throw err;
      }

      const target = payload.target === "destination" ? "destination" : "workspace";
      let materializeRoot;
      if (target === "destination") {
        if (typeof payload.destination_root !== "string" || !payload.destination_root.length) {
          const err = new Error("destination_root is required when target=destination");
          err.statusCode = 400;
          throw err;
        }
        materializeRoot = path.resolve(payload.destination_root);
      } else {
        materializeRoot = workspaceRoot;
      }

      const result = onboarding.materializeBlueprint(blueprint, materializeRoot, {
        collisionPolicy: payload.collision_policy || "merge",
        dryRun: Boolean(payload.dry_run),
      });

      // Reindex the workspace if we wrote into it so /api/files reflects the skeleton.
      let rebuild = null;
      if (target === "workspace" && !result.dry_run) {
        rebuild = rebuildFromDir(workspaceRoot);
      }

      return res.json({
        ok: true,
        user_id: sessionId,
        target,
        version,
        result,
        rebuild: rebuild ? { ok: true, ...rebuild } : null,
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // P3 — Refine: read v1 + corpus signals, produce v2 + diff.
  // Calls rebuildFromDir to ensure the pipeline_store reflects the session
  // workspace before sampling; then walks the file inventory to annotate
  // and extend the blueprint.
  app.post("/api/onboarding/refine", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const v1 = onboarding.loadBlueprint(workspaceRoot, "v1");
      if (!v1) {
        const err = new Error("No blueprint v1 found. Run POST /api/onboarding/intake first.");
        err.statusCode = 404;
        throw err;
      }

      // Refresh the global state so `endpoints` reflects this session's workspace.
      const rebuild = rebuildFromDir(workspaceRoot);

      const baseUrl = getBaseUrl(req);
      const fileSignals = endpoints.map((endpoint) => {
        const s = serializeEndpoint(endpoint, baseUrl);
        return {
          file: s.file,
          fileName: s.fileName,
          category: s.category,
          kind: s.kind,
          contentGroup: s.contentGroup,
        };
      });

      const signals = {
        files: fileSignals,
        stats: lastPipelineStats,
      };

      const { v2, diff, stats: refineStats } = onboarding.refineBlueprint(v1, signals);
      const blueprintPath = onboarding.saveBlueprint(workspaceRoot, v2);

      return res.json({
        ok: true,
        user_id: sessionId,
        blueprint: v2,
        diff,
        refine_stats: refineStats,
        artifacts: {
          blueprint_v2: path.relative(workspaceRoot, blueprintPath),
        },
        rebuild: { ok: true, ...rebuild },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ---------- Onboarding · P4 / P4.5 ----------
  // Save the user-edited blueprint v2 plus the per-directory pipeline plan
  // and the destination root. Computes guardrail diffs (deleted/renamed
  // required paths) so overrides are auditable.
  app.post("/api/onboarding/plan", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const originalV2 = onboarding.loadBlueprint(workspaceRoot, "v2");
      if (!originalV2) {
        const err = new Error("No blueprint v2 found. Run POST /api/onboarding/refine first.");
        err.statusCode = 404;
        throw err;
      }

      // The edited blueprint replaces v2 on disk. Caller may omit `blueprint`
      // to mean "no edits, keep current v2".
      const editedNodes = payload.blueprint && Array.isArray(payload.blueprint.nodes)
        ? payload.blueprint.nodes
        : originalV2.nodes;

      const editedBlueprint = {
        ...originalV2,
        nodes: editedNodes,
        blueprint_version: "v2",
        generated_at: new Date().toISOString(),
        source: {
          ...(originalV2.source || {}),
          kind: "user_edited",
          previous_blueprint_ref: ".discovery/tree_blueprint.v2.json",
        },
      };
      onboarding.validateBlueprint(editedBlueprint);

      if (!Array.isArray(payload.main_directories)) {
        const err = new Error("main_directories is required");
        err.statusCode = 400;
        throw err;
      }
      if (!payload.global_options || typeof payload.global_options !== "object") {
        const err = new Error("global_options is required");
        err.statusCode = 400;
        throw err;
      }
      if (typeof payload.destination_root !== "string" || !payload.destination_root.trim()) {
        const err = new Error("destination_root is required");
        err.statusCode = 400;
        throw err;
      }

      const newPlan = onboarding.buildPipelinePlan({
        sessionId,
        editedBlueprint,
        originalBlueprint: originalV2,
        destinationRoot: payload.destination_root,
        destinationCollisionPolicy: payload.destination_collision_policy,
        mainDirectories: payload.main_directories,
        globalOptions: payload.global_options,
        guardrailReasons: payload.guardrail_reasons || {},
        existingPlan: onboarding.loadPipelinePlan(workspaceRoot),
      });
      onboarding.validatePipelinePlan(newPlan, editedBlueprint);

      const blueprintPath = onboarding.saveBlueprint(workspaceRoot, editedBlueprint);
      const planPath = onboarding.savePipelinePlan(workspaceRoot, newPlan);

      return res.json({
        ok: true,
        user_id: sessionId,
        blueprint: editedBlueprint,
        plan: newPlan,
        artifacts: {
          blueprint_v2: path.relative(workspaceRoot, blueprintPath),
          pipeline_plan: path.relative(workspaceRoot, planPath),
        },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/plan", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const plan = onboarding.loadPipelinePlan(workspaceRoot);
      const v2 = onboarding.loadBlueprint(workspaceRoot, "v2");
      return res.json({ ok: true, user_id: sessionId, plan, blueprint: v2 });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ---------- Onboarding · P5 ----------
  // Pilot run: sample one file per main directory (per pilot.sample_strategy),
  // optionally one per child subdir (deeper_sample), and emit a structured
  // pilot_report.json. This MVP does not invoke LLMs — it gates the full run
  // on coverage (every main dir has at least one corpus match) and validates
  // the layers config.
  app.post("/api/onboarding/pilot-run", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const plan = onboarding.loadPipelinePlan(workspaceRoot);
      const v2 = onboarding.loadBlueprint(workspaceRoot, "v2");

      const report = onboarding.runPilot({
        workspaceRoot,
        plan,
        blueprint: v2,
        classifyToNode: onboarding.classifyFileToNode,
        flattenBlueprint: onboarding.flattenBlueprint,
      });
      const reportPath = onboarding.savePilotReport(workspaceRoot, report);

      return res.json({
        ok: true,
        user_id: sessionId,
        report,
        artifacts: {
          pilot_report: path.relative(workspaceRoot, reportPath),
        },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/pilot-run", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const report = onboarding.loadPilotReport(workspaceRoot);
      return res.json({ ok: true, user_id: sessionId, report });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ---------- Onboarding · P6 ----------
  // Full run (structural commit): materializes the v2 blueprint at the
  // user-chosen destination_root and COPIES files from the session
  // workspace into the destination tree per the v2 layout. Renames between
  // v1 and v2 are honored via plan.guardrails.renamed_paths. The session
  // workspace is preserved as a snapshot. LLM-driven layer execution is
  // out of scope for this MVP — invoke /api/intelligence/run separately
  // against destination_root after the commit succeeds.
  app.post("/api/onboarding/full-run", (req, res) => {
    try {
      const payload = req.body || {};
      const userId = getSessionUserId(req, payload);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);

      const plan = onboarding.loadPipelinePlan(workspaceRoot);
      const v2 = onboarding.loadBlueprint(workspaceRoot, "v2");

      const manifest = onboarding.runFull({
        workspaceRoot,
        destinationRoot: (plan && plan.destination_root) || payload.destination_root,
        plan,
        blueprint: v2,
        materializeBlueprint: onboarding.materializeBlueprint,
        classifyToNode: onboarding.classifyFileToNode,
        flattenBlueprint: onboarding.flattenBlueprint,
        dryRun: payload.dry_run === true,
      });
      const manifestPath = onboarding.saveFullRunManifest(workspaceRoot, manifest);

      return res.json({
        ok: true,
        user_id: sessionId,
        manifest,
        artifacts: {
          full_run_manifest: path.relative(workspaceRoot, manifestPath),
        },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/onboarding/full-run", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      const manifest = onboarding.loadFullRunManifest(workspaceRoot);
      return res.json({ ok: true, user_id: sessionId, manifest });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.get("/api/discovery/export-session", (req, res) => {
    try {
      const userId = req.query.user_id || getSessionUserId(req);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      fs.mkdirSync(workspaceRoot, { recursive: true });

      // Rebuild first so endpoint URLs and metadata snapshot match the current workspace state.
      rebuildFromDir(workspaceRoot);
      const payload = buildWorkspaceExportPayload(sessionId, workspaceRoot, getBaseUrl(req));
      return res.json(payload);
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  app.post("/api/discovery/import-session", upload.single("bundle"), (req, res) => {
    const badRequest = (message) => {
      const err = new Error(message);
      err.statusCode = 400;
      return err;
    };

    try {
      const userId = getSessionUserId(req, req.body || {});
      const overwriteExisting = parseBooleanFlag(req.body && req.body.overwrite_existing, true);
      const { sessionId, workspaceRoot } = resolveUploadRoot(userId);
      fs.mkdirSync(workspaceRoot, { recursive: true });

      let payload;
      if (req.file && req.file.buffer) {
        try {
          payload = JSON.parse(req.file.buffer.toString("utf8"));
        } catch {
          throw badRequest("Invalid export bundle JSON");
        }
      } else if (req.body && typeof req.body === "object" && req.body._format) {
        payload = req.body;
      } else {
        throw badRequest("Missing export bundle. Send multipart field 'bundle' with an exported JSON file.");
      }

      if (!payload || payload._format !== WORKSPACE_EXPORT_FORMAT) {
        throw badRequest(`Unsupported export format. Expected '${WORKSPACE_EXPORT_FORMAT}'.`);
      }

      const filesToImport = Array.isArray(payload.files) ? payload.files : [];
      if (!filesToImport.length) {
        throw badRequest("Export bundle has no files to import.");
      }

      const reservedPaths = new Set();
      const importSample = [];
      let importedCount = 0;
      let overwrittenCount = 0;
      let renamedCount = 0;
      let generatedCount = 0;

      for (const entry of filesToImport) {
        const sourceRelative = entry && typeof entry.relative_path === "string"
          ? entry.relative_path
          : null;
        if (!sourceRelative) {
          throw badRequest("Invalid file entry in export bundle: missing relative_path.");
        }

        const safeRelative = assertSafeRelativePath(sourceRelative);
        const normalizedRelative = toPosixPath(safeRelative);
        let targetRelative = normalizedRelative;
        let destination = path.resolve(workspaceRoot, targetRelative);
        const existedBefore = fs.existsSync(destination);

        if (existedBefore && !overwriteExisting) {
          targetRelative = ensureUniqueRelativePath(normalizedRelative, workspaceRoot, reservedPaths);
          destination = path.resolve(workspaceRoot, targetRelative);
          renamedCount += 1;
        } else {
          reservedPaths.add(targetRelative);
        }

        if (destination !== workspaceRoot && !destination.startsWith(`${workspaceRoot}${path.sep}`)) {
          throw badRequest(`Invalid file path: ${sourceRelative}`);
        }

        if (typeof entry.content_base64 !== "string") {
          throw badRequest(`Missing content_base64 for ${sourceRelative}`);
        }

        const bytes = Buffer.from(entry.content_base64, "base64");
        const expectedSize = Number(entry.size_bytes);
        if (Number.isFinite(expectedSize) && expectedSize >= 0 && bytes.length !== expectedSize) {
          throw badRequest(`Invalid payload size for ${sourceRelative}`);
        }

        if (typeof entry.sha256 === "string" && entry.sha256.trim()) {
          const actualHash = crypto.createHash("sha256").update(bytes).digest("hex");
          if (actualHash !== entry.sha256.trim().toLowerCase()) {
            throw badRequest(`Checksum mismatch for ${sourceRelative}`);
          }
        }

        fs.mkdirSync(path.dirname(destination), { recursive: true });
        fs.writeFileSync(destination, bytes);

        if (existedBefore && overwriteExisting) {
          overwrittenCount += 1;
        }
        if (isGeneratedWorkspaceArtifact(targetRelative)) {
          generatedCount += 1;
        }

        importedCount += 1;
        if (importSample.length < 50) {
          importSample.push({
            source_relative_path: normalizedRelative,
            relative_path: targetRelative,
            overwritten: existedBefore && overwriteExisting,
            renamed_on_import: targetRelative !== normalizedRelative,
            size: bytes.length,
          });
        }
      }

      const rebuild = rebuildFromDir(workspaceRoot);
      return res.json({
        ok: true,
        user_id: sessionId,
        root_dir: workspaceRoot,
        import: {
          imported_files: importedCount,
          overwritten_files: overwrittenCount,
          renamed_existing_files: renamedCount,
          generated_files: generatedCount,
          overwrite_existing: overwriteExisting,
          sample: importSample,
        },
        rebuild: { ok: true, ...rebuild },
      });
    } catch (err) {
      const status = err.statusCode || 500;
      return res.status(status).json({ error: err.message });
    }
  });

  // ── Search (text match across metadata) ─────────────────────────
  app.get("/api/search", (req, res) => {
    const q = (req.query.q || "").toLowerCase().trim();
    if (!q) return res.status(400).json({ error: "Missing ?q=" });
    const baseUrl = getBaseUrl(req);
    const limit = Math.min(parseInt(req.query.limit, 10) || 50, 500);
    const results = endpoints.filter((e) =>
      e.displayName.toLowerCase().includes(q) ||
      e.category.toLowerCase().includes(q) ||
      e.description.toLowerCase().includes(q) ||
      e.file.toLowerCase().includes(q) ||
      e.kind.toLowerCase().includes(q) ||
      e.fileName.toLowerCase().includes(q)
    ).slice(0, limit).map((endpoint) => serializeEndpoint(endpoint, baseUrl));
    res.json({ query: q, total: results.length, results });
  });

  // ── Endpoints listing ───────────────────────────────────────────
  app.get("/api/endpoints", (req, res) => {
    const baseUrl = getBaseUrl(req);
    res.json(endpoints.map((endpoint) => serializeEndpoint(endpoint, baseUrl)));
  });

  // ── Files (filterable) ──────────────────────────────────────────
  app.get("/api/files", (req, res) => {
    const baseUrl = getBaseUrl(req);
    let result = endpoints;
    if (req.query.category) result = result.filter((e) => e.category === req.query.category);
    if (req.query.ext) result = result.filter((e) => e.extension === req.query.ext);
    if (req.query.kind) result = result.filter((e) => e.kind.toLowerCase().includes(req.query.kind.toLowerCase()));
    if (req.query.group) result = result.filter((e) => e.contentGroup === req.query.group);
    res.json({
      total: result.length,
      filters: req.query,
      files: result.map((endpoint) => serializeEndpoint(endpoint, baseUrl)),
    });
  });

  // ── Categories ──────────────────────────────────────────────────
  app.get("/api/categories", (req, res) => {
    res.json({ total_files: endpoints.length, categories: summarizeCategories() });
  });

  app.get("/api/law/frameworks", async (req, res) => {
    await proxyArgusJson(req, res, "/api/law/frameworks");
  });

  app.get("/api/law/frameworks/:code/articles", async (req, res) => {
    const code = encodeURIComponent(req.params.code || "");
    await proxyArgusJson(req, res, `/api/law/frameworks/${code}/articles`);
  });

  // ── Directory tree ──────────────────────────────────────────────
  app.get("/api/tree", (req, res) => {
    const baseUrl = getBaseUrl(req);

    function buildTree(dir, basePath = "") {
      let items;
      try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch { return []; }
      const children = [];
      for (const item of items) {
        if (item.name.startsWith(".")) continue;
        const relPath = basePath ? `${basePath}/${item.name}` : item.name;
        if (item.isDirectory()) {
          children.push({ name: item.name, type: "directory", path: relPath, children: buildTree(path.join(dir, item.name), relPath) });
        } else {
          const ep = endpoints.find((e) => e.file === relPath.replace(/\//g, path.sep));
          children.push({
            name: item.name,
            type: "file",
            path: relPath,
            url: ep ? `${baseUrl}${ep.route}` : null,
            category: ep ? ep.category : null,
            kind: ep ? ep.kind : null,
          });
        }
      }
      return children;
    }

    res.json({ root: currentRootDir, tree: buildTree(currentRootDir) });
  });

  // ── Manifest ────────────────────────────────────────────────────
  app.get("/api/manifest", (req, res) => {
    const baseUrl = getBaseUrl(req);
    res.json({
      discovery: "Discovery",
      version: "2.0.0",
      generated_at: new Date().toISOString(),
      root_dir: currentRootDir,
      base_url: baseUrl,
      total_files: endpoints.length,
      build: buildCount,
      categories: summarizeCategories(),
      endpoints: endpoints.map((endpoint) => {
        const serialized = serializeEndpoint(endpoint, baseUrl);
        return {
          url: serialized.url,
          file: serialized.file,
          fileName: serialized.fileName,
          displayName: serialized.displayName,
          category: serialized.category,
          kind: serialized.kind,
          contentGroup: serialized.contentGroup,
          mimeType: serialized.mimeType,
          description: serialized.description,
          size_human: serialized.size_human,
        };
      }),
    });
  });

  // ── Pipeline: Enriched file detail ─────────────────────────────
  app.get("/api/file-detail", (req, res) => {
    const rel = req.query.file;
    if (!rel) return res.status(400).json({ error: "Missing ?file=" });
    const ep = endpoints.find((e) => e.file === rel);
    if (!ep) return res.status(404).json({ error: "File not found in index" });
    const baseUrl = getBaseUrl(req);
    const enriched = pipelineStore ? enrichEndpoint(ep, pipelineStore) : ep;
    res.json(serializeEndpoint(enriched, baseUrl));
  });

  // ── Pipeline: Entity index ──────────────────────────────────────
  app.get("/api/pipeline/entities", (req, res) => {
    if (!pipelineStore) return res.json({ error: "Pipeline not run yet", entities: {} });
    const entities = pipelineStore.getEntities();
    const type = req.query.type; // people, organizations, laws, locations, dates
    if (type && entities[type]) {
      // Return specific entity type with counts
      const items = Object.entries(entities[type])
        .map(([name, files]) => ({ name, file_count: files.length, files: files.map((f) => f.file_ref) }))
        .sort((a, b) => b.file_count - a.file_count);
      return res.json({ type, total: items.length, items });
    }
    // Summary of all entity types
    const summary = {};
    for (const [type, map] of Object.entries(entities)) {
      summary[type] = {
        unique_count: Object.keys(map).length,
        total_mentions: Object.values(map).reduce((s, f) => s + f.length, 0),
        top: Object.entries(map)
          .sort((a, b) => b[1].length - a[1].length)
          .slice(0, 10)
          .map(([name, files]) => ({ name, file_count: files.length })),
      };
    }
    res.json({ entities: summary });
  });

  // ── Pipeline: Relationships ─────────────────────────────────────
  app.get("/api/pipeline/relationships", (req, res) => {
    if (!pipelineStore) return res.json({ error: "Pipeline not run yet", relationships: [] });
    const rels = pipelineStore.getRelationships();
    const limit = Math.min(parseInt(req.query.limit, 10) || 100, 500);
    const minStrength = parseInt(req.query.min_strength, 10) || 1;
    const filtered = rels
      .filter((r) => r.strength >= minStrength)
      .slice(0, limit)
      .map((r) => {
        const allFiles = pipelineStore.getAllFiles();
        return {
          ...r,
          source_file: allFiles[r.source] ? allFiles[r.source].file_ref : r.source,
          target_file: allFiles[r.target] ? allFiles[r.target].file_ref : r.target,
        };
      });
    res.json({ total: filtered.length, relationships: filtered });
  });

  // ── Pipeline: Timeline ──────────────────────────────────────────
  app.get("/api/pipeline/timeline", (req, res) => {
    if (!pipelineStore) return res.json({ error: "Pipeline not run yet", timeline: [] });
    const timeline = pipelineStore.getTimeline();
    const from = req.query.from; // YYYY-MM-DD
    const to = req.query.to;
    let filtered = timeline;
    if (from) filtered = filtered.filter((t) => t.date >= from);
    if (to) filtered = filtered.filter((t) => t.date <= to);
    res.json({ total: filtered.length, timeline: filtered.slice(0, 500) });
  });

  // ── Pipeline: Stats ─────────────────────────────────────────────
  app.get("/api/pipeline/stats", (req, res) => {
    if (!pipelineStore) return res.json({ error: "Pipeline not run yet" });
    const meta = pipelineStore.getMeta();
    const allFiles = pipelineStore.getAllFiles();
    const fileCount = Object.keys(allFiles).length;

    // Aggregate stats
    const languages = {};
    const domains = {};
    const tagFreq = {};
    let withEntities = 0;
    let textFiles = 0;
    let totalWords = 0;

    for (const record of Object.values(allFiles)) {
      const L1 = record.layers && record.layers.L1;
      const L2 = record.layers && record.layers.L2;
      const L3 = record.layers && record.layers.L3;
      if (L1 && L1.is_text) { textFiles++; totalWords += (L1.word_count || 0); }
      if (L2) {
        languages[L2.language || "unknown"] = (languages[L2.language || "unknown"] || 0) + 1;
        if (L2.primary_domain) domains[L2.primary_domain] = (domains[L2.primary_domain] || 0) + 1;
        for (const tag of (L2.tags || [])) tagFreq[tag] = (tagFreq[tag] || 0) + 1;
      }
      if (L3 && L3.has_entities) withEntities++;
    }

    res.json({
      pipeline: meta,
      last_run: lastPipelineStats,
      files_enriched: fileCount,
      text_files: textFiles,
      total_words: totalWords,
      files_with_entities: withEntities,
      languages,
      domains,
      top_tags: Object.entries(tagFreq).sort((a, b) => b[1] - a[1]).slice(0, 30),
    });
  });

  // ── Pipeline: Search enriched data ──────────────────────────────
  app.get("/api/pipeline/search", (req, res) => {
    const q = (req.query.q || "").toLowerCase().trim();
    if (!q) return res.status(400).json({ error: "Missing ?q=" });
    if (!pipelineStore) return res.json({ error: "Pipeline not run yet", results: [] });

    const baseUrl = getBaseUrl(req);
    const limit = Math.min(parseInt(req.query.limit, 10) || 50, 200);
    const allFiles = pipelineStore.getAllFiles();
    const results = [];

    for (const [hash, record] of Object.entries(allFiles)) {
      const L1 = record.layers && record.layers.L1;
      const L2 = record.layers && record.layers.L2;
      const L3 = record.layers && record.layers.L3;
      let score = 0;
      const matches = [];

      // Search in preview text
      if (L1 && L1.preview && L1.preview.toLowerCase().includes(q)) { score += 3; matches.push("content"); }
      // Search in tags
      if (L2 && L2.tags && L2.tags.some((t) => t.includes(q))) { score += 2; matches.push("tag"); }
      // Search in key terms
      if (L3 && L3.key_terms && L3.key_terms.some((t) => t.term.includes(q))) { score += 2; matches.push("key_term"); }
      // Search in entities
      if (L3 && L3.entities) {
        for (const [type, ents] of Object.entries(L3.entities)) {
          if (ents.some((e) => (e.raw || e.normalized || "").toLowerCase().includes(q))) {
            score += 2; matches.push(type); break;
          }
        }
      }
      // Search in file path
      if (record.file_ref && record.file_ref.toLowerCase().includes(q)) { score += 1; matches.push("path"); }

      if (score > 0) {
        const ep = endpoints.find((e) => e.file === record.file_ref);
        results.push({
          file: record.file_ref,
          hash,
          score,
          matches,
          url: ep ? `${baseUrl}${ep.route}` : null,
          category: ep ? ep.category : null,
          kind: ep ? ep.kind : null,
        });
      }
    }

    results.sort((a, b) => b.score - a.score);
    res.json({ query: q, total: results.length, results: results.slice(0, limit) });
  });

  // ── Intelligence: Run L5–L7 ───────────────────────────────────
  app.get("/api/intelligence/status", (req, res) => {
    const intelligenceDir = path.join(currentRootDir, "_intelligence");
    const has = (fileName) => fs.existsSync(path.join(intelligenceDir, fileName));

    const available = {
      summary: has("pipeline_summary.json"),
      narrative: has("narrative.md"),
      violations: has("violations.json"),
      events: has("events.json"),
      caseState: has("case_state.json"),
      gaps: has("gap_report.json"),
      comprehension: has("corpus_overview.json"),
      comprehensionGuide: has("corpus_guide.md"),
    };

    res.json({
      ok: true,
      root_dir: currentRootDir,
      intelligence_dir: intelligenceDir,
      available,
      any: Object.values(available).some(Boolean),
      hint: Object.values(available).some(Boolean)
        ? null
        : "Run POST /api/intelligence/run with an API key to generate artifacts.",
    });
  });

  const parseOptionalBoolean = (value) => {
    if (value === undefined || value === null || value === "") return undefined;
    if (typeof value === "boolean") return value;
    const normalized = String(value).trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "off"].includes(normalized)) return false;
    return undefined;
  };

  app.post("/api/intelligence/run", async (req, res) => {
    const {
      api_key,
      model,
      concurrency,
      skip_dedup,
      bulk_fast,
      use_cache,
      analysis_profile,
      kb_enabled,
      persist_to_graph,
      augment_extraction,
      skip_verification
    } = req.body || {};

    if (!api_key) {
      return res.status(400).json({ error: "Missing api_key" });
    }

    try {
      const store = ensurePipelineStore();
      const skipDedupFlag = parseOptionalBoolean(skip_dedup);
      const bulkFastFlag = parseOptionalBoolean(bulk_fast);
      const useCacheFlag = parseOptionalBoolean(use_cache);
      const kbEnabledFlag = parseOptionalBoolean(kb_enabled);
      const persistGraphFlag = parseOptionalBoolean(persist_to_graph);
      const augmentExtractionFlag = parseOptionalBoolean(augment_extraction);
      const skipVerificationFlag = parseOptionalBoolean(skip_verification);
      const result = await runIntelligencePipeline(store, currentRootDir, {
        apiKey: api_key,
        model,
        concurrency: Number.isFinite(Number(concurrency)) ? Number(concurrency) : 3,
        skipDedup: skipDedupFlag === undefined ? false : skipDedupFlag,
        bulkFast: bulkFastFlag === undefined ? false : bulkFastFlag,
        useCache: useCacheFlag === undefined ? true : useCacheFlag,
        analysisProfile: typeof analysis_profile === "string" ? analysis_profile : undefined,
        kbConfig: kbEnabledFlag === undefined ? undefined : { enabled: kbEnabledFlag },
        persistToGraph: persistGraphFlag,
        augmentExtraction: augmentExtractionFlag,
        skipVerification: skipVerificationFlag === undefined ? false : skipVerificationFlag,
        outputDir: path.join(currentRootDir, "_intelligence"),
      });
      res.json(result);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get("/api/intelligence/run-stream", async (req, res) => {
    const {
      api_key,
      model,
      concurrency,
      skip_dedup,
      bulk_fast,
      use_cache,
      analysis_profile,
      kb_enabled,
      persist_to_graph,
      augment_extraction,
      skip_verification
    } = req.query;

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    if (typeof res.flushHeaders === "function") {
      res.flushHeaders();
    }
    res.write("retry: 3000\n\n");

    let streamClosed = false;
    const heartbeat = setInterval(() => {
      if (!streamClosed) {
        // SSE comment heartbeat keeps intermediaries from timing out idle streams.
        res.write(": ping\n\n");
      }
    }, 15000);

    const closeStream = () => {
      if (streamClosed) return;
      streamClosed = true;
      clearInterval(heartbeat);
      if (!res.writableEnded) {
        res.end();
      }
    };

    req.on("close", closeStream);
    req.on("aborted", closeStream);

    const send = (event, payload) => {
      if (streamClosed || res.writableEnded) return;
      res.write(`event: ${event}\n`);
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    };

    if (!api_key) {
      send("error", { error: "Missing api_key" });
      closeStream();
      return;
    }

    try {
      const store = ensurePipelineStore();
      const skipDedupFlag = parseOptionalBoolean(skip_dedup);
      const bulkFastFlag = parseOptionalBoolean(bulk_fast);
      const useCacheFlag = parseOptionalBoolean(use_cache);
      const kbEnabledFlag = parseOptionalBoolean(kb_enabled);
      const persistGraphFlag = parseOptionalBoolean(persist_to_graph);
      const augmentExtractionFlag = parseOptionalBoolean(augment_extraction);
      const skipVerificationFlag = parseOptionalBoolean(skip_verification);
      const result = await runIntelligencePipeline(store, currentRootDir, {
        apiKey: String(api_key),
        model: model ? String(model) : undefined,
        concurrency: Number.isFinite(Number(concurrency)) ? Number(concurrency) : 3,
        skipDedup: skipDedupFlag === undefined ? false : skipDedupFlag,
        bulkFast: bulkFastFlag === undefined ? false : bulkFastFlag,
        useCache: useCacheFlag === undefined ? true : useCacheFlag,
        analysisProfile: typeof analysis_profile === "string" ? analysis_profile : undefined,
        kbConfig: kbEnabledFlag === undefined ? undefined : { enabled: kbEnabledFlag },
        persistToGraph: persistGraphFlag,
        augmentExtraction: augmentExtractionFlag,
        skipVerification: skipVerificationFlag === undefined ? false : skipVerificationFlag,
        outputDir: path.join(currentRootDir, "_intelligence"),
        onProgress: (stage, detail) => send("progress", { stage, detail }),
      });
      send("complete", result);
      closeStream();
    } catch (err) {
      send("error", { error: err.message });
      closeStream();
    }
  });

  app.get("/api/intelligence/summary", (req, res) => {
    const summary = readIntelligenceJson("pipeline_summary.json");
    if (!summary) {
      return res.status(404).json({
        error: "Intelligence pipeline has not been run yet.",
        hint: "POST /api/intelligence/run with your API key",
      });
    }
    res.json(summary);
  });

  app.get("/api/intelligence/case-graph", (req, res) => {
    const graph = readIntelligenceJson("case_graph.json");
    if (!graph) return res.status(404).json({ error: "Case graph not yet generated." });
    res.json(graph);
  });

  const sendFindingsPayload = (req, res) => {
    let violations = readIntelligenceJson("violations.json");
    const summary = readIntelligenceJson("pipeline_summary.json") || {};

    const profile = normalizeAnalysisProfile(
      (typeof req.query.analysis_profile === "string" && req.query.analysis_profile) ||
      summary.analysis_profile
    );
    const profileMeta = getAnalysisProfileMeta(profile);

    if (!violations) {
      const notGeneratedLabel = isLegalProfile(profile) ? "Violations" : "Findings";
      return res.status(404).json({ error: `${notGeneratedLabel} not yet generated.` });
    }

    if (req.query.severity) {
      violations = violations.filter((item) => item.severity === req.query.severity);
    }

    if (req.query.min_confidence !== undefined) {
      const minConfidence = Number(req.query.min_confidence);
      if (!Number.isNaN(minConfidence)) {
        violations = violations.filter((item) => Number(item.confidence) >= minConfidence);
      }
    }

    res.json({
      total: violations.length,
      analysis_profile: profile,
      label: profileMeta.finding_plural,
      findings: violations,
      violations
    });
  };

  app.get("/api/intelligence/violations", sendFindingsPayload);
  app.get("/api/intelligence/findings", sendFindingsPayload);

  app.get("/api/intelligence/timeline", (req, res) => {
    const timeline = readIntelligenceJson("timeline.json");
    if (!timeline) return res.status(404).json({ error: "Timeline not yet generated." });
    res.json(timeline);
  });

  app.get("/api/intelligence/narrative", (req, res) => {
    const narrativePath = path.join(currentRootDir, "_intelligence", "narrative.md");
    if (!fs.existsSync(narrativePath)) {
      return res.status(404).json({ error: "Narrative not yet generated." });
    }

    const markdown = fs.readFileSync(narrativePath, "utf8");
    if (req.query.format === "md") {
      res.type("text/markdown");
      return res.send(markdown);
    }
    res.json({ markdown });
  });

  app.get("/api/intelligence/gap-report", (req, res) => {
    const gapReport = readIntelligenceJson("gap_report.json");
    if (!gapReport) return res.status(404).json({ error: "Gap report not yet generated." });
    res.json(gapReport);
  });

  app.get("/api/intelligence/law-registry", (req, res) => {
    let registry = readIntelligenceJson("law_registry.json");
    if (!registry) return res.status(404).json({ error: "Law registry not yet generated." });

    if (req.query.resolved !== undefined) {
      const resolved = req.query.resolved === "true";
      registry = registry.filter((item) => item.resolved === resolved);
    }

    if (req.query.needs_argus === "true") {
      registry = registry.filter((item) => item.needs_argus);
    }

    res.json({ total: registry.length, registry });
  });

  app.get("/api/intelligence/dedup-report", (req, res) => {
    const dedupReport = readIntelligenceJson("dedup_report.json");
    if (!dedupReport) return res.status(404).json({ error: "Dedup report not yet generated." });
    if (req.query.summary === "true") return res.json({ stats: dedupReport.stats });
    res.json(dedupReport);
  });

  // ── Events: GET /api/events ──────────────────────────────────────────────
  app.get("/api/events", (req, res) => {
    const data = readIntelligenceJson("events.json");
    if (!data) return res.status(404).json({ error: "Events not yet generated. Run the intelligence pipeline first." });
    // Optional type filter
    if (req.query.type) {
      const filtered = (data.events || []).filter(e => e.type === req.query.type);
      return res.json({ stats: data.stats, total: filtered.length, events: filtered });
    }
    res.json(data);
  });

  // ── Events: GET /api/events/graph ───────────────────────────────────────
  app.get("/api/events/graph", (req, res) => {
    const data = readIntelligenceJson("event_graph.json");
    if (!data) return res.status(404).json({ error: "Event graph not yet generated." });
    // Optional edge type filter
    if (req.query.edge_type) {
      const filtered = (data.edges || []).filter(e => e.type === req.query.edge_type);
      return res.json({ ...data, edges: filtered, _filtered: true });
    }
    res.json(data);
  });

  // ── Case State: GET /api/case-state ─────────────────────────────────────
  app.get("/api/case-state", (req, res) => {
    const data = readIntelligenceJson("case_state.json");
    if (!data) return res.status(404).json({ error: "Case state not yet evaluated. Run the intelligence pipeline first." });
    res.json(data);
  });

  // ── Case State: GET /api/case-state/phase ───────────────────────────────
  app.get("/api/case-state/phase", (req, res) => {
    const data = readIntelligenceJson("case_state.json");
    if (!data) return res.status(404).json({ error: "Case state not yet evaluated." });
    res.json(data.phase);
  });

  // ── Case State: GET /api/case-state/findings ─────────────────────────────
  app.get("/api/case-state/findings", (req, res) => {
    const data = readIntelligenceJson("case_state.json");
    if (!data) return res.status(404).json({ error: "Case state not yet evaluated." });
    let findings = data.findings || [];
    if (req.query.severity) findings = findings.filter(f => f.severity === req.query.severity);
    if (req.query.type) findings = findings.filter(f => f.type === req.query.type);
    res.json({ total: findings.length, findings });
  });

  // ── Case State: GET /api/case-state/next-steps ──────────────────────────
  app.get("/api/case-state/next-steps", (req, res) => {
    const data = readIntelligenceJson("case_state.json");
    if (!data) return res.status(404).json({ error: "Case state not yet evaluated." });
    res.json({ total: (data.next_steps || []).length, next_steps: data.next_steps || [] });
  });

  // ── Comprehension: POST /api/comprehend/run ─────────────────────────────
  app.post("/api/comprehend/run", async (req, res) => {
    const { api_key, model, concurrency, max_samples, max_groups, analysis_profile } = req.body || {};

    if (!api_key) return res.status(400).json({ error: "Missing api_key" });

    try {
      const store  = ensurePipelineStore();
      const result = await runComprehension(store, currentRootDir, {
        apiKey:            String(api_key),
        model:             model ? String(model) : undefined,
        concurrency:       Number.isFinite(Number(concurrency))  ? Number(concurrency)  : 3,
        maxSamplesPerGroup: Number.isFinite(Number(max_samples)) ? Number(max_samples)  : 5,
        maxGroups:         Number.isFinite(Number(max_groups))   ? Number(max_groups)   : 20,
        analysisProfile:   typeof analysis_profile === "string" ? analysis_profile : undefined,
        outputDir:         path.join(currentRootDir, "_intelligence"),
      });
      res.json(result);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Comprehension: GET /api/comprehend/run-stream ───────────────────────
  app.get("/api/comprehend/run-stream", async (req, res) => {
    const { api_key, model, concurrency, max_samples, max_groups, analysis_profile } = req.query;

    res.setHeader("Content-Type",  "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection",    "keep-alive");
    if (typeof res.flushHeaders === "function") {
      res.flushHeaders();
    }
    res.write("retry: 3000\n\n");

    let streamClosed = false;
    const heartbeat = setInterval(() => {
      if (!streamClosed) {
        res.write(": ping\n\n");
      }
    }, 15000);

    const closeStream = () => {
      if (streamClosed) return;
      streamClosed = true;
      clearInterval(heartbeat);
      if (!res.writableEnded) {
        res.end();
      }
    };

    req.on("close", closeStream);
    req.on("aborted", closeStream);

    const send = (event, payload) => {
      if (streamClosed || res.writableEnded) return;
      res.write(`event: ${event}\n`);
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    };

    if (!api_key) {
      send("error", { error: "Missing api_key" });
      closeStream();
      return;
    }

    try {
      const store  = ensurePipelineStore();
      const result = await runComprehension(store, currentRootDir, {
        apiKey:            String(api_key),
        model:             model ? String(model) : undefined,
        concurrency:       Number.isFinite(Number(concurrency))   ? Number(concurrency)  : 3,
        maxSamplesPerGroup: Number.isFinite(Number(max_samples))  ? Number(max_samples)  : 5,
        maxGroups:         Number.isFinite(Number(max_groups))    ? Number(max_groups)   : 20,
        analysisProfile:   typeof analysis_profile === "string" ? analysis_profile : undefined,
        outputDir:         path.join(currentRootDir, "_intelligence"),
        onProgress:        (stage, detail) => send("progress", { stage, detail }),
      });
      send("complete", result);
      closeStream();
    } catch (err) {
      send("error", { error: err.message });
      closeStream();
    }
  });

  // ── Comprehension: GET /api/comprehend/overview ─────────────────────────
  app.get("/api/comprehend/overview", (req, res) => {
    const data = readComprehendFile("corpus_overview.json");
    if (!data) return res.status(404).json({
      error: "Corpus comprehension has not been run yet.",
      hint:  "POST /api/comprehend/run with your API key"
    });
    res.json(data);
  });

  // ── Comprehension: GET /api/comprehend/guide ────────────────────────────
  app.get("/api/comprehend/guide", (req, res) => {
    const md = readComprehendFile("corpus_guide.md", true);
    if (!md) return res.status(404).json({ error: "Corpus guide not yet generated." });
    if (req.query.format === "md") { res.type("text/markdown"); return res.send(md); }
    res.json({ markdown: md });
  });

  // ── Comprehension: GET /api/comprehend/groups ───────────────────────────
  app.get("/api/comprehend/groups", (req, res) => {
    const data = readComprehendFile("group_descriptions.json");
    if (!data) return res.status(404).json({ error: "Group descriptions not yet generated." });
    // Optional filter by domain
    if (req.query.domain) {
      const entry = data[req.query.domain];
      return entry ? res.json(entry)
                   : res.status(404).json({ error: `Domain '${req.query.domain}' not found.` });
    }
    res.json(data);
  });

  // ── Comprehension: GET /api/comprehend/strategies ───────────────────────
  app.get("/api/comprehend/strategies", (req, res) => {
    const data = readComprehendFile("restructure_options.json");
    if (!data) return res.status(404).json({ error: "Restructure strategies not yet generated." });
    res.json({ total: data.length, strategies: data });
  });

  // ── Raw file access ─────────────────────────────────────────────
  app.get("/api/raw", (req, res) => {
    const rel = req.query.file;
    if (!rel) return res.status(400).json({ error: "Missing ?file=" });
    const abs = path.resolve(currentRootDir, rel);
    if (!abs.startsWith(currentRootDir) || !fs.existsSync(abs)) {
      return res.status(404).json({ error: "File not found" });
    }
    res.sendFile(abs);
  });

  // ── Server info page ────────────────────────────────────────────
  app.get("/server", (req, res) => {
    const cats = summarizeCategories();
    const catList = Object.entries(cats)
      .map(([, value]) => `<li><strong>${value.label}</strong> — ${value.count} files</li>`)
      .join("\n");

    res.send(`<!DOCTYPE html><html><head><title>Discovery</title>
<style>body{font-family:system-ui;max-width:800px;margin:40px auto;padding:0 20px;color:#333}
a{color:#2563eb}code{background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:13px}
h2{border-bottom:2px solid #e5e7eb;padding-bottom:8px}ul{line-height:1.8}
.meta{color:#6b7280;font-size:14px}</style></head><body>
<h1>Discovery — Data Server</h1>
<p class="meta">Organized file access · Build #${buildCount} · ${endpoints.length} files from <code>${currentRootDir}</code></p>
<h2>Categories</h2><ul>${catList || "<li>No files loaded</li>"}</ul>
<h2>API</h2><ul>
<li><a href="/api/manifest">/api/manifest</a> — Full manifest with metadata</li>
<li><a href="/api/endpoints">/api/endpoints</a> — All endpoints</li>
<li><a href="/api/files">/api/files</a> — Files (filter: <code>?category=</code> <code>?ext=</code> <code>?kind=</code> <code>?group=</code>)</li>
<li><a href="/api/categories">/api/categories</a> — Category summary</li>
<li><a href="/api/tree">/api/tree</a> — Directory tree</li>
<li><a href="/api/search?q=example">/api/search?q=</a> — Search metadata</li>
<li><code>POST /api/rebuild</code> — Point at new directory: <code>{"root_dir":"..."}</code></li>
<li><a href="/api/raw?file=...">/api/raw?file=</a> — Raw file access</li>
<li><a href="/api/file-detail?file=...">/api/file-detail?file=</a> — Enriched file detail</li>
</ul>
<h2>Pipeline API</h2><ul>
<li><a href="/api/pipeline/stats">/api/pipeline/stats</a> — Pipeline run stats & aggregates</li>
<li><a href="/api/pipeline/entities">/api/pipeline/entities</a> — Global entity index (<code>?type=people|laws|organizations|locations|dates</code>)</li>
<li><a href="/api/pipeline/relationships">/api/pipeline/relationships</a> — Cross-file relationships (<code>?min_strength=</code>)</li>
<li><a href="/api/pipeline/timeline">/api/pipeline/timeline</a> — Chronological timeline (<code>?from=&to=</code>)</li>
<li><a href="/api/pipeline/search?q=example">/api/pipeline/search?q=</a> — Deep search across enriched data</li>
</ul>
<h2>Intelligence API</h2><ul>
<li><code>POST /api/intelligence/run</code> — Run L5–L7 with <code>{"api_key":"...","concurrency":4,"bulk_fast":false,"use_cache":true,"skip_dedup":false,"kb_enabled":true,"persist_to_graph":false,"augment_extraction":false,"skip_verification":false,"analysis_profile":"general|office|law-firm|business|legal"}</code></li>
<li><a href="/api/intelligence/summary">/api/intelligence/summary</a> — Latest intelligence summary</li>
<li><a href="/api/intelligence/case-graph">/api/intelligence/case-graph</a> — Full case graph</li>
<li><a href="/api/intelligence/violations">/api/intelligence/violations</a> — Violations list (<code>?severity=&min_confidence=</code>)</li>
<li><a href="/api/intelligence/timeline">/api/intelligence/timeline</a> — Intelligence timeline</li>
<li><a href="/api/intelligence/gap-report">/api/intelligence/gap-report</a> — Gap report</li>
</ul>
<h2>Events & Case State</h2><ul>
<li><a href="/api/events">/api/events</a> — Formalized events (<code>?type=incident|complaint|…</code>)</li>
<li><a href="/api/events/graph">/api/events/graph</a> — Causal/temporal event graph (<code>?edge_type=CAUSED|PRECEDED_BY|RELATED_TO</code>)</li>
<li><a href="/api/case-state">/api/case-state</a> — Full case state evaluation</li>
<li><a href="/api/case-state/phase">/api/case-state/phase</a> — Current case phase</li>
<li><a href="/api/case-state/findings">/api/case-state/findings</a> — Anomalies & gaps (<code>?severity=high&type=anomaly</code>)</li>
<li><a href="/api/case-state/next-steps">/api/case-state/next-steps</a> — Recommended next actions</li>
</ul>
<h2>Comprehension API — Layer C</h2><ul>
<li><code>POST /api/comprehend/run</code> — Understand + guide: <code>{"api_key":"...","concurrency":3}</code></li>
<li><a href="/api/comprehend/run-stream">/api/comprehend/run-stream?api_key=…</a> — SSE streaming run</li>
<li><a href="/api/comprehend/overview">/api/comprehend/overview</a> — Full corpus understanding JSON</li>
<li><a href="/api/comprehend/guide?format=md">/api/comprehend/guide?format=md</a> — Human-readable guide (Markdown)</li>
<li><a href="/api/comprehend/groups">/api/comprehend/groups</a> — Per-category descriptions (<code>?domain=legal</code>)</li>
<li><a href="/api/comprehend/strategies">/api/comprehend/strategies</a> — Organisation strategies</li>
</ul></body></html>`);
  });

  // ── Dashboard UI ────────────────────────────────────────────────
  app.get("/", (req, res) => {
    if (fs.existsSync(UI_FILE)) {
      return res.sendFile(UI_FILE);
    }
    return res.redirect("/server");
  });

  app.get("/onboarding", (req, res) => {
    if (fs.existsSync(ONBOARDING_UI_FILE)) {
      return res.sendFile(ONBOARDING_UI_FILE);
    }
    return res.status(404).send("Onboarding UI file not found");
  });

  app.get("/agent-workspace", (req, res) => {
    if (fs.existsSync(AGENT_WORKSPACE_FILE)) {
      return res.sendFile(AGENT_WORKSPACE_FILE);
    }
    return res.redirect("/");
  });

  app.get("/awareness-agent-workspace", (req, res) => {
    if (fs.existsSync(AWARENESS_AGENT_WORKSPACE_FILE)) {
      return res.sendFile(AWARENESS_AGENT_WORKSPACE_FILE);
    }
    return res.redirect("/");
  });

  return app;
}

function startDiscoveryServer(options = {}) {
  const port = Number(options.port || PORT);
  const app = createDiscoveryApp();

  try {
    if (isAllowedRootDir(currentRootDir)) {
      rebuildFromDir(currentRootDir);
    } else {
      console.warn(`⚠️  Skipping initial rebuild; ROOT_DIR outside strict scope: ${currentRootDir}`);
    }
  } catch (err) {
    console.warn(`⚠️  Initial ROOT_DIR not found (${currentRootDir}). POST /api/rebuild to set one.`);
  }

  return new Promise((resolve, reject) => {
    const server = app.listen(port, () => {
      const address = server.address();
      const resolvedPort = typeof address === "object" && address ? address.port : port;
      console.log(`🚀 Discovery → http://localhost:${resolvedPort}`);
      resolve({ app, server, port: resolvedPort });
    });
    server.on("error", reject);
  });
}

module.exports = {
  createDiscoveryApp,
  startDiscoveryServer,
  rebuildFromDir,
};

if (require.main === module) {
  startDiscoveryServer().catch((err) => {
    console.error("Failed to start Discovery:", err);
    process.exit(1);
  });
}