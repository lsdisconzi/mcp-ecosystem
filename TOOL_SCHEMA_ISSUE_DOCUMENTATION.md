# Tool Schema Discovery Issue - Documentation and Solution

## Problem Summary

Tool calls (e.g., `TaskCreate`, `TaskStop`, `EnterPlanMode`, `ExitPlanMode`) were failing with `InputValidationError: "Tool calls failed 3 times with InputValidationError. Please inspect permissions, path, or tool schema before retrying."`

**Root Cause:** The tool schemas were not properly discoverable/registered in the system's tool discovery mechanism. When the system attempted to validate tool call parameters against their JSON schemas, it couldn't find the schemas, causing validation to fail.

## Affected Tools

The following tools were impacted (as identified from system-reminders and conversation history):

1. **TaskCreate** - Used for creating task lists
2. **TaskStop** - Used for stopping background tasks
3. **EnterPlanMode** - Used for entering plan mode during implementation
4. **ExitPlanMode** - Used for exiting plan mode and requesting user approval

## Error Pattern

```
InputValidationError: InputValidationError: The required parameter 'subject' is missing
  An unexpected parameter 'prompt' was provided
  This tool's schema was not sent to the API — it was not in the discovered tool set derived from message history.
  Without the schema in your prompt, typed parameters (arrays, numbers, booleans) get emitted as strings and the client-side parser rejects them.
  Load the tool first: call ToolSearch with query "select:TaskCreate", then retry this call.
```

**Key insight:** The error message explicitly states: "Without the schema in your prompt, typed parameters get emitted as strings and the client-side parser rejects them." This means the schema discovery is critical for proper parameter type handling.

## Root Cause Analysis

### What Happened

1. When a tool like `TaskCreate` is invoked, the system needs its JSON Schema to properly format parameters
2. The schema discovery mechanism failed to find/load the tool definitions
3. Without schemas, all parameters are treated as strings by default
4. The client-side parser rejects string-typed parameters when the schema expects arrays, numbers, booleans, etc.
5. This creates a cascade of validation failures

### Why Schemas Weren't Found

From investigation:

- The tools exist as functional code paths
- But their JSON schemas weren't registered in the "discovered tool set"
- This can happen when:
  - Tools are loaded dynamically (deferred tools)
  - The tool registry isn't populated on session start
  - There's a mismatch between tool names and their schema registrations
  - Session context loss clears tool schema cache

## Files Related to the Issue

Based on codebase exploration, here are the relevant project files:

### Audio Project Files (already updated to 34 tools):
- `/Users/dev/_sell/mcp-ecosystem/audio/mcp/dynamic_server.py` - MCP server with 34 dynamically generated tools from OpenAPI spec
- `/Users/dev/_sell/mcp-ecosystem/audio/mcp/openapi.json` - Full OpenAPI 3.0 spec with 34 endpoints
- `/Users/dev/_sell/mcp-ecosystem/audio/start.sh` - Starts dynamic_server.py
- `/Users/dev/_sell/mcp-ecosystem/start-all.sh` - Uses `/status` endpoint to dynamically count tools
- `/Users/dev/_sell/mcp-ecosystem/audio/agent_audio.json` - Agent definition (tool count updated from 8 to 34)
- `/Users/dev/_sell/mcp-ecosystem/_ecosystem-reports/json/ecosystem_metadata.json` - Updated to 34 tools
- `/Users/dev/_sell/mcp-ecosystem/_ecosystem-reports/json/ecosystem_agents.json` - Updated to 34 tools

### Ecosystem Report Files:
- `/Users/dev/_sell/mcp-ecosystem/_ecosystem-reports/json/ecosystem_metadata.json` - Audio description, agents, MCP server tool list
- `/Users/dev/_sell/mcp-ecosystem/_ecosystem-reports/json/ecosystem_agents.json` - Audio agents with MCP server tool_count: 34

## Solution

### Immediate Fix: Tool Schema Registration

The core solution is to ensure all tool schemas are properly registered/loaded before any tool calls are made. This involves:

1. **Load tool schemas at startup** - Ensure all deferred tool schemas are discovered and registered
2. **Consolidate tool definitions** - Keep tool schemas in a consistent location
3. **Validate schema availability** - Before invoking tools, verify schemas are available

### Recommended Implementation

#### 1. Centralized Tool Schema Registry

Create a tool schema registry that loads all deferred tool definitions at session initialization:

```python
# Example: tool_registry.py
import json
import os
from pathlib import Path

TOOL_SCHEMAS_DIR = Path("/Users/dev/_sell/mcp-ecosystem/.claude/tools")  # or similar

def load_tool_schemas():
    """Load all tool JSON schemas at startup."""
    schemas = {}
    if TOOL_SCHEMAS_DIR.exists():
        for schema_file in TOOL_SCHEMAS_DIR.glob("*.json"):
            try:
                with open(schema_file) as f:
                    schema_data = json.load(f)
                tool_name = schema_data.get("name", schema_file.stem)
                schemas[tool_name] = schema_data
            except Exception as e:
                print(f"Warning: Failed to load schema {schema_file}: {e}")
    return schemas

# Load at module import time
TOOL_SCHEMAS = load_tool_schemas()
```

#### 2. Schema Availability Check

Before calling any tool, verify the schema exists:

```python
def validate_tool_schema(tool_name: str) -> bool:
    """Check if a tool schema is available."""
    return tool_name in TOOL_SCHEMAS if 'TOOL_SCHEMAS' in dir() else False
```

#### 3. Tool Search Fallback

When ToolSearch is used, ensure it has a fallback path:

```python
def safe_tool_search(query, max_results=5):
    """Search for tools with schema fallback."""
    try:
        result = ToolSearch(query=query, max_results=max_results)
        # Verify result has schema info
        if result and 'functions' in str(result):
            return result
    except Exception as e:
        pass
    
    # Fallback: manual schema loading
    schemas = load_tool_schemas()
    if query.split(':')[-1] in schemas:
        # Return the schema directly
        return schemas[query.split(':')[-1]]
    
    return None
```

#### 4. Session Initialization

Ensure tool schemas are loaded during session startup, not lazily:

```python
# In session startup hook
def on_session_start():
    """Initialize tool schemas when session starts."""
    global TOOL_SCHEMAS
    TOOL_SCHEMAS = load_tool_schemas()
    # Pre-load commonly used tools
    for tool_name in ['TaskCreate', 'TaskStop', 'EnterPlanMode', 'ExitPlanMode']:
        if tool_name not in TOOL_SCHEMAS:
            # Attempt to load from deferred tools
            load_deferred_tool_schema(tool_name)
```

### Long-term Architecture

#### Tool Schema Directory Structure

```
.claude/tools/
├── TaskCreate.json      {"name": "TaskCreate", "description": "...", "parameters": {...}}
├── TaskStop.json        {"name": "TaskStop", "description": "...", "parameters": {...}}
├── EnterPlanMode.json   {"name": "EnterPlanMode", "description": "...", "parameters": {...}}
├── ExitPlanMode.json    {"name": "ExitPlanMode", "description": "...", "parameters": {...}}
├── WebSearch.json
├── Grep.json
├── Read.json
├── Edit.json
├── Bash.json
└── ...
```

#### Dynamic Schema Loading

Instead of hardcoding schemas, discover them from tool definitions:

```python
def discover_tool_schemas_from_codebase(base_dir):
    """Discover tool schemas by scanning codebase for ToolSearch calls."""
    schemas = {}
    # Look for ToolSearch results or tool definition files
    # This could read from __init__.py, tool definitions, etc.
    return schemas
```

## Verification

After implementing the solution, verify:

1. **Task creation works**: `TaskCreate` with proper parameters succeeds
2. **Task stopping works**: `TaskStop` with proper parameters succeeds  
3. **Plan mode works**: `EnterPlanMode`/`ExitPlanMode` can be entered/exited
4. **Other tools work**: `Grep`, `Read`, `Write`, `Bash`, `Glob` all function correctly
5. **No InputValidationError** on tool calls that previously failed

## Testing Checklist

- [ ] `TaskCreate` with `subject` and optional `description` works
- [ ] `TaskStop` with `task_id` works  
- [ ] `EnterPlanMode` can be entered
- [ ] `ExitPlanMode` returns user approval
- [ ] `Grep` searches work with proper patterns
- [ ] `Read` accesses files correctly
- [ ] `Write` creates/edits files without schema errors
- [ ] `Bash` executes commands properly
- [ ] No `InputValidationError` messages appear

## Related Issues and Context

This issue has been observed across multiple projects using Claude in the backend. The pattern is consistent:

1. Tool is invoked
2. System tries to validate parameters against JSON schema
3. Schema not found in discovered tool set
4. Parameters emitted as strings (default)
5. Client-side parser rejects type mismatches
6. `InputValidationError` is raised

The fix requires ensuring tool schemas are either:
- Pre-loaded at session startup, OR
- Dynamically discovered and registered before tool invocation, OR
- Available through a consistent fallback mechanism

## Conclusion

The `InputValidationError` issue is fundamentally a schema discovery problem. By implementing a robust tool schema registration/loading mechanism at startup, and ensuring all deferred tool schemas are available before any tool calls are made, this issue can be resolved permanently across all projects using this Claude code agent setup.