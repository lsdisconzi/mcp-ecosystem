"""Tools API endpoints - single source of truth."""
import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Body
from pydantic import BaseModel

from data.tools import registry
from api.schemas import ToolCreateRequest, ToolExecuteRequest

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Request Models ==============

class ToolCreateRequest(BaseModel):
    type: str = "function"
    function: dict


class ToolExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}
    model: Optional[str] = None
    assistant_id: Optional[str] = None


# ============== Tool Endpoints ==============

@router.get("/tools")
async def list_tools():
    """List all registered tools in OpenAI format."""
    try:
        schemas = registry.get_schemas()
        return {"object": "list", "data": schemas}
    except Exception as e:
        logger.error(f"Error listing tools: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    """Get a specific tool by name."""
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return tool.to_schema()


@router.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, request: Request):
    """Execute a specific tool by name."""
    try:
        try:
            payload = await request.json()
        except:
            payload = {}
        
        parameters = payload.get("parameters", payload)
        
        tool = registry.get(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
        result = await registry.execute(tool_name, **parameters)
        
        if result.success:
            return {"success": True, "tool": tool_name, "result": result.data}
        else:
            raise HTTPException(status_code=500, detail=result.error)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/execute")
async def execute_tool_by_name(request: ToolExecuteRequest = Body(...)):
    """Execute a tool using request body for tool name."""
    tool = registry.get(request.tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{request.tool_name}' not found")
    
    result = await registry.execute(request.tool_name, **request.parameters)
    
    if result.success:
        return {"success": True, "tool": request.tool_name, "result": result.data}
    else:
        raise HTTPException(status_code=500, detail=result.error)


@router.post("/tools")
def create_tool(req: ToolCreateRequest):
    """Create a new user-defined tool."""
    try:
        if req.type != "function":
            raise HTTPException(status_code=422, detail="Only 'function' type supported")
        
        function = req.function
        for field in ["name", "description", "parameters"]:
            if field not in function:
                raise HTTPException(status_code=422, detail=f"Missing '{field}' field")
        
        if "properties" not in function["parameters"]:
            function["parameters"]["properties"] = {}
        if "required" not in function["parameters"]:
            function["parameters"]["required"] = []
        
        tool_name = function["name"]
        tool_path = f"data/tools/user_defined/{tool_name}.json"
        os.makedirs("data/tools/user_defined", exist_ok=True)
        
        tool_data = {
            "name": function["name"],
            "description": function["description"],
            "parameters": function["parameters"],
            "action": function.get("action", {"type": "python", "code": "None"}),
            "created_at": int(datetime.now().timestamp())
        }
        
        with open(tool_path, 'w') as f:
            json.dump(tool_data, f, indent=2)
        
        from data.tools.json_tool import JsonTool
        new_tool = JsonTool(tool_data)
        registry.register(new_tool)
        
        return {"success": True, "tool": {"type": "function", "function": tool_data}}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating tool: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tools/{tool_name}")
async def delete_tool(tool_name: str):
    """Delete a user-defined tool."""
    tool_path = f"data/tools/user_defined/{tool_name}.json"
    
    if not os.path.exists(tool_path):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    os.remove(tool_path)
    registry.unregister(tool_name)
    return {"success": True, "message": f"Tool '{tool_name}' deleted"}


# ============== Special Tool Endpoints ==============

@router.post("/tools/deep_reasoning")
async def deep_reasoning(
    question: str = Body(...),
    max_steps: int = Body(3),
    use_knowledge_graph: bool = Body(True),
    verify_with_files: bool = Body(True),
    files: List[str] = Body([]),
    model: Optional[str] = Body(None)
):
    """Execute deep reasoning tool directly."""
    parameters = {
        "question": question,
        "max_steps": max_steps,
        "use_knowledge_graph": use_knowledge_graph,
        "verify_with_files": verify_with_files,
        "files": files
    }
    
    result = await registry.execute("deep_reasoning", **parameters)
    
    if result.success:
        return {"success": True, "result": result.data}
    else:
        raise HTTPException(status_code=500, detail=result.error)