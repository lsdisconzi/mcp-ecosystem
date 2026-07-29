# MCP Architecture — discovery

This file summarises the patterns used in `discovery_mcp_server.js`. The full authoritative standard lives at:

```
garage-main/mcp/MCP_ARCHITECTURE.md
```

---

## Quick reference

### Tool entry shape

```js
{
  name: "discovery_{action}",             // snake_case, discovery_ prefix always
  description: "One-line description.",
  route: { method: "GET|POST|...", path: "/api/route" },
  schema: {
    type: "object",
    properties: {
      param: { type: "string", description: "..." },
      flag:  boolSchema("Description.", false),
      count: numSchema("Description.", 1, 500),
    },
    required: ["param"],                  // list only truly required params
    additionalProperties: false,
  },
  toRequest: (args) => ({ query: args }), // GET → query params
  // toRequest: (args) => ({ body: args }),  POST/PUT → request body
  // toRequest: (args) => ({ routePath: `/api/path/${encodeURIComponent(args.id)}` }),
},
```

### Error handling

Errors are caught centrally in the `CallToolRequestSchema` handler. Individual `toRequest` functions may `throw new Error("message")` for validation failures (including unconfirmed destructive ops).

### Destructive guard

```js
toRequest: (args) => {
  if (!args.confirm) throw new Error("Set confirm=true to delete.");
  return { routePath: `/api/resource/${encodeURIComponent(args.id)}`, method: "DELETE" };
},
```

### Config

```
DISCOVERY_BASE_URL   default: http://127.0.0.1:3010
```

---

## Coverage tracking

```bash
# Regenerate mcp_readiness_report.md
node mcp/generate_readiness_artifacts.js

# Syntax check
node --check mcp/discovery_mcp_server.js
```

Target: 100% of in-scope (`/api/*`, `/health`, stream) endpoints mapped.

---

## Adding a tool

1. Add entry to `endpointTools` array in `discovery_mcp_server.js`
2. `node --check mcp/discovery_mcp_server.js`
3. `node mcp/generate_readiness_artifacts.js` → confirm 0 missing
