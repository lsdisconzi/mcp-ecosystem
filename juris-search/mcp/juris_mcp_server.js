#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const childProcess = require("child_process");
const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { StreamableHTTPServerTransport } = require("@modelcontextprotocol/sdk/server/streamableHttp.js");
const {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} = require("@modelcontextprotocol/sdk/types.js");

const ROOT_DIR = path.resolve(__dirname, "..");
const START_SCRIPT = path.join(ROOT_DIR, "start.sh");
const STOP_SCRIPT = path.join(ROOT_DIR, "stop.sh");

const DEFAULT_BASE_URL = process.env.JURIS_SEARCH_BASE_URL || "http://127.0.0.1:8000";
let jurisBaseUrl = normalizeBaseUrl(DEFAULT_BASE_URL);

function normalizeBaseUrl(url) {
  const trimmed = String(url || "").trim().replace(/\/+$/, "");
  if (!trimmed) {
    return "http://127.0.0.1:8000";
  }
  return trimmed;
}

function joinUrl(baseUrl, routePath, query) {
  const url = new URL(routePath, `${baseUrl}/`);
  if (query && typeof query === "object") {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item === undefined || item === null || item === "") continue;
          url.searchParams.append(key, String(item));
        }
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

function toPosixPath(value) {
  return String(value || "").replace(/\\/g, "/");
}

function encodeRouteSubpath(value, fieldName) {
  const normalized = toPosixPath(value).trim().replace(/^\/+/, "");
  if (!normalized || normalized === ".") {
    throw new Error(`${fieldName} is required`);
  }
  if (normalized.includes("..")) {
    throw new Error(`${fieldName} must be a safe relative path`);
  }
  return normalized
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

async function parseResponseBody(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  if (contentType.startsWith("text/") || contentType.includes("javascript")) {
    return response.text();
  }
  const arrayBuffer = await response.arrayBuffer();
  return {
    content_type: contentType || "application/octet-stream",
    size_bytes: arrayBuffer.byteLength,
    content_base64: Buffer.from(arrayBuffer).toString("base64"),
  };
}

async function jurisRequest({ method, routePath, query, body, headers }) {
  const url = joinUrl(jurisBaseUrl, routePath, query);
  const init = {
    method,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...(headers || {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  };

  const response = await fetch(url, init);
  const payload = await parseResponseBody(response);

  if (!response.ok) {
    const errorMessage = typeof payload === "string"
      ? payload
      : (payload && payload.detail) || (payload && payload.error) || JSON.stringify(payload);
    throw new Error(`${method} ${routePath} failed (${response.status}): ${errorMessage}`);
  }

  return payload;
}

function jsonResult(payload) {
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
  };
}

function boolSchema(description, defaultValue) {
  return { type: "boolean", description, ...(defaultValue === undefined ? {} : { default: defaultValue }) };
}

function numSchema(description, minimum, maximum) {
  const schema = { type: "number", description };
  if (minimum !== undefined) schema.minimum = minimum;
  if (maximum !== undefined) schema.maximum = maximum;
  return schema;
}

function intSchema(description, minimum, maximum) {
  const schema = { type: "integer", description };
  if (minimum !== undefined) schema.minimum = minimum;
  if (maximum !== undefined) schema.maximum = maximum;
  return schema;
}

function runScript(scriptPath, envOverrides) {
  return new Promise((resolve, reject) => {
    childProcess.execFile(
      "bash",
      [scriptPath],
      {
        cwd: ROOT_DIR,
        env: { ...process.env, ...(envOverrides || {}) },
      },
      (error, stdout, stderr) => {
        if (error) {
          const detail = stderr || stdout || error.message;
          reject(new Error(`Script failed: ${path.basename(scriptPath)}: ${detail}`));
          return;
        }
        resolve({ stdout: String(stdout || "").trim(), stderr: String(stderr || "").trim() });
      }
    );
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth(timeoutSeconds) {
  const timeoutMs = Math.max(1, Number(timeoutSeconds || 20)) * 1000;
  const started = Date.now();
  let lastError = null;

  while ((Date.now() - started) <= timeoutMs) {
    try {
      const payload = await jurisRequest({ method: "GET", routePath: "/health" });
      return { ok: true, health: payload };
    } catch (error) {
      lastError = error;
      await sleep(500);
    }
  }

  return {
    ok: false,
    error: lastError ? lastError.message : "Timed out waiting for health endpoint",
  };
}

async function handleStartService(args) {
  if (!fs.existsSync(START_SCRIPT)) {
    throw new Error(`start.sh not found at ${START_SCRIPT}`);
  }

  const port = args && args.port ? Number(args.port) : Number(process.env.PORT || 8000);
  const host = args && args.host ? String(args.host) : String(process.env.HOST || "0.0.0.0");

  const output = await runScript(START_SCRIPT, {
    PORT: String(port),
    HOST: host,
    ...(args && args.build_frontend !== undefined
      ? { JURIS_SEARCH_BUILD_FRONTEND: args.build_frontend ? "1" : "0" }
      : {}),
  });

  jurisBaseUrl = normalizeBaseUrl(`http://127.0.0.1:${port}`);

  const shouldWait = args && args.wait_for_health !== undefined ? Boolean(args.wait_for_health) : true;
  let health = null;
  if (shouldWait) {
    health = await waitForHealth(args && args.health_timeout_seconds);
  }

  return {
    ok: true,
    started: true,
    base_url: jurisBaseUrl,
    port,
    host,
    health,
    stdout: output.stdout,
    stderr: output.stderr,
  };
}

async function handleStopService() {
  if (!fs.existsSync(STOP_SCRIPT)) {
    throw new Error(`stop.sh not found at ${STOP_SCRIPT}`);
  }

  const output = await runScript(STOP_SCRIPT);
  return {
    ok: true,
    stopped: true,
    base_url: jurisBaseUrl,
    stdout: output.stdout,
    stderr: output.stderr,
  };
}

async function handleUploadFile(args) {
  const filePathRaw = String(args.file_path || "").trim();
  if (!filePathRaw) {
    throw new Error("file_path is required");
  }

  const filePath = path.resolve(filePathRaw);
  if (!fs.existsSync(filePath)) {
    throw new Error(`File not found: ${filePath}`);
  }

  const stats = fs.statSync(filePath);
  if (!stats.isFile()) {
    throw new Error(`Not a file: ${filePath}`);
  }

  const bytes = fs.readFileSync(filePath);
  const form = new FormData();
  form.append("file", new Blob([bytes]), path.basename(filePath));
  form.append("court", String(args.court || "TJRS"));

  const url = joinUrl(jurisBaseUrl, "/api/upload");
  const response = await fetch(url, {
    method: "POST",
    body: form,
  });

  const payload = await parseResponseBody(response);
  if (!response.ok) {
    const errorMessage = typeof payload === "string"
      ? payload
      : (payload && payload.detail) || (payload && payload.error) || JSON.stringify(payload);
    throw new Error(`POST /api/upload failed (${response.status}): ${errorMessage}`);
  }

  return payload;
}

const endpointTools = [
  {
    name: "juris_chat",
    description: "Chat with the jurisprudence assistant via /api/chat.",
    route: { method: "POST", path: "/api/chat" },
    schema: {
      type: "object",
      properties: {
        message: { type: "string", description: "User message." },
        conversation: {
          type: "array",
          description: "Optional conversation history.",
          items: {
            type: "object",
            properties: {
              role: { type: "string" },
              content: { type: "string" },
            },
            required: ["role", "content"],
            additionalProperties: false,
          },
        },
        file_text: { type: "string", description: "Extracted file text if available." },
        file_name: { type: "string", description: "Uploaded file name." },
        model: { type: "string", description: "Optional DeepSeek model override." },
        court: { type: "string", description: "Court key: TJRS, TJSP, STF." },
      },
      required: ["message"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "juris_upload_file",
    description: "Upload a local file for assistant analysis (/api/upload).",
    route: { method: "POST", path: "/api/upload" },
    schema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "Absolute or workspace-relative file path." },
        court: { type: "string", description: "Court key (default TJRS)." },
      },
      required: ["file_path"],
      additionalProperties: false,
    },
    handler: "upload_file",
    toRequest: () => ({}),
  },
  {
    name: "juris_search_start",
    description: "Start an async jurisprudence search job.",
    route: { method: "POST", path: "/api/search" },
    schema: {
      type: "object",
      properties: {
        search_text: { type: "string", description: "Main search text." },
        tipo_processo: { type: "string" },
        classe_cnj: { type: "string" },
        assunto_cnj: { type: "string" },
        comarca_origem: { type: "string" },
        relator: { type: "string" },
        orgao_julgador: { type: "string" },
        tipo_decisao: { type: "string" },
        tribunal: { type: "string", description: "Court alias; may be overridden by court/courts." },
        court: { type: "string", description: "Single court key: TJRS, TJSP, STF." },
        courts: {
          type: "array",
          description: "Court list or [\"ALL\"].",
          items: { type: "string" },
        },
        search_index: { type: "string", description: "acordao or inteiro_teor.", default: "acordao" },
        max_results: intSchema("Maximum number of results.", 1, 500),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "juris_search_status",
    description: "Get status of a search/download job by id.",
    route: { method: "GET", path: "/api/search/status/{job_id}" },
    schema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Job id returned from search_start/download." },
      },
      required: ["job_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/search/status/${encodeURIComponent(args.job_id)}`,
    }),
  },
  {
    name: "juris_results",
    description: "Fetch full results payload for a job.",
    route: { method: "GET", path: "/api/results/{job_id}" },
    schema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Job id." },
      },
      required: ["job_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/results/${encodeURIComponent(args.job_id)}`,
    }),
  },
  {
    name: "juris_search_history",
    description: "List persisted search history files.",
    route: { method: "GET", path: "/api/search/history" },
    schema: {
      type: "object",
      properties: {
        limit: intSchema("History entries to return (max 200).", 1, 200),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "juris_search_history_file",
    description: "Read one persisted search history JSON by file name.",
    route: { method: "GET", path: "/api/search/history/{filename}" },
    schema: {
      type: "object",
      properties: {
        filename: { type: "string", description: "History file name, e.g. search_...json" },
      },
      required: ["filename"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/search/history/${encodeURIComponent(args.filename)}`,
    }),
  },
  {
    name: "juris_storage_paths",
    description: "Get configured storage directories and link roots.",
    route: { method: "GET", path: "/api/storage/paths" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_download",
    description: "Start async batch download or run legacy single download flow.",
    route: { method: "POST", path: "/api/download" },
    schema: {
      type: "object",
      properties: {
        results: {
          type: "array",
          description: "Batch results payload.",
          items: { type: "object", additionalProperties: true },
        },
        url: { type: "string", description: "Legacy single download URL." },
        numero_processo: { type: "string", description: "Process number for legacy flow." },
        inteiro_url: { type: "string", description: "Legacy alias for url." },
        folder_name: { type: "string", description: "Optional destination folder name." },
        tribunal: { type: "string", description: "Court key override." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "juris_download_status",
    description: "Get status for a download job started via /api/download.",
    route: { method: "GET", path: "/api/download/status/{job_id}" },
    schema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Download job id." },
      },
      required: ["job_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/download/status/${encodeURIComponent(args.job_id)}`,
    }),
  },
  {
    name: "juris_download_batch",
    description: "Run legacy-compatible synchronous batch download endpoint.",
    route: { method: "POST", path: "/api/download-batch" },
    schema: {
      type: "object",
      properties: {
        results: {
          type: "array",
          items: { type: "object", additionalProperties: true },
          minItems: 1,
        },
        folder_name: { type: "string" },
        tribunal: { type: "string" },
      },
      required: ["results"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "juris_health",
    description: "Get API health status.",
    route: { method: "GET", path: "/api/health" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_health_legacy",
    description: "Get legacy /health status.",
    route: { method: "GET", path: "/health" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_stats",
    description: "Get aggregate stats from /api/stats.",
    route: { method: "GET", path: "/api/stats" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_stats_legacy",
    description: "Get aggregate stats from /stats.",
    route: { method: "GET", path: "/stats" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_docx_index",
    description: "Read the DOCX index payload.",
    route: { method: "GET", path: "/api/docx/index" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_json_index",
    description: "Read the JSON index payload.",
    route: { method: "GET", path: "/api/json/index" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_docx_rebuild",
    description: "Trigger DOCX rebuild pipeline.",
    route: { method: "POST", path: "/api/docx/rebuild" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_json_rebuild",
    description: "Trigger JSON rebuild pipeline.",
    route: { method: "POST", path: "/api/json/rebuild" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_storage_rebuild",
    description: "Trigger DOCX+JSON rebuild and export link synchronization.",
    route: { method: "POST", path: "/api/storage/rebuild" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_master_index_stats",
    description: "Get master indexer stats/availability.",
    route: { method: "GET", path: "/api/master-index/stats" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_master_index_documents",
    description: "List master-index documents with optional filters.",
    route: { method: "GET", path: "/api/master-index/documents" },
    schema: {
      type: "object",
      properties: {
        tribunal: { type: "string" },
        year: { type: "string" },
        relator: { type: "string" },
        outcome: { type: "string" },
        text: { type: "string" },
        limit: intSchema("Max documents per page (max 500).", 1, 500),
        offset: intSchema("Offset for pagination.", 0),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "juris_master_index_document",
    description: "Get one master-index document by id.",
    route: { method: "GET", path: "/api/master-index/document/{doc_id}" },
    schema: {
      type: "object",
      properties: {
        doc_id: { type: "string" },
      },
      required: ["doc_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/master-index/document/${encodeURIComponent(args.doc_id)}`,
    }),
  },
  {
    name: "juris_master_index_rebuild",
    description: "Rebuild master-index artifacts.",
    route: { method: "POST", path: "/api/master-index/rebuild" },
    schema: {
      type: "object",
      properties: {
        force_ingest: boolSchema("If true, forces full ingest.", false),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "juris_master_index_markdown",
    description: "Fetch master-index markdown view.",
    route: { method: "GET", path: "/api/master-index/markdown" },
    schema: {
      type: "object",
      properties: {
        rebuild: boolSchema("If true, regenerate markdown before serving.", false),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "juris_master_index_search",
    description: "Proxy semantic search through the qdrant gateway.",
    route: { method: "POST", path: "/api/master-index/search" },
    schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query text." },
        collection_name: { type: "string" },
        limit: intSchema("Result limit.", 1, 500),
        filters: { type: "object", additionalProperties: true },
        min_score: numSchema("Minimum score threshold.", 0, 1),
      },
      required: ["query"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "juris_ui_home",
    description: "Fetch frontend index response at /.",
    route: { method: "GET", path: "/" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_ui_juris_search",
    description: "Fetch frontend index response at /juris-search.",
    route: { method: "GET", path: "/juris-search" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_ui_juris_search_slash",
    description: "Fetch frontend index response at /juris-search/.",
    route: { method: "GET", path: "/juris-search/" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_favicon",
    description: "Fetch root frontend favicon.",
    route: { method: "GET", path: "/favicon.svg" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_juris_search_favicon",
    description: "Fetch /juris-search frontend favicon.",
    route: { method: "GET", path: "/juris-search/favicon.svg" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_icons",
    description: "Fetch root frontend icon sprite.",
    route: { method: "GET", path: "/icons.svg" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_juris_search_icons",
    description: "Fetch /juris-search frontend icon sprite.",
    route: { method: "GET", path: "/juris-search/icons.svg" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "juris_assets_file",
    description: "Fetch a file from /assets mount.",
    route: { method: "GET", path: "/assets" },
    schema: {
      type: "object",
      properties: {
        asset_path: { type: "string", description: "Relative asset path under /assets." },
      },
      required: ["asset_path"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/assets/${encodeRouteSubpath(args.asset_path, "asset_path")}`,
    }),
  },
  {
    name: "juris_scoped_assets_file",
    description: "Fetch a file from /juris-search/assets mount.",
    route: { method: "GET", path: "/juris-search/assets" },
    schema: {
      type: "object",
      properties: {
        asset_path: { type: "string", description: "Relative asset path under /juris-search/assets." },
      },
      required: ["asset_path"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/juris-search/assets/${encodeRouteSubpath(args.asset_path, "asset_path")}`,
    }),
  },
];

// ── Direct file-read tools (no HTTP required) ──────────────────────────────

const QDRANT_MGMT_API = process.env.QDRANT_MANAGEMENT_API || "http://localhost:8066";
const LEGAL_FRAMEWORK_COLLECTION = "legal_framework";
const MASTER_INDEX_PATH = path.join(ROOT_DIR, "master_index", "master_index.json");
const FLATTEN_REPORT_PATH = path.join(ROOT_DIR, "flatten_report.json");

function loadMasterIndex() {
  if (!fs.existsSync(MASTER_INDEX_PATH)) {
    throw new Error(`Master index not found at ${MASTER_INDEX_PATH}`);
  }
  return JSON.parse(fs.readFileSync(MASTER_INDEX_PATH, "utf-8"));
}

function loadFlattenReport() {
  if (!fs.existsSync(FLATTEN_REPORT_PATH)) {
    throw new Error(`Flatten report not found at ${FLATTEN_REPORT_PATH}`);
  }
  return JSON.parse(fs.readFileSync(FLATTEN_REPORT_PATH, "utf-8"));
}

const fileTools = [
  {
    name: "juris_flat_corpus_stats",
    description: "Get flattened corpus statistics from flatten_report.json (file counts by tribunal, dedup stats).",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    handler: async () => {
      const report = loadFlattenReport();
      return {
        generated_at: report.generated_at,
        corpus_path: report.corpus_flat_path,
        total_collected: report.total_collected,
        unique_by_hash: report.unique_by_hash,
        duplicates_removed: report.duplicates_removed,
        by_tribunal: report.by_tribunal,
        source_stats: report.source_stats,
      };
    },
  },
  {
    name: "juris_citations",
    description: "Find documents that cite a given process number. Extracts citation network from master index.",
    inputSchema: {
      type: "object",
      properties: {
        processo: {
          type: "string",
          description: "Process number to search for in citations (e.g., '0027812-80.2013.4.01.3400' or 'REsp 1584465').",
        },
        limit: {
          type: "integer",
          description: "Max citing documents to return (default 20, max 100).",
          default: 20,
          minimum: 1,
          maximum: 100,
        },
      },
      required: ["processo"],
      additionalProperties: false,
    },
    handler: async (args) => {
      const index = loadMasterIndex();
      const docs = index.documents || [];
      const processo = String(args.processo || "").trim().toLowerCase();
      if (!processo) {
        throw new Error("processo is required and must not be empty");
      }
      const limit = Math.min(Math.max(1, Number(args.limit) || 20), 100);

      // Normalize: strip non-digits for comparison
      const digits = processo.replace(/\D/g, "");

      const citing = [];
      for (const doc of docs) {
        const cited = (doc.cited_processes || []).map((c) => String(c).toLowerCase());
        const citedDigits = cited.map((c) => c.replace(/\D/g, ""));
        if (
          cited.some((c) => c.includes(processo)) ||
          citedDigits.some((c) => c.includes(digits))
        ) {
          citing.push({
            id: doc.id,
            tribunal: doc.tribunal,
            numero_processo: doc.numero_processo,
            relator: doc.relator,
            ano: doc.ano,
            outcome: doc.outcomes,
            ementa: (doc.ementa || "").substring(0, 300),
            cited_processes: doc.cited_processes,
          });
          if (citing.length >= limit) break;
        }
      }

      // Also find the target document itself
      const target = docs.find((d) => d.id.includes(digits) ||
        (d.numero_processo || "").replace(/\D/g, "").includes(digits) ||
        (d.cnj_numero || "").replace(/\D/g, "").includes(digits));

      return {
        query: args.processo,
        target_document: target ? {
          id: target.id,
          tribunal: target.tribunal,
          numero_processo: target.numero_processo,
          relator: target.relator,
          ementa: (target.ementa || "").substring(0, 500),
        } : null,
        citing_count: citing.length,
        citing_documents: citing,
      };
    },
  },
  {
    name: "juris_relator_network",
    description: "Get relator co-occurrence network from master index. Shows which judges/relators appear together on decisions.",
    inputSchema: {
      type: "object",
      properties: {
        relator: {
          type: "string",
          description: "Optional: filter to a specific relator to see their co-relators.",
        },
        min_cooccurrence: {
          type: "integer",
          description: "Minimum co-occurrence count to include (default 2).",
          default: 2,
          minimum: 1,
        },
        limit: {
          type: "integer",
          description: "Max results (default 50).",
          default: 50,
          minimum: 1,
          maximum: 200,
        },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const index = loadMasterIndex();
      const docs = index.documents || [];
      const filterRelator = (args.relator || "").trim().toLowerCase();
      const minCooccur = Math.max(1, Number(args.min_cooccurrence) || 2);
      const limit = Math.min(Math.max(1, Number(args.limit) || 50), 200);

      // Build co-relator pairs from documents that have a relator
      const cooccurrence = new Map();
      const relatorDocs = new Map();

      for (const doc of docs) {
        const relator = (doc.relator || "").trim();
        if (!relator) continue;

        // Track docs per relator
        if (!relatorDocs.has(relator)) relatorDocs.set(relator, []);
        relatorDocs.get(relator).push(doc.id);

        // Co-occurrence with cited_processes that reference other decisions
        // (We use the text_excerpt/ementa context rather than true multi-relator panels)
      }

      // Real co-relator detection: look for documents where text mentions
      // multiple relators (panel decisions)
      const pairs = new Map();
      for (const doc of docs) {
        const text = [
          doc.ementa || "",
          doc.text_excerpt || "",
        ].join(" ").toLowerCase();

        const mentioned = [];
        for (const [name] of relatorDocs) {
          if (name.toLowerCase() === (doc.relator || "").toLowerCase()) continue;
          // Check if this relator is mentioned in the text (as part of panel)
          const nameParts = name.toLowerCase().split(" ").filter((p) => p.length > 3);
          if (nameParts.some((p) => text.includes(p))) {
            mentioned.push(name);
          }
        }

        if (mentioned.length > 0 && doc.relator) {
          for (const co of mentioned) {
            const pair = [doc.relator, co].sort().join(" ||| ");
            pairs.set(pair, (pairs.get(pair) || 0) + 1);
          }
        }
      }

      // Filter and sort
      let results = [];
      for (const [pair, count] of pairs) {
        if (count < minCooccur) continue;
        const [a, b] = pair.split(" ||| ");
        if (filterRelator && !a.toLowerCase().includes(filterRelator) && !b.toLowerCase().includes(filterRelator)) continue;
        results.push({ relator_a: a, relator_b: b, cooccurrence_count: count });
      }

      results.sort((a, b) => b.cooccurrence_count - a.cooccurrence_count);
      results = results.slice(0, limit);

      return {
        filter_relator: args.relator || null,
        min_cooccurrence: minCooccur,
        total_pairs: results.length,
        top_relators: index.top_relators || {},
        pairs: results,
      };
    },
  },
  {
    name: "juris_master_index_summary",
    description: "Get a comprehensive summary of the master index including stats, top entities, and flat corpus cross-reference.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    handler: async () => {
      const index = loadMasterIndex();
      let flattenStats = null;
      try {
        const report = loadFlattenReport();
        flattenStats = {
          unique_files: report.unique_by_hash,
          by_tribunal: report.by_tribunal,
        };
      } catch (_) { /* flatten report not available */ }

      return {
        generated_at: index.generated_at,
        total_documents: index.total_documents,
        search_jobs: index.search_jobs_count,
        by_tribunal: index.by_tribunal,
        by_year: index.by_year,
        by_outcome: index.by_outcome,
        top_relators: index.top_relators,
        top_comarcas: index.top_comarcas,
        qdrant: index.qdrant,
        flat_corpus: flattenStats,
        sample_document_ids: (index.documents || []).slice(0, 5).map((d) => d.id),
      };
    },
  },
  {
    name: "juris_legal_framework_search",
    description: "Semantic search across the legal framework collection (BR/CL/INT aviation law articles). Uses Qdrant vector search.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search query in natural language (e.g., 'consumer rights in air transport', 'airline liability for delays').",
        },
        jurisdiction: {
          type: "string",
          description: "Filter by jurisdiction: BR, CL, or INT.",
        },
        norm_type: {
          type: "string",
          description: "Filter by norm type: duty, prohibition, penalty, definition, right, procedural, power, exemption.",
        },
        framework_code: {
          type: "string",
          description: "Filter by framework code (e.g., CDC, CC, CBA, MC99, ACHR).",
        },
        limit: {
          type: "integer",
          description: "Max results (default 10, max 50).",
          default: 10,
          minimum: 1,
          maximum: 50,
        },
        min_score: {
          type: "number",
          description: "Minimum relevance score 0-1 (default 0.3).",
          default: 0.3,
          minimum: 0,
          maximum: 1,
        },
      },
      required: ["query"],
      additionalProperties: false,
    },
    handler: async (args) => {
      const query = String(args.query || "").trim();
      if (!query) throw new Error("query is required");

      const limit = Math.min(Math.max(1, Number(args.limit) || 10), 50);
      const minScore = Number(args.min_score) ?? 0.3;

      // Build filters
      const must = [];
      if (args.jurisdiction) {
        must.push({ key: "jurisdiction", match: { value: String(args.jurisdiction).toUpperCase() } });
      }
      if (args.norm_type) {
        must.push({ key: "norm_type", match: { value: String(args.norm_type).toLowerCase() } });
      }
      if (args.framework_code) {
        must.push({ key: "framework_code", match: { value: String(args.framework_code) } });
      }

      const searchPayload = {
        collection_name: LEGAL_FRAMEWORK_COLLECTION,
        query_text: query,
        limit: limit,
        score_threshold: minScore,
        with_payload: true,
        with_vector: false,
      };
      if (must.length > 0) {
        searchPayload.filters = { must };
      }

      const url = `${QDRANT_MGMT_API}/v1/qdrant/search`;
      const init = {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(searchPayload),
      };

      let response;
      try {
        response = await fetch(url, init);
      } catch (err) {
        // Return graceful error with query info
        return {
          ok: false,
          error: `Qdrant search failed: ${err.message}`,
          query: query,
          hint: "Ensure Qdrant management API is running at " + QDRANT_MGMT_API,
        };
      }

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        return { ok: false, error: `Search failed (${response.status}): ${text.substring(0, 300)}`, query: query };
      }

      const data = await response.json();
      const results = (data.results || data.hits || []).map((r) => ({
        score: r.score || r._score || null,
        doc_id: r.payload?.doc_id || r.id,
        jurisdiction: r.payload?.jurisdiction,
        framework_code: r.payload?.framework_code,
        framework_name: r.payload?.metadata?.framework_name || r.payload?.framework_name,
        article_number: r.payload?.article_number,
        reference: r.payload?.metadata?.reference || r.payload?.reference,
        theme: r.payload?.metadata?.theme || r.payload?.theme,
        norm_type: r.payload?.norm_type,
        norm_scope: r.payload?.norm_scope,
        text: (r.payload?.metadata?.text || r.payload?.text || "").substring(0, 600),
        hierarchy_label: r.payload?.metadata?.hierarchy_label,
        regulated_subject: r.payload?.metadata?.regulated_subject || r.payload?.regulated_subject,
        duty_bearer_roles: r.payload?.metadata?.duty_bearer_roles || r.payload?.duty_bearer_roles,
        right_holder_roles: r.payload?.metadata?.right_holder_roles || r.payload?.right_holder_roles,
        eli_id: r.payload?.metadata?.eli_id,
      }));

      return {
        ok: true,
        query: query,
        filters: {
          jurisdiction: args.jurisdiction || null,
          norm_type: args.norm_type || null,
          framework_code: args.framework_code || null,
        },
        total_results: results.length,
        results: results,
      };
    },
  },
  {
    name: "juris_legal_framework_stats",
    description: "Get legal framework collection statistics (article counts by jurisdiction, norm type, framework).",
    inputSchema: {
      type: "object",
      properties: {
        jurisdiction: {
          type: "string",
          description: "Optional: filter stats to a specific jurisdiction (BR, CL, INT).",
        },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      // Load from the ingestion report
      const reportPath = path.join(ROOT_DIR, "law_ingestion_report.json");
      if (!fs.existsSync(reportPath)) {
        return { ok: false, error: "Ingestion report not found. Run ingest_laws.py first." };
      }

      const report = JSON.parse(fs.readFileSync(reportPath, "utf-8"));

      if (args.jurisdiction) {
        const jd = String(args.jurisdiction).toUpperCase();
        // Load articles from source or report
        return {
          jurisdiction: jd,
          total: report.by_jurisdiction?.[jd] || 0,
          collection: report.collection,
          generated_at: report.generated_at,
          all_jurisdictions: report.by_jurisdiction,
          top_frameworks: Object.entries(report.by_framework || {})
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10),
          by_norm_type: report.by_norm_type,
        };
      }

      // Also get collection info from Qdrant
      let collectionInfo = null;
      try {
        const infoUrl = `${QDRANT_MGMT_API}/v1/qdrant/collections/${LEGAL_FRAMEWORK_COLLECTION}/summary`;
        const resp = await fetch(infoUrl);
        if (resp.ok) collectionInfo = await resp.json();
      } catch (_) { /* optional */ }

      return {
        ok: true,
        collection: report.collection,
        generated_at: report.generated_at,
        total_articles: report.total_articles,
        ingested: report.ingested,
        by_jurisdiction: report.by_jurisdiction,
        by_norm_type: report.by_norm_type,
        by_scope: report.by_scope,
        top_frameworks: Object.entries(report.by_framework || {})
          .sort((a, b) => b[1] - a[1])
          .slice(0, 15)
          .map(([code, count]) => ({ code, count })),
        qdrant_info: collectionInfo,
      };
    },
  },
];

const fileToolMap = new Map(fileTools.map((tool) => [tool.name, tool]));

const endpointToolMap = new Map(endpointTools.map((tool) => [tool.name, tool]));

function describeTools() {
  const shared = [
    {
      name: "juris_set_base_url",
      description: "Set target juris-search base URL for HTTP-backed tools.",
      inputSchema: {
        type: "object",
        properties: {
          base_url: { type: "string", description: "Example: http://127.0.0.1:8000" },
        },
        required: ["base_url"],
        additionalProperties: false,
      },
    },
    {
      name: "juris_start_service",
      description: "Start local juris-search service using start.sh and optional env overrides.",
      inputSchema: {
        type: "object",
        properties: {
          host: { type: "string", description: "Host binding passed to start.sh (default 0.0.0.0)." },
          port: intSchema("Port passed to start.sh (default 8000).", 1, 65535),
          build_frontend: boolSchema("Set JURIS_SEARCH_BUILD_FRONTEND=1 before start.", false),
          wait_for_health: boolSchema("Poll /health after start.", true),
          health_timeout_seconds: numSchema("Health wait timeout in seconds.", 1, 120),
        },
        additionalProperties: false,
      },
    },
    {
      name: "juris_stop_service",
      description: "Stop local juris-search service using stop.sh.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
    },
  ];

  const generated = endpointTools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.schema,
  }));

  const fileBased = fileTools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
  }));

  return [...shared, ...generated, ...fileBased];
}

async function executeEndpointTool(name, args) {
  const tool = endpointToolMap.get(name);
  if (!tool) {
    throw new Error(`Unknown endpoint tool: ${name}`);
  }

  if (tool.handler === "upload_file") {
    return handleUploadFile(args || {});
  }

  const requestShape = tool.toRequest ? tool.toRequest(args || {}) : {};
  const routePath = requestShape.routePath || tool.route.path;

  return jurisRequest({
    method: tool.route.method,
    routePath,
    query: requestShape.query,
    body: requestShape.body,
    headers: requestShape.headers,
  });
}

const server = new Server(
  {
    name: "juris-search-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: describeTools() }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const name = request.params.name;
  const args = request.params.arguments || {};

  try {
    if (name === "juris_set_base_url") {
      jurisBaseUrl = normalizeBaseUrl(args.base_url);
      return jsonResult({ ok: true, base_url: jurisBaseUrl });
    }

    if (name === "juris_start_service") {
      const payload = await handleStartService(args);
      return jsonResult(payload);
    }

    if (name === "juris_stop_service") {
      const payload = await handleStopService();
      return jsonResult(payload);
    }

    // File-based tools
    const fileTool = fileToolMap.get(name);
    if (fileTool) {
      const payload = await fileTool.handler(args);
      return jsonResult(payload);
    }

    const payload = await executeEndpointTool(name, args);
    return jsonResult(payload);
  } catch (error) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          ok: false,
          error: error && error.message ? error.message : String(error),
          tool: name,
          base_url: jurisBaseUrl,
        }, null, 2),
      }],
      isError: true,
    };
  }
});

async function main() {
  const transportMode = (process.env.MCP_TRANSPORT || "stdio").trim().toLowerCase();
  if (transportMode === "stdio") {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    return;
  }
  if (transportMode === "streamable-http" || transportMode === "sse") {
    const host = process.env.MCP_HOST || "127.0.0.1";
    const port = parseInt(process.env.MCP_PORT || "8116", 10);
    const httpServer = http.createServer(async (req, res) => {
      if (req.url === "/health" && req.method === "GET") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "ok", service: "juris" }));
        return;
      }
      // Create a fresh transport per request (stateless, one-shot)
      const mcpTransport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      try {
        await server.connect(mcpTransport);
        await mcpTransport.handleRequest(req, res, undefined);
        await mcpTransport.close();
      } catch (e) {
        console.error("MCP transport error:", e.message);
        if (!res.headersSent) {
          res.writeHead(500);
          res.end("Internal error");
        }
        await mcpTransport.close().catch(() => {});
      }
    });
    httpServer.listen(port, host, () => {
      console.error(`Juris MCP server (${transportMode}) listening on http://${host}:${port}`);
    });
    return;
  }
  console.error("Unsupported MCP_TRANSPORT: " + transportMode + ". Use: stdio, sse, streamable-http");
  process.exit(1);
}

main().catch((error) => {
  console.error("Failed to start juris-search MCP server:", error);
  process.exit(1);
});
