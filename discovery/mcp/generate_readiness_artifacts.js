#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const serverFile = path.join(repoRoot, "case-server", "auto_server_builder.js");
const mcpFile = path.join(repoRoot, "mcp", "discovery_mcp_server.js");
const inventoryFile = path.join(repoRoot, "endpoints_inventory.json");
const readinessReportFile = path.join(repoRoot, "mcp", "mcp_readiness_report.md");

function normalizePath(routePath) {
  return String(routePath || "")
    .replace(/:[A-Za-z0-9_]+/g, "{param}")
    .replace(/\{[A-Za-z0-9_]+\}/g, "{param}")
    .replace(/\/+/g, "/");
}

function classifyEndpoint(endpoint) {
  const loweredPath = endpoint.path.toLowerCase();

  if (endpoint.path === "/health") return "health";
  if (loweredPath.includes("run-stream")) return "stream";

  if (endpoint.path.startsWith("/api/")) {
    if (loweredPath.includes("/upload") || loweredPath.includes("/import-session")) {
      return "upload";
    }
    return "api";
  }

  if (
    endpoint.method === "USE" ||
    loweredPath.startsWith("/assets") ||
    loweredPath.startsWith("/static") ||
    loweredPath === "/" ||
    loweredPath.startsWith("/agent-") ||
    loweredPath.includes("workspace") ||
    loweredPath.startsWith("/server") ||
    loweredPath.startsWith("/data")
  ) {
    return "ui-static";
  }

  return "utility";
}

function parseServerEndpoints(sourceCode) {
  const endpoints = [];
  const seen = new Set();

  const directRoutePattern = /app\.(get|post|put|delete|patch)\(\s*(["'])(.*?)\2/g;
  for (const match of sourceCode.matchAll(directRoutePattern)) {
    const method = match[1].toUpperCase();
    const endpointPath = match[3];
    const key = `${method} ${endpointPath}`;
    if (seen.has(key)) continue;
    seen.add(key);
    endpoints.push({ method, path: endpointPath });
  }

  const arrayRoutePattern = /app\.(get|post|put|delete|patch)\(\s*\[(.*?)\]/gs;
  for (const match of sourceCode.matchAll(arrayRoutePattern)) {
    const method = match[1].toUpperCase();
    const arrayBody = match[2];
    for (const pathMatch of arrayBody.matchAll(/["']([^"']+)["']/g)) {
      const endpointPath = pathMatch[1];
      const key = `${method} ${endpointPath}`;
      if (seen.has(key)) continue;
      seen.add(key);
      endpoints.push({ method, path: endpointPath });
    }
  }

  const staticMountPattern = /app\.use\(\s*(["'])(.*?)\1\s*,/g;
  for (const match of sourceCode.matchAll(staticMountPattern)) {
    const endpointPath = match[2];
    const key = `USE ${endpointPath}`;
    if (seen.has(key)) continue;
    seen.add(key);
    endpoints.push({ method: "USE", path: endpointPath });
  }

  return endpoints.map((endpoint) => ({
    ...endpoint,
    normalized_path: normalizePath(endpoint.path),
    classification: classifyEndpoint(endpoint),
  }));
}

function parseMcpRouteTools(sourceCode) {
  const mappings = [];
  const seen = new Set();

  const toolRoutePattern = /\{\s*name:\s*"([^"]+)"[\s\S]*?route:\s*\{\s*method:\s*"([A-Z]+)"\s*,\s*path:\s*"([^"]+)"\s*\}[\s\S]*?schema:\s*\{/g;
  for (const match of sourceCode.matchAll(toolRoutePattern)) {
    const toolName = match[1];
    const method = match[2];
    const endpointPath = match[3];
    const key = `${method} ${endpointPath}`;
    if (seen.has(key)) continue;
    seen.add(key);
    mappings.push({
      tool_name: toolName,
      method,
      path: endpointPath,
      normalized_path: normalizePath(endpointPath),
      mapping_type: "direct",
    });
  }

  const hasTool = (toolName) => sourceCode.includes(`name: "${toolName}"`);
  if (hasTool("discovery_raw_file")) {
    mappings.push({
      tool_name: "discovery_raw_file",
      method: "GET",
      path: "/api/raw",
      normalized_path: normalizePath("/api/raw"),
      mapping_type: "custom-handler",
    });
  }

  if (hasTool("discovery_upload_files")) {
    mappings.push({
      tool_name: "discovery_upload_files",
      method: "POST",
      path: "/api/discovery/upload",
      normalized_path: normalizePath("/api/discovery/upload"),
      mapping_type: "custom-handler",
    });
  }

  if (hasTool("discovery_assets_file")) {
    mappings.push({
      tool_name: "discovery_assets_file",
      method: "USE",
      path: "/assets",
      normalized_path: normalizePath("/assets"),
      mapping_type: "mount-wrapper",
    });
  }

  if (hasTool("discovery_static_file")) {
    mappings.push({
      tool_name: "discovery_static_file",
      method: "USE",
      path: "/static",
      normalized_path: normalizePath("/static"),
      mapping_type: "mount-wrapper",
    });
  }

  return mappings;
}

function isInScope(endpoint) {
  return (
    endpoint.path.startsWith("/api/") ||
    endpoint.path === "/health" ||
    endpoint.classification === "stream" ||
    endpoint.classification === "ui-static"
  );
}

function countByClassification(endpoints) {
  const counts = {};
  for (const endpoint of endpoints) {
    counts[endpoint.classification] = (counts[endpoint.classification] || 0) + 1;
  }
  return counts;
}

function findMapping(endpoint, mappings) {
  return mappings.find((mapping) => (
    mapping.method === endpoint.method &&
    mapping.normalized_path === endpoint.normalized_path
  ));
}

function run() {
  const serverSource = fs.readFileSync(serverFile, "utf8");
  const mcpSource = fs.readFileSync(mcpFile, "utf8");

  const discoveredEndpoints = parseServerEndpoints(serverSource);
  const mcpMappings = parseMcpRouteTools(mcpSource);

  const inScopeEndpoints = discoveredEndpoints.filter(isInScope);
  const excludedEndpoints = discoveredEndpoints.filter((endpoint) => !isInScope(endpoint));

  const inventoryEntries = discoveredEndpoints.map((endpoint) => {
    const mapping = findMapping(endpoint, mcpMappings);
    const inScope = isInScope(endpoint);
    return {
      method: endpoint.method,
      path: endpoint.path,
      classification: endpoint.classification,
      in_scope: inScope,
      mapped: Boolean(mapping),
      mapped_tool: mapping ? mapping.tool_name : null,
      mapping_type: mapping ? mapping.mapping_type : null,
    };
  });

  const mappedInScope = inventoryEntries.filter((entry) => entry.in_scope && entry.mapped);
  const missingInScope = inventoryEntries.filter((entry) => entry.in_scope && !entry.mapped);

  const staleMappings = mcpMappings.filter((mapping) => {
    const directMatch = discoveredEndpoints.some((endpoint) => (
      endpoint.method === mapping.method &&
      endpoint.normalized_path === mapping.normalized_path
    ));
    if (directMatch) {
      return false;
    }

    // Treat static mount wrappers as covered when /assets or /static exists as app.use.
    if ((mapping.path === "/assets" || mapping.path === "/static") && mapping.method === "GET") {
      return !discoveredEndpoints.some((endpoint) => (
        endpoint.method === "USE" && endpoint.normalized_path === mapping.normalized_path
      ));
    }

    return true;
  });

  fs.writeFileSync(inventoryFile, `${JSON.stringify(inventoryEntries, null, 2)}\n`);

  const readinessStatus = missingInScope.length === 0 ? "ready" : "not-ready";
  const coverage = inScopeEndpoints.length
    ? ((mappedInScope.length / inScopeEndpoints.length) * 100).toFixed(1)
    : "100.0";

  const reportLines = [
    "# MCP Readiness Report",
    "",
    `Generated at: ${new Date().toISOString()}`,
    "",
    "## Status",
    `- Readiness: ${readinessStatus}`,
    `- Coverage: ${mappedInScope.length}/${inScopeEndpoints.length} (${coverage}%)`,
    "",
    "## Totals",
    `- Discovered endpoints: ${discoveredEndpoints.length}`,
    `- In-scope endpoints: ${inScopeEndpoints.length}`,
    `- Mapped endpoints: ${mappedInScope.length}`,
    `- Missing endpoints: ${missingInScope.length}`,
    `- Excluded endpoints: ${excludedEndpoints.length}`,
    `- Stale MCP mappings: ${staleMappings.length}`,
    "",
    "## Discovered By Classification",
    ...Object.entries(countByClassification(discoveredEndpoints))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([classification, total]) => `- ${classification}: ${total}`),
    "",
    "## Missing In-Scope Endpoints",
  ];

  if (!missingInScope.length) {
    reportLines.push("- None");
  } else {
    for (const item of missingInScope) {
      reportLines.push(`- ${item.method} ${item.path} (${item.classification})`);
    }
  }

  reportLines.push("", "## Stale MCP Mappings");
  if (!staleMappings.length) {
    reportLines.push("- None");
  } else {
    for (const item of staleMappings) {
      reportLines.push(`- ${item.method} ${item.path} -> ${item.tool_name}`);
    }
  }

  reportLines.push("", "## Excluded Endpoints");
  if (!excludedEndpoints.length) {
    reportLines.push("- None");
  } else {
    for (const item of excludedEndpoints) {
      reportLines.push(`- ${item.method} ${item.path} (${item.classification})`);
    }
  }

  fs.writeFileSync(readinessReportFile, `${reportLines.join("\n")}\n`);

  const summary = {
    readiness: readinessStatus,
    discovered_total: discoveredEndpoints.length,
    in_scope_total: inScopeEndpoints.length,
    mapped_total: mappedInScope.length,
    missing_total: missingInScope.length,
    excluded_total: excludedEndpoints.length,
    stale_total: staleMappings.length,
    coverage_percent: Number(coverage),
  };

  console.log(JSON.stringify(summary, null, 2));
}

run();
