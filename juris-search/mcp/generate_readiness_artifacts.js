#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");

const sourceFiles = [
  path.join(repoRoot, "main.py"),
  path.join(repoRoot, "api.py"),
  path.join(repoRoot, "modules"),
];

const mcpFile = path.join(repoRoot, "mcp", "juris_mcp_server.js");
const inventoryFile = path.join(repoRoot, "endpoints_inventory.json");
const readinessReportFile = path.join(repoRoot, "mcp", "mcp_readiness_report.md");


function normalizePath(routePath) {
  return String(routePath || "")
    .replace(/:[A-Za-z0-9_]+/g, "{param}")
    .replace(/\{[A-Za-z0-9_]+\}/g, "{param}")
    .replace(/\/+$/g, "")
    .replace(/\/+/g, "/") || "/";
}


function readPythonSources(target) {
  const files = [];

  function walk(current) {
    if (!fs.existsSync(current)) return;

    const stat = fs.statSync(current);

    if (stat.isFile() && current.endsWith(".py")) {
      files.push(current);
      return;
    }

    if (stat.isDirectory()) {
      for (const item of fs.readdirSync(current)) {
        walk(path.join(current, item));
      }
    }
  }

  if (Array.isArray(target)) {
    target.forEach(walk);
  } else {
    walk(target);
  }

  return files
    .map(file => fs.readFileSync(file, "utf8"))
    .join("\n\n");
}


function classifyEndpoint(endpoint) {
  const loweredPath = endpoint.path.toLowerCase();

  if (
    endpoint.path === "/health" ||
    endpoint.path === "/api/health"
  ) {
    return "health";
  }

  if (endpoint.path.startsWith("/api/")) {
    if (loweredPath.includes("/upload")) return "upload";
    return "api";
  }

  if (
    endpoint.method === "MOUNT" ||
    loweredPath === "/" ||
    loweredPath.startsWith("/juris") ||
    loweredPath.startsWith("/tj") ||
    loweredPath.includes("favicon") ||
    loweredPath.includes("icons") ||
    loweredPath.startsWith("/assets")
  ) {
    return "ui-static";
  }

  return "utility";
}


function parseServerEndpoints(sourceCode) {
  const endpoints = [];
  const seen = new Set();


  const routePattern =
    /@(app|router)\.(get|post|put|delete|patch)\(\s*(["'])(.*?)\3/g;


  for (const match of sourceCode.matchAll(routePattern)) {

    const method = match[2].toUpperCase();
    const endpointPath = match[4];

    const key = `${method} ${endpointPath}`;

    if (seen.has(key)) continue;

    seen.add(key);

    endpoints.push({
      method,
      path: endpointPath,
    });
  }


  const mountPattern =
    /app\.mount\(\s*(["'])(.*?)\1\s*,/g;


  for (const match of sourceCode.matchAll(mountPattern)) {

    const endpointPath = match[2];

    const key = `MOUNT ${endpointPath}`;

    if (seen.has(key)) continue;

    seen.add(key);

    endpoints.push({
      method: "MOUNT",
      path: endpointPath,
    });
  }


  return endpoints.map(endpoint => ({
    ...endpoint,
    normalized_path: normalizePath(endpoint.path),
    classification: classifyEndpoint(endpoint),
  }));
}



function parseMcpRouteTools(sourceCode) {

  const mappings = [];

  const pattern =
    /\{\s*name:\s*"([^"]+)"[\s\S]*?route:\s*\{\s*method:\s*"([A-Z]+)"\s*,\s*path:\s*"([^"]+)"\s*\}/g;


  for (const match of sourceCode.matchAll(pattern)) {

    mappings.push({

      tool_name: match[1],

      method: match[2],

      path: match[3],

      normalized_path:
        normalizePath(match[3]),

      mapping_type:
        "direct",

    });
  }


  return mappings;
}



function isInScope(endpoint) {

  return (
    endpoint.path.startsWith("/api/") ||
    endpoint.path === "/health" ||
    endpoint.classification === "ui-static"
  );

}



function findMapping(endpoint, mappings) {

  return mappings.find(mapping =>
    mapping.method === endpoint.method &&
    mapping.normalized_path === endpoint.normalized_path
  );

}



function run() {


  const serverSource =
    readPythonSources(sourceFiles);


  const mcpSource =
    fs.readFileSync(mcpFile, "utf8");


  const discoveredEndpoints =
    parseServerEndpoints(serverSource);


  const mcpMappings =
    parseMcpRouteTools(mcpSource);



  const inventoryEntries =
    discoveredEndpoints.map(endpoint => {

      const mapping =
        findMapping(endpoint, mcpMappings);

      return {

        method: endpoint.method,

        path: endpoint.path,

        classification:
          endpoint.classification,

        in_scope:
          isInScope(endpoint),

        mapped:
          Boolean(mapping),

        mapped_tool:
          mapping?.tool_name || null,

        mapping_type:
          mapping?.mapping_type || null,

      };

    });



  const inScopeEndpoints =
    discoveredEndpoints.filter(isInScope);


  const mappedInScope =
    inventoryEntries.filter(
      e => e.in_scope && e.mapped
    );


  const missingInScope =
    inventoryEntries.filter(
      e => e.in_scope && !e.mapped
    );



  const staleMappings =
    mcpMappings.filter(mapping => {

      return !discoveredEndpoints.some(endpoint =>
        endpoint.method === mapping.method &&
        endpoint.normalized_path === mapping.normalized_path
      );

    });



  fs.writeFileSync(
    inventoryFile,
    JSON.stringify(
      inventoryEntries,
      null,
      2
    ) + "\n"
  );



  const coverage =
    inScopeEndpoints.length
      ? (
        mappedInScope.length /
        inScopeEndpoints.length *
        100
      ).toFixed(1)
      : "100.0";



  const report = [

    "# MCP Readiness Report",

    "",

    `Generated: ${new Date().toISOString()}`,

    "",

    `- Discovered endpoints: ${discoveredEndpoints.length}`,

    `- In scope endpoints: ${inScopeEndpoints.length}`,

    `- Mapped endpoints: ${mappedInScope.length}`,

    `- Missing endpoints: ${missingInScope.length}`,

    `- Stale MCP mappings: ${staleMappings.length}`,

    `- Coverage: ${coverage}%`,

  ].join("\n");



  fs.writeFileSync(
    readinessReportFile,
    report + "\n"
  );



  console.log(JSON.stringify({

    readiness:
      missingInScope.length === 0
        ? "ready"
        : "not-ready",

    discovered_total:
      discoveredEndpoints.length,

    in_scope_total:
      inScopeEndpoints.length,

    mapped_total:
      mappedInScope.length,

    missing_total:
      missingInScope.length,

    stale_total:
      staleMappings.length,

    coverage_percent:
      Number(coverage),

  }, null, 2));

}


run();