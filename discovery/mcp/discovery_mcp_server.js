#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} = require("@modelcontextprotocol/sdk/types.js");

const DEFAULT_BASE_URL = process.env.DISCOVERY_BASE_URL || "http://127.0.0.1:3010";

let discoveryBaseUrl = normalizeBaseUrl(DEFAULT_BASE_URL);
let embeddedServerHandle = null;

function normalizeBaseUrl(url) {
  const trimmed = String(url || "").trim().replace(/\/+$/, "");
  if (!trimmed) {
    return "http://127.0.0.1:3010";
  }
  return trimmed;
}

function joinUrl(baseUrl, routePath, query) {
  const url = new URL(routePath, `${baseUrl}/`);
  if (query && typeof query === "object") {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
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

function findCommonDirectory(filePaths) {
  if (!Array.isArray(filePaths) || !filePaths.length) {
    return "";
  }

  const absoluteDirs = filePaths.map((filePath) => path.resolve(path.dirname(filePath)));
  const splitPath = (target) => path.resolve(target).split(path.sep).filter(Boolean);

  let commonParts = splitPath(absoluteDirs[0]);
  for (const dir of absoluteDirs.slice(1)) {
    const parts = splitPath(dir);
    let index = 0;
    while (index < commonParts.length && index < parts.length && commonParts[index] === parts[index]) {
      index += 1;
    }
    commonParts = commonParts.slice(0, index);
    if (!commonParts.length) {
      break;
    }
  }

  const root = path.parse(absoluteDirs[0]).root || path.sep;
  if (!commonParts.length) {
    return root;
  }

  return path.resolve(root, ...commonParts);
}

function inferRelativeUploadPaths(filePaths) {
  if (!Array.isArray(filePaths) || !filePaths.length) {
    return [];
  }

  if (filePaths.length === 1) {
    return [path.basename(filePaths[0])];
  }

  const commonDir = findCommonDirectory(filePaths);
  const commonRoot = path.parse(commonDir).root || path.sep;
  const hasUsableRoot = path.resolve(commonDir) !== path.resolve(commonRoot);

  if (!hasUsableRoot) {
    return filePaths.map((filePath) => path.basename(filePath));
  }

  return filePaths.map((filePath) => {
    const relative = path.relative(commonDir, filePath);
    if (!relative || relative.startsWith("..")) {
      return path.basename(filePath);
    }
    return toPosixPath(relative);
  });
}

async function parseResponseBody(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  if (contentType.startsWith("text/")) {
    return response.text();
  }
  const arrayBuffer = await response.arrayBuffer();
  return {
    content_type: contentType || "application/octet-stream",
    size_bytes: arrayBuffer.byteLength,
    content_base64: Buffer.from(arrayBuffer).toString("base64"),
  };
}

async function discoveryRequest({ method, routePath, query, body, headers }) {
  const url = joinUrl(discoveryBaseUrl, routePath, query);
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
      : (payload && payload.error) || JSON.stringify(payload);
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

function parseSseTranscript(rawText, maxEvents) {
  const transcript = String(rawText || "");
  const lines = transcript.split(/\r?\n/);
  const events = [];
  let currentEvent = "message";
  let dataLines = [];

  const flush = () => {
    if (!dataLines.length) {
      currentEvent = "message";
      return;
    }
    const rawData = dataLines.join("\n");
    let data = rawData;
    try {
      data = JSON.parse(rawData);
    } catch (_) {
      // Keep plain text payloads when event data is not JSON.
    }
    events.push({ event: currentEvent || "message", data });
    currentEvent = "message";
    dataLines = [];
  };

  for (const line of lines) {
    if (!line.trim()) {
      flush();
      continue;
    }
    if (line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      currentEvent = line.slice("event:".length).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  flush();

  const normalizedMaxEvents = Number.isFinite(Number(maxEvents))
    ? Math.max(1, Math.min(500, Number(maxEvents)))
    : 50;

  const tail = events.slice(-normalizedMaxEvents);
  const completion = [...events].reverse().find((item) => item.event === "complete") || null;
  const error = [...events].reverse().find((item) => item.event === "error") || null;

  return {
    total_events: events.length,
    progress_events: events.filter((item) => item.event === "progress").length,
    completed: Boolean(completion),
    errored: Boolean(error),
    completion: completion ? completion.data : null,
    error: error ? error.data : null,
    events_tail: tail,
  };
}

const endpointTools = [
  {
    name: "discovery_health",
    description: "Get Discovery server health state.",
    route: { method: "GET", path: "/health" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_manifest",
    description: "Get full Discovery manifest with metadata and endpoint catalog.",
    route: { method: "GET", path: "/api/manifest" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_endpoints",
    description: "List all generated file endpoints.",
    route: { method: "GET", path: "/api/endpoints" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_files",
    description: "List files with optional Discovery filters.",
    route: { method: "GET", path: "/api/files" },
    schema: {
      type: "object",
      properties: {
        category: { type: "string", description: "Category exact match." },
        ext: { type: "string", description: "Extension exact match, e.g. .json" },
        kind: { type: "string", description: "Partial kind match." },
        group: { type: "string", description: "Content group exact match." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_categories",
    description: "Get category summary with file counts.",
    route: { method: "GET", path: "/api/categories" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_search",
    description: "Search Discovery metadata by query string.",
    route: { method: "GET", path: "/api/search" },
    schema: {
      type: "object",
      properties: {
        q: { type: "string", description: "Search text." },
        limit: numSchema("Result limit (max 500).", 1, 500),
      },
      required: ["q"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_tree",
    description: "Get recursive file tree with endpoint linkage.",
    route: { method: "GET", path: "/api/tree" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_rebuild",
    description: "Rebuild Discovery index from a new root directory.",
    route: { method: "POST", path: "/api/rebuild" },
    schema: {
      type: "object",
      properties: {
        root_dir: { type: "string", description: "Absolute or relative directory path." },
      },
      required: ["root_dir"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_organize",
    description: "Alias to rebuild organization from a root directory.",
    route: { method: "POST", path: "/organize" },
    schema: {
      type: "object",
      properties: {
        root_dir: { type: "string", description: "Absolute or relative directory path." },
      },
      required: ["root_dir"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_init_session",
    description: "Initialize or create a user workspace session.",
    route: { method: "POST", path: "/api/discovery/init-session" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        reset_generated: boolSchema("Clear generated artifacts before rebuild.", false),
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_reset_session",
    description: "Reset session workspace and optionally remove uploaded files.",
    route: { method: "POST", path: "/api/discovery/reset-session" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        clear_files: boolSchema("If true, remove files from workspace.", false),
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_law_frameworks",
    description: "List legal frameworks proxied by Argus integration.",
    route: { method: "GET", path: "/api/law/frameworks" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_law_framework_articles",
    description: "Get articles for a law framework code.",
    route: { method: "GET", path: "/api/law/frameworks/{code}/articles" },
    schema: {
      type: "object",
      properties: {
        code: { type: "string", description: "Framework code." },
      },
      required: ["code"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/api/law/frameworks/${encodeURIComponent(args.code)}/articles`,
    }),
  },
  {
    name: "discovery_file_detail",
    description: "Get enriched detail for a file in Discovery index.",
    route: { method: "GET", path: "/api/file-detail" },
    schema: {
      type: "object",
      properties: {
        file: { type: "string", description: "Relative file path from Discovery root." },
      },
      required: ["file"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_pipeline_entities",
    description: "Get entity summaries or one entity type from pipeline output.",
    route: { method: "GET", path: "/api/pipeline/entities" },
    schema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          description: "Optional entity type (people, organizations, laws, locations, dates).",
        },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_pipeline_relationships",
    description: "List cross-file relationships with optional filters.",
    route: { method: "GET", path: "/api/pipeline/relationships" },
    schema: {
      type: "object",
      properties: {
        limit: numSchema("Max relationships (max 500).", 1, 500),
        min_strength: numSchema("Minimum relationship strength.", 1, 9999),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_pipeline_timeline",
    description: "Get pipeline timeline with optional date bounds.",
    route: { method: "GET", path: "/api/pipeline/timeline" },
    schema: {
      type: "object",
      properties: {
        from: { type: "string", description: "Lower date bound YYYY-MM-DD." },
        to: { type: "string", description: "Upper date bound YYYY-MM-DD." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_pipeline_stats",
    description: "Get aggregate pipeline statistics.",
    route: { method: "GET", path: "/api/pipeline/stats" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_pipeline_search",
    description: "Search enriched pipeline data.",
    route: { method: "GET", path: "/api/pipeline/search" },
    schema: {
      type: "object",
      properties: {
        q: { type: "string", description: "Search text." },
        limit: numSchema("Result limit (max 200).", 1, 200),
      },
      required: ["q"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_intelligence_status",
    description: "Check which intelligence artifacts are available.",
    route: { method: "GET", path: "/api/intelligence/status" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_run",
    description: "Run intelligence pipeline (L5-L7).",
    route: { method: "POST", path: "/api/intelligence/run" },
    schema: {
      type: "object",
      properties: {
        api_key: { type: "string", description: "Provider API key." },
        model: { type: "string", description: "Optional model override." },
        concurrency: numSchema("Worker concurrency.", 1, 16),
        skip_dedup: boolSchema("Skip dedup stage.", false),
        bulk_fast: boolSchema("Enable bulk fast mode.", false),
        use_cache: boolSchema("Use local cache.", true),
      },
      required: ["api_key"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_intelligence_summary",
    description: "Get generated intelligence summary.",
    route: { method: "GET", path: "/api/intelligence/summary" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_case_graph",
    description: "Get intelligence case graph.",
    route: { method: "GET", path: "/api/intelligence/case-graph" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_violations",
    description: "Get intelligence violations with optional filters.",
    route: { method: "GET", path: "/api/intelligence/violations" },
    schema: {
      type: "object",
      properties: {
        severity: { type: "string", description: "Filter by severity." },
        min_confidence: numSchema("Minimum confidence score.", 0, 1),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_intelligence_findings",
    description: "Get intelligence findings with optional filters.",
    route: { method: "GET", path: "/api/intelligence/findings" },
    schema: {
      type: "object",
      properties: {
        severity: { type: "string", description: "Filter by severity." },
        min_confidence: numSchema("Minimum confidence score.", 0, 1),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_intelligence_timeline",
    description: "Get intelligence timeline.",
    route: { method: "GET", path: "/api/intelligence/timeline" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_narrative",
    description: "Get intelligence narrative in JSON wrapper or raw markdown.",
    route: { method: "GET", path: "/api/intelligence/narrative" },
    schema: {
      type: "object",
      properties: {
        format: { type: "string", enum: ["md"], description: "Use md for raw markdown response." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_intelligence_gap_report",
    description: "Get intelligence gap report.",
    route: { method: "GET", path: "/api/intelligence/gap-report" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_law_registry",
    description: "Get law registry with optional filter flags.",
    route: { method: "GET", path: "/api/intelligence/law-registry" },
    schema: {
      type: "object",
      properties: {
        resolved: boolSchema("Filter resolved status."),
        needs_argus: boolSchema("Return only unresolved entries needing Argus.", false),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_intelligence_dedup_report",
    description: "Get dedup report or dedup summary stats.",
    route: { method: "GET", path: "/api/intelligence/dedup-report" },
    schema: {
      type: "object",
      properties: {
        summary: boolSchema("If true, only return dedup stats.", false),
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_events",
    description: "Get events data with optional type filter.",
    route: { method: "GET", path: "/api/events" },
    schema: {
      type: "object",
      properties: {
        type: { type: "string", description: "Filter event type." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_event_graph",
    description: "Get event graph with optional edge type filter.",
    route: { method: "GET", path: "/api/events/graph" },
    schema: {
      type: "object",
      properties: {
        edge_type: { type: "string", description: "Filter by edge type." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_case_state",
    description: "Get evaluated case state.",
    route: { method: "GET", path: "/api/case-state" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_case_phase",
    description: "Get case state current phase.",
    route: { method: "GET", path: "/api/case-state/phase" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_case_findings",
    description: "Get case findings with optional severity and type filters.",
    route: { method: "GET", path: "/api/case-state/findings" },
    schema: {
      type: "object",
      properties: {
        severity: { type: "string", description: "Filter by severity." },
        type: { type: "string", description: "Filter by finding type." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_case_next_steps",
    description: "Get recommended case next steps.",
    route: { method: "GET", path: "/api/case-state/next-steps" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_comprehend_run",
    description: "Run corpus comprehension analysis.",
    route: { method: "POST", path: "/api/comprehend/run" },
    schema: {
      type: "object",
      properties: {
        api_key: { type: "string", description: "Provider API key." },
        model: { type: "string", description: "Optional model override." },
        concurrency: numSchema("Worker concurrency.", 1, 16),
        max_samples: numSchema("Max samples per group.", 1, 100),
        max_groups: numSchema("Max groups to process.", 1, 200),
      },
      required: ["api_key"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ body: args }),
  },
  {
    name: "discovery_comprehend_overview",
    description: "Get corpus comprehension overview.",
    route: { method: "GET", path: "/api/comprehend/overview" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_comprehend_guide",
    description: "Get corpus guide in JSON wrapper or markdown.",
    route: { method: "GET", path: "/api/comprehend/guide" },
    schema: {
      type: "object",
      properties: {
        format: { type: "string", enum: ["md"], description: "Use md for raw markdown response." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_comprehend_groups",
    description: "Get group descriptions or one domain summary.",
    route: { method: "GET", path: "/api/comprehend/groups" },
    schema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Optional domain key to fetch only one group." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_comprehend_strategies",
    description: "Get generated restructure strategies.",
    route: { method: "GET", path: "/api/comprehend/strategies" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_export_session",
    description: "Export a full Discovery workspace session payload for one user id.",
    route: { method: "GET", path: "/api/discovery/export-session" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Discovery user/session id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({ query: args }),
  },
  {
    name: "discovery_import_session",
    description: "Import an exported workspace bundle JSON into a Discovery session.",
    route: { method: "POST", path: "/api/discovery/import-session" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Discovery user/session id." },
        bundle_file_path: { type: "string", description: "Path to an exported bundle JSON file." },
        overwrite_existing: boolSchema("Overwrite existing files in destination workspace.", true),
      },
      required: ["user_id", "bundle_file_path"],
      additionalProperties: false,
    },
    handler: "import_session",
    toRequest: () => ({}),
  },
  {
    name: "discovery_intelligence_run_stream",
    description: "Run intelligence stream endpoint and return a parsed SSE snapshot.",
    route: { method: "GET", path: "/api/intelligence/run-stream" },
    schema: {
      type: "object",
      properties: {
        api_key: { type: "string", description: "Provider API key." },
        model: { type: "string", description: "Optional model override." },
        concurrency: numSchema("Worker concurrency.", 1, 16),
        skip_dedup: boolSchema("Skip dedup stage.", false),
        bulk_fast: boolSchema("Enable bulk fast mode.", false),
        use_cache: boolSchema("Use local cache.", true),
        max_events: numSchema("Max SSE events included in events_tail.", 1, 500),
      },
      required: ["api_key"],
      additionalProperties: false,
    },
    handler: "sse_snapshot",
    toRequest: (args) => {
      const query = { ...(args || {}) };
      const stream_max_events = query.max_events;
      delete query.max_events;
      return { query, stream_max_events };
    },
  },
  {
    name: "discovery_comprehend_run_stream",
    description: "Run comprehension stream endpoint and return a parsed SSE snapshot.",
    route: { method: "GET", path: "/api/comprehend/run-stream" },
    schema: {
      type: "object",
      properties: {
        api_key: { type: "string", description: "Provider API key." },
        model: { type: "string", description: "Optional model override." },
        concurrency: numSchema("Worker concurrency.", 1, 16),
        max_samples: numSchema("Max samples per group.", 1, 100),
        max_groups: numSchema("Max groups to process.", 1, 200),
        max_events: numSchema("Max SSE events included in events_tail.", 1, 500),
      },
      required: ["api_key"],
      additionalProperties: false,
    },
    handler: "sse_snapshot",
    toRequest: (args) => {
      const query = { ...(args || {}) };
      const stream_max_events = query.max_events;
      delete query.max_events;
      return { query, stream_max_events };
    },
  },
  {
    name: "discovery_ui_server",
    description: "Fetch the Discovery server info page HTML.",
    route: { method: "GET", path: "/server" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_ui_home",
    description: "Fetch the Discovery root page HTML.",
    route: { method: "GET", path: "/" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_ui_agent_workspace",
    description: "Fetch the Discovery agent workspace page HTML.",
    route: { method: "GET", path: "/agent-workspace" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_ui_awareness_agent_workspace",
    description: "Fetch the legacy awareness agent workspace page HTML.",
    route: { method: "GET", path: "/awareness-agent-workspace" },
    schema: { type: "object", properties: {}, additionalProperties: false },
    toRequest: () => ({}),
  },
  {
    name: "discovery_assets_file",
    description: "Fetch a file served by the /assets static mount.",
    route: { method: "GET", path: "/assets" },
    schema: {
      type: "object",
      properties: {
        asset_path: { type: "string", description: "Relative file path under /assets." },
      },
      required: ["asset_path"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/assets/${encodeRouteSubpath(args.asset_path, "asset_path")}`,
    }),
  },
  {
    name: "discovery_static_file",
    description: "Fetch a file served by the /static static mount.",
    route: { method: "GET", path: "/static" },
    schema: {
      type: "object",
      properties: {
        static_path: { type: "string", description: "Relative file path under /static." },
      },
      required: ["static_path"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      routePath: `/static/${encodeRouteSubpath(args.static_path, "static_path")}`,
    }),
  },

  // ── Onboarding (P0–P6) ──────────────────────────────────────────
  {
    name: "discovery_onboarding_templates",
    description: "List intake templates available for onboarding (legal-case, blank, …).",
    route: { method: "GET", path: "/api/onboarding/templates" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id (X-Discovery-User-Id)." },
      },
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: args && args.user_id ? { "X-Discovery-User-Id": String(args.user_id) } : {},
    }),
  },
  {
    name: "discovery_onboarding_intake_get",
    description: "Get the saved intake spec for a session, if any.",
    route: { method: "GET", path: "/api/onboarding/intake" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
    }),
  },
  {
    name: "discovery_onboarding_intake_save",
    description: "Save the intake spec for a session. Generates the v1 blueprint as a side effect.",
    route: { method: "POST", path: "/api/onboarding/intake" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        intake_spec: {
          type: "object",
          description: "Intake spec object matching schemas/intake_spec.schema.json.",
        },
      },
      required: ["user_id", "intake_spec"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: { intake_spec: args.intake_spec },
    }),
  },
  {
    name: "discovery_onboarding_intake_agent_start",
    description: "Start (or resume) the conversational agent intake. The agent asks one question at a time and assembles an intake_spec from the replies. Pass reset=true to discard any in-flight session.",
    route: { method: "POST", path: "/api/onboarding/intake/agent/start" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        reset: boolSchema("If true, discard any in-flight agent session and start over.", false),
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: args.reset !== undefined ? { reset: !!args.reset } : {},
    }),
  },
  {
    name: "discovery_onboarding_intake_agent_state",
    description: "Get the current agent intake state (history, partial spec, pending question).",
    route: { method: "GET", path: "/api/onboarding/intake/agent" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
    }),
  },
  {
    name: "discovery_onboarding_intake_agent_reply",
    description: "Send a user reply to the agent intake. Returns the next question, or — when the dialogue completes and the user confirms — the saved intake_spec and generated blueprint v1.",
    route: { method: "POST", path: "/api/onboarding/intake/agent/reply" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        reply: { type: "string", description: "User reply text." },
      },
      required: ["user_id", "reply"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: { reply: String(args.reply == null ? "" : args.reply) },
    }),
  },
  {
    name: "discovery_onboarding_intake_agent_cancel",
    description: "Discard the in-flight agent intake session for a user.",
    route: { method: "POST", path: "/api/onboarding/intake/agent/cancel" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {},
    }),
  },
  {
    name: "discovery_onboarding_blueprint_get",
    description: "Fetch the blueprint for a session. version is 'v1' (default) or 'v2'.",
    route: { method: "GET", path: "/api/onboarding/blueprint" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        version: { type: "string", enum: ["v1", "v2"], description: "Blueprint version." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      query: args.version ? { version: args.version } : {},
    }),
  },
  {
    name: "discovery_onboarding_blueprint_materialize",
    description: "Materialize the blueprint (create directories and skeleton READMEs) inside the session workspace.",
    route: { method: "POST", path: "/api/onboarding/blueprint/materialize" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        version: { type: "string", enum: ["v1", "v2"], description: "Blueprint version (default v1)." },
        collision_policy: {
          type: "string",
          enum: ["merge", "overwrite", "rename_existing", "abort"],
          description: "Collision policy for existing dirs/READMEs (default merge).",
        },
        dry_run: boolSchema("If true, plan without creating directories.", false),
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {
        ...(args.version ? { version: args.version } : {}),
        ...(args.collision_policy ? { collision_policy: args.collision_policy } : {}),
        ...(args.dry_run !== undefined ? { dry_run: !!args.dry_run } : {}),
      },
    }),
  },
  {
    name: "discovery_onboarding_refine",
    description: "Refine v1 blueprint into v2 using the current corpus signals (file paths, kinds, keywords).",
    route: { method: "POST", path: "/api/onboarding/refine" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {},
    }),
  },
  {
    name: "discovery_onboarding_plan_get",
    description: "Get the saved pipeline plan for a session.",
    route: { method: "GET", path: "/api/onboarding/plan" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
    }),
  },
  {
    name: "discovery_onboarding_plan_save",
    description: "Build and save a pipeline plan from an edited blueprint, destination root, per-directory layer choices, and pilot strategies.",
    route: { method: "POST", path: "/api/onboarding/plan" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        blueprint: {
          type: "object",
          description: "Edited blueprint (typically v2 with optional renames/deletes). Must contain a 'nodes' array.",
        },
        destination_root: {
          type: "string",
          description: "Absolute filesystem path where the committed structure will live.",
        },
        destination_collision_policy: {
          type: "string",
          enum: ["merge", "overwrite", "rename_existing", "abort"],
          description: "Policy applied during full-run when destination already has files (default abort).",
        },
        main_directories: {
          type: "array",
          description: "Per-main-directory layer + pilot configuration. See pipeline_plan.schema.json.",
          items: { type: "object" },
        },
        global_options: {
          type: "object",
          description: "Run-wide options: llm_provider, max_concurrency, halt_on_error, dry_run, cost_ceiling_usd.",
        },
      },
      required: ["user_id", "blueprint", "destination_root", "main_directories"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {
        blueprint: args.blueprint,
        destination_root: args.destination_root,
        ...(args.destination_collision_policy
          ? { destination_collision_policy: args.destination_collision_policy }
          : {}),
        main_directories: args.main_directories,
        ...(args.global_options ? { global_options: args.global_options } : {}),
      },
    }),
  },
  {
    name: "discovery_onboarding_pilot_get",
    description: "Get the most recent pilot report for a session.",
    route: { method: "GET", path: "/api/onboarding/pilot-run" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
    }),
  },
  {
    name: "discovery_onboarding_pilot_run",
    description: "Run the pilot pass: pick samples per main directory using the saved plan strategies and produce a coverage report.",
    route: { method: "POST", path: "/api/onboarding/pilot-run" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {},
    }),
  },
  {
    name: "discovery_onboarding_full_run_get",
    description: "Get the most recent full-run manifest for a session.",
    route: { method: "GET", path: "/api/onboarding/full-run" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
    }),
  },
  {
    name: "discovery_onboarding_full_run",
    description: "Execute the full structural commit: materialize the v2 blueprint at destination_root and copy every workspace file into its target node, applying guardrail renames and dropping orphans into UNCLASSIFIED/loose. The session workspace is preserved as a snapshot. Use dry_run=true to preview the manifest without writing.",
    route: { method: "POST", path: "/api/onboarding/full-run" },
    schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Session user id." },
        dry_run: boolSchema("If true, compute manifest without copying or creating directories.", false),
        destination_root: {
          type: "string",
          description: "Override destination root (otherwise read from saved plan).",
        },
      },
      required: ["user_id"],
      additionalProperties: false,
    },
    toRequest: (args) => ({
      headers: { "X-Discovery-User-Id": String(args.user_id) },
      body: {
        ...(args.dry_run !== undefined ? { dry_run: !!args.dry_run } : {}),
        ...(args.destination_root ? { destination_root: args.destination_root } : {}),
      },
    }),
  },
];

const endpointToolMap = new Map(endpointTools.map((tool) => [tool.name, tool]));

function describeTools() {
  const shared = [
    {
      name: "discovery_set_base_url",
      description: "Set target Discovery base URL for all HTTP-backed tools.",
      inputSchema: {
        type: "object",
        properties: {
          base_url: { type: "string", description: "Example: http://127.0.0.1:3010" },
        },
        required: ["base_url"],
        additionalProperties: false,
      },
    },
    {
      name: "discovery_start_service",
      description: "Start an embedded Discovery service from this repository process.",
      inputSchema: {
        type: "object",
        properties: {
          port: numSchema("Port for embedded service.", 1, 65535),
          root_dir: { type: "string", description: "Optional root directory to rebuild after start." },
        },
        additionalProperties: false,
      },
    },
    {
      name: "discovery_stop_service",
      description: "Stop embedded Discovery service started by this MCP server.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
    },
    {
      name: "discovery_raw_file",
      description: "Fetch file bytes from /api/raw and return base64 payload.",
      inputSchema: {
        type: "object",
        properties: {
          file: { type: "string", description: "Relative file path from Discovery root." },
          max_bytes: numSchema("Optional max byte limit; if exceeded payload is truncated.", 1),
        },
        required: ["file"],
        additionalProperties: false,
      },
    },
    {
      name: "discovery_upload_files",
      description: "Upload one or more local files into a Discovery user session workspace.",
      inputSchema: {
        type: "object",
        properties: {
          user_id: { type: "string", description: "Discovery user/session id (sent as X-Discovery-User-Id)." },
          file_paths: {
            type: "array",
            description: "Absolute or workspace-relative local file paths.",
            items: { type: "string" },
            minItems: 1,
          },
          relative_paths: {
            type: "array",
            description: "Optional upload-relative filenames matching file_paths length. If omitted, hierarchy is inferred from a common parent directory when possible.",
            items: { type: "string" },
          },
        },
        required: ["user_id", "file_paths"],
        additionalProperties: false,
      },
    },
  ];

  const generated = endpointTools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.schema,
  }));

  return [...shared, ...generated];
}

async function handleStartService(args) {
  if (embeddedServerHandle) {
    return {
      ok: true,
      message: "Embedded Discovery service is already running.",
      port: embeddedServerHandle.port,
      base_url: discoveryBaseUrl,
    };
  }

  const { startDiscoveryServer } = require("../case-server/auto_server_builder.js");
  const options = {};
  if (args && args.port) {
    options.port = Number(args.port);
  }

  embeddedServerHandle = await startDiscoveryServer(options);
  discoveryBaseUrl = normalizeBaseUrl(`http://127.0.0.1:${embeddedServerHandle.port}`);

  if (args && args.root_dir) {
    await discoveryRequest({
      method: "POST",
      routePath: "/api/rebuild",
      body: { root_dir: args.root_dir },
    });
  }

  return {
    ok: true,
    started: true,
    port: embeddedServerHandle.port,
    base_url: discoveryBaseUrl,
  };
}

async function handleStopService() {
  if (!embeddedServerHandle) {
    return {
      ok: true,
      stopped: false,
      message: "No embedded Discovery service was started by this MCP process.",
      base_url: discoveryBaseUrl,
    };
  }

  await new Promise((resolve, reject) => {
    embeddedServerHandle.server.close((err) => {
      if (err) return reject(err);
      resolve();
    });
  });

  const previousPort = embeddedServerHandle.port;
  embeddedServerHandle = null;

  return {
    ok: true,
    stopped: true,
    previous_port: previousPort,
    base_url: discoveryBaseUrl,
  };
}

async function handleRawFile(args) {
  const file = args.file;
  const maxBytes = Number.isFinite(Number(args.max_bytes)) ? Number(args.max_bytes) : null;
  const url = joinUrl(discoveryBaseUrl, "/api/raw", { file });

  const response = await fetch(url, { method: "GET" });
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const buffer = Buffer.from(await response.arrayBuffer());

  if (!response.ok) {
    let detail = buffer.toString("utf8");
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.error || detail;
    } catch (_) {
      // keep text detail
    }
    throw new Error(`GET /api/raw failed (${response.status}): ${detail}`);
  }

  const truncated = maxBytes && buffer.length > maxBytes;
  const payload = truncated ? buffer.subarray(0, maxBytes) : buffer;

  return {
    file,
    content_type: contentType,
    size_bytes: buffer.length,
    returned_bytes: payload.length,
    truncated: Boolean(truncated),
    content_base64: payload.toString("base64"),
  };
}

async function handleUploadFiles(args) {
  const { user_id: userId, file_paths: filePaths, relative_paths: relativePaths } = args;

  if (relativePaths && relativePaths.length !== filePaths.length) {
    throw new Error("relative_paths length must match file_paths length");
  }

  const form = new FormData();
  const resolvedFilePaths = [];

  for (let i = 0; i < filePaths.length; i += 1) {
    const filePathRaw = filePaths[i];
    const resolvedPath = path.resolve(filePathRaw);
    if (!fs.existsSync(resolvedPath)) {
      throw new Error(`File not found: ${resolvedPath}`);
    }

    const stat = fs.statSync(resolvedPath);
    if (!stat.isFile()) {
      throw new Error(`Not a file: ${resolvedPath}`);
    }

    resolvedFilePaths.push(resolvedPath);
  }

  const uploadRelativePaths = relativePaths
    ? relativePaths.map((relativePath) => String(relativePath))
    : inferRelativeUploadPaths(resolvedFilePaths);

  for (let i = 0; i < resolvedFilePaths.length; i += 1) {
    const resolvedPath = resolvedFilePaths[i];

    const uploadName = uploadRelativePaths[i] || path.basename(resolvedPath);

    const bytes = fs.readFileSync(resolvedPath);
    const blob = new Blob([bytes]);
    form.append("files", blob, uploadName);
  }

  const url = joinUrl(discoveryBaseUrl, "/api/discovery/upload");
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "X-Discovery-User-Id": String(userId),
    },
    body: form,
  });

  const payload = await parseResponseBody(response);
  if (!response.ok) {
    const errorMessage = typeof payload === "string"
      ? payload
      : (payload && payload.error) || JSON.stringify(payload);
    throw new Error(`POST /api/discovery/upload failed (${response.status}): ${errorMessage}`);
  }

  return payload;
}

async function handleImportSession(args) {
  const userId = String(args.user_id || "").trim();
  const bundleFilePathRaw = String(args.bundle_file_path || "").trim();

  if (!userId) {
    throw new Error("user_id is required");
  }
  if (!bundleFilePathRaw) {
    throw new Error("bundle_file_path is required");
  }

  const bundleFilePath = path.resolve(bundleFilePathRaw);
  if (!fs.existsSync(bundleFilePath)) {
    throw new Error(`File not found: ${bundleFilePath}`);
  }
  if (!fs.statSync(bundleFilePath).isFile()) {
    throw new Error(`Not a file: ${bundleFilePath}`);
  }

  const form = new FormData();
  const bytes = fs.readFileSync(bundleFilePath);
  const bundleBlob = new Blob([bytes], { type: "application/json" });
  form.append("bundle", bundleBlob, path.basename(bundleFilePath));
  form.append("user_id", userId);

  if (args.overwrite_existing !== undefined) {
    form.append("overwrite_existing", String(Boolean(args.overwrite_existing)));
  }

  const url = joinUrl(discoveryBaseUrl, "/api/discovery/import-session");
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "X-Discovery-User-Id": userId,
    },
    body: form,
  });

  const payload = await parseResponseBody(response);
  if (!response.ok) {
    const errorMessage = typeof payload === "string"
      ? payload
      : (payload && payload.error) || JSON.stringify(payload);
    throw new Error(`POST /api/discovery/import-session failed (${response.status}): ${errorMessage}`);
  }

  return payload;
}

async function handleSseSnapshot(routePath, query, maxEvents) {
  const url = joinUrl(discoveryBaseUrl, routePath, query);
  const response = await fetch(url, { method: "GET" });
  const rawText = await response.text();

  if (!response.ok) {
    let errorMessage = rawText;
    try {
      const parsed = JSON.parse(rawText);
      errorMessage = parsed.error || rawText;
    } catch (_) {
      // Keep raw text detail when not JSON.
    }
    throw new Error(`GET ${routePath} failed (${response.status}): ${errorMessage}`);
  }

  return {
    route_path: routePath,
    content_type: response.headers.get("content-type") || "text/event-stream",
    ...parseSseTranscript(rawText, maxEvents),
  };
}

async function executeEndpointTool(name, args) {
  const tool = endpointToolMap.get(name);
  if (!tool) {
    throw new Error(`Unknown endpoint tool: ${name}`);
  }

  const requestShape = tool.toRequest ? tool.toRequest(args || {}) : {};
  const routePath = requestShape.routePath || tool.route.path;

  if (tool.handler === "import_session") {
    return handleImportSession(args || {});
  }

  if (tool.handler === "sse_snapshot") {
    return handleSseSnapshot(routePath, requestShape.query || {}, requestShape.stream_max_events);
  }

  return discoveryRequest({
    method: tool.route.method,
    routePath,
    query: requestShape.query,
    body: requestShape.body,
    headers: requestShape.headers,
  });
}

const server = new Server(
  {
    name: "discovery-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: describeTools() };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const name = request.params.name;
  const args = request.params.arguments || {};

  try {
    if (name === "discovery_set_base_url") {
      discoveryBaseUrl = normalizeBaseUrl(args.base_url);
      return jsonResult({ ok: true, base_url: discoveryBaseUrl });
    }

    if (name === "discovery_start_service") {
      const payload = await handleStartService(args);
      return jsonResult(payload);
    }

    if (name === "discovery_stop_service") {
      const payload = await handleStopService();
      return jsonResult(payload);
    }

    if (name === "discovery_raw_file") {
      const payload = await handleRawFile(args);
      return jsonResult(payload);
    }

    if (name === "discovery_upload_files") {
      const payload = await handleUploadFiles(args);
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
          base_url: discoveryBaseUrl,
        }, null, 2),
      }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("Failed to start Discovery MCP server:", error);
  process.exit(1);
});
