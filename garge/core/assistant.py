import asyncio
import base64
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import ollama
import logging

from config.settings import settings
from core.file_processor import FileProcessor
from core.local_llm import LocalLLMClient
from core.memory import MemoryManager
# from data.tools import registry

logger = logging.getLogger(__name__)


class AssistantCore:
    """Core class that manages interactions with Ollama models and tools."""

    def __init__(self):
        _ollama_url = (
            os.environ.get('OLLAMA_BASE_URL')
            or getattr(settings, 'ollama_base_url', None)
            or 'http://localhost:11436'
        )
        self.client = ollama.Client(host=_ollama_url)
        self.memory = MemoryManager()
        self.file_processor = FileProcessor()
        self.llm_client = LocalLLMClient()
        self._health_status = True
        self.supports_streaming = self.llm_client.timeout >= 300

    def _get_tools(self) -> List[Dict[str, Any]]:
        """Get all available tools in OpenAI format."""
        return registry.get_schemas()

    def _get_tool_names(self) -> List[str]:
        """Get list of available tool names."""
        return registry.list_tools()

    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models from Ollama."""
        try:
            models = self.client.list()
            return [
                {
                    "id": model["name"],
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "ollama"
                }
                for model in models.get("models", [])
            ]
        except Exception as e:
            self._health_status = False
            raise Exception(f"Failed to list models: {str(e)}")

    @staticmethod
    def get_assistant_data(assistant_id: str) -> dict:
        """Load assistant data from disk by ID."""
        file_path = os.path.join(settings.assistant_storage_path, f"{assistant_id}.json")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Assistant {assistant_id} not found")
        with open(file_path, "r") as f:
            return json.load(f)

    async def get_assistant_file_context(self, assistant_id: str) -> str:
        """Get file content context for an assistant"""
        try:
            assistant_data = self.get_assistant_data(assistant_id)
            file_ids = assistant_data.get("file_ids", [])
            if not file_ids:
                return ""
            
            context_parts = []
            files_dir = Path("data/files")
            
            for file_id in file_ids:
                metadata_file = files_dir / f"{file_id}_metadata.json"
                if not metadata_file.exists():
                    continue
                
                try:
                    with open(metadata_file, "r") as f:
                        file_data = json.load(f)
                    
                    file_path = files_dir / file_data["stored_filename"]
                    if file_path.exists():
                        with open(file_path, "rb") as f:
                            file_content = f.read()
                        
                        base64_content = base64.b64encode(file_content).decode('utf-8')
                        extracted_text = self.file_processor.extract_text_from_base64(
                            base64_content, 
                            file_data.get("content_type", "")
                        )
                        
                        if extracted_text and not extracted_text.startswith("[Error"):
                            context_parts.append(f"--- File: {file_data['filename']} ---\n{extracted_text}\n")
                
                except Exception as e:
                    logging.warning(f"Error processing file {file_id}: {e}")
                    continue
            
            if context_parts:
                return "\n### ASSISTANT KNOWLEDGE BASE ###\n\n" + "\n".join(context_parts) + "\n"
            
            return ""
            
        except Exception as e:
            logging.warning(f"Error getting assistant file context: {e}")
            return ""

    async def generate_response(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        top_p: float = 1.0,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        tools: Optional[List] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
        assistant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a response from the model based on input messages."""
        model_name = model or settings.default_model

        # Convert messages to dicts
        dict_messages = []
        for msg in messages:
            if hasattr(msg, 'model_dump'):
                dict_messages.append(msg.model_dump())
            elif hasattr(msg, 'dict'):
                dict_messages.append(msg.dict())
            elif isinstance(msg, dict):
                dict_messages.append(msg)
            else:
                raise TypeError(f"Unsupported message type: {type(msg)}")

        # Enrich messages with assistant context (files, tools, collections)
        if assistant_id:
            assistant_data = await self.load_assistant_data(assistant_id)
            if assistant_data:
                dict_messages = await self.enrich_messages_with_context(dict_messages, assistant_data)
                # Use assistant's model if specified and no override provided
                if not model and assistant_data.get("model"):
                    model_name = assistant_data["model"]
                # Merge assistant tools with request tools
                if assistant_data.get("tools") and not tools:
                    tools = assistant_data["tools"]
                logger.info(f"Enriched context for assistant {assistant_id}")

        formatted_messages = []
        has_images = any("images" in msg for msg in dict_messages)
        try:
            for msg in dict_messages:
                entry: Dict[str, Any] = {
                    "role": msg.get("role", ""),
                    "content": msg.get("content", "")
                }
                # Preserve images field for vision models
                if "images" in msg:
                    entry["images"] = msg["images"]
                formatted_messages.append(entry)

            current_message = dict_messages[-1].get('content', '') if dict_messages else ''

            if tools and len(tools) > 0:
                # Pass formatted_messages to preserve context
                response_content = await self._process_with_tools(
                    current_message,
                    tools,
                    formatted_messages=formatted_messages,
                    model_name=model_name,
                )
            elif has_images:
                # Use chat endpoint for vision/multimodal messages
                response = self.llm_client.generate_chat_completion(
                    messages=formatted_messages,
                    model=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream
                )
                response_content = response["choices"][0]["message"]["content"]
            else:
                response = self.llm_client.generate_completion(
                    messages=formatted_messages,
                    model=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream
                )
                response_content = response["choices"][0]["message"]["content"]

            await self.memory.save_interaction(formatted_messages, response_content)

            prompt_tokens = sum(len(str(msg["content"]).split()) * 1.3 for msg in formatted_messages)
            completion_tokens = len(response_content.split()) * 1.3

            return {
                "id": f"chatcmpl-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": response_content},
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": int(prompt_tokens),
                    "completion_tokens": int(completion_tokens),
                    "total_tokens": int(prompt_tokens + completion_tokens)
                }
            }
        except Exception as e:
            self._health_status = False
            logging.error(f"Failed to generate response: {str(e)}")
            raise

    async def _process_with_tools(
        self,
        query: str,
        tools: List,
        formatted_messages: List[Dict] = None,
        model_name: Optional[str] = None,
    ) -> str:
        """Process a query using available tools."""
        if not tools:
            return "No tools available for processing this query."

        selected_model = model_name or settings.default_model

        tool_selection_prompt = self._create_tool_selection_prompt(query, tools)
        
        selection_response = self.client.generate(
            model=selected_model,
            prompt=tool_selection_prompt,
            stream=False
        )
        
        tool_name = self._parse_tool_choice(selection_response["response"], tools)
        
        if tool_name == "none":
            # Use the full context from formatted_messages instead of raw query
            if formatted_messages:
                has_images = any("images" in msg for msg in formatted_messages)
                if has_images:
                    response = self.llm_client.generate_chat_completion(
                        messages=formatted_messages,
                        model=selected_model,
                        temperature=0.2,
                        stream=False
                    )
                else:
                    response = self.llm_client.generate_completion(
                        messages=formatted_messages,
                        model=selected_model,
                        temperature=0.2,
                        stream=False
                    )
                return response["choices"][0]["message"]["content"]
            else:
                response = self.client.generate(
                    model=selected_model,
                    prompt=query,
                    stream=False
                )
                return response["response"]
        
        # Get tool parameters from LLM
        tool_params = await self._extract_tool_parameters(query, tool_name, tools)
        
        # Execute tool via registry with proper parameters
        result = await registry.execute(tool_name, **tool_params)
        
        if not result.success:
            return f"Tool error: {result.error}"
        
        final_prompt = f"""Query: {query}\n\nTool Result: {result.data}\n\nPlease provide a helpful response based on the tool result."""
        final_response = self.client.generate(
            model=selected_model,
            prompt=final_prompt,
            stream=False
        )
        return final_response["response"]

    async def _extract_tool_parameters(self, query: str, tool_name: str, tools: List) -> dict:
        """Extract tool parameters from query using LLM."""
        # Find the tool schema
        tool_schema = None
        for tool in tools:
            if tool.get("type") == "function" and tool.get("function", {}).get("name") == tool_name:
                tool_schema = tool["function"]
                break
        
        if not tool_schema:
            return {}
        
        params = tool_schema.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])
        
        if not properties:
            return {}
        
        # Build prompt to extract parameters
        param_descriptions = []
        for name, spec in properties.items():
            req_marker = "(required)" if name in required else "(optional)"
            param_descriptions.append(f"- {name} {req_marker}: {spec.get('description', 'No description')}")
        
        extraction_prompt = f"""Extract parameters for the '{tool_name}' tool from this query.

Tool parameters:
{chr(10).join(param_descriptions)}

Query: "{query}"

Respond ONLY with valid JSON containing the parameter values. Example:
{{"param1": "value1", "param2": "value2"}}

If a parameter cannot be determined from the query, omit it (unless required).
JSON response:"""

        try:
            response = self.client.generate(
                model=settings.default_model,
                prompt=extraction_prompt,
                stream=False
            )
            
            # Parse JSON from response
            response_text = response["response"].strip()
            # Try to find JSON in response
            import re
            json_match = re.search(r'\{[^{}]*\}', response_text)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(response_text)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to extract tool parameters: {e}")
            return {}

    def _create_tool_selection_prompt(self, query: str, tools: List) -> str:
        """Create a prompt for the LLM to select the appropriate tool."""
        tool_descriptions = []
        for tool in tools:
            if tool.get("type") == "function" and tool.get("function"):
                func = tool["function"]
                name = func.get("name", "unknown")
                desc = func.get("description", "No description")
                tool_descriptions.append(f"- {name}: {desc}")
        
        tools_text = "\n".join(tool_descriptions) if tool_descriptions else "No tools available"
        
        return f"""You are a tool selection assistant. Based on the user's query, select the most appropriate tool to use.

Available tools:
{tools_text}

User query: "{query}"

Instructions:
- If the user is asking about your capabilities, assigned files, tools, or collections, respond with "none" - you already have this information in your context
- If the user is asking a general knowledge question or conversational query, respond with "none"
- Only select a tool if the query explicitly requires performing an ACTION (like reading a specific file path, getting current time, etc.)
- If a tool is appropriate for the query, respond with ONLY the tool name (e.g., "filesystem" or "time_now")
- If no tool is needed or appropriate, respond with "none"
- Do not include any explanation, just the tool name or "none"

Tool selection:"""

    def _parse_tool_choice(self, response: str, tools: List) -> str:
        """Parse the LLM's tool selection response."""
        response_clean = response.strip().lower()
        
        # Get list of valid tool names
        valid_tools = []
        for tool in tools:
            if tool.get("type") == "function" and tool.get("function"):
                valid_tools.append(tool["function"].get("name", "").lower())
        
        # Check for explicit "none" response first
        if "none" in response_clean or "no tool" in response_clean:
            return "none"
        
        # Check if response matches a tool name exactly or contains it
        for tool_name in valid_tools:
            # Exact match takes priority
            if response_clean == tool_name:
                return tool_name
            # Partial match as fallback
            if tool_name in response_clean:
                return tool_name
        
        # Default to none if no match
        return "none"

    def is_healthy(self) -> bool:
        try:
            response = self.client.list()
            self._health_status = "models" in response
            return self._health_status
        except Exception as e:
            self._health_status = False
            logging.warning(f"Health check failed: {e}")
            return False

    async def generate_tool_suggestion(self, prompt, model=None, assistant_id=None):
        return {"name": "Example Tool", "description": f"Suggested tool for: {prompt}"}

    async def handle_tool_call(self, tool_name: str, arguments: dict):
        """Execute a tool call from LLM response."""
        result = await registry.execute(tool_name, **arguments)
        return result.data if result.success else f"Error: {result.error}"

    async def load_assistant_data(self, assistant_id: str) -> Optional[dict]:
        """Load assistant data from file storage."""
        try:
            assistant_path = Path(f"data/assistants/{assistant_id}.json")
            if assistant_path.exists():
                with open(assistant_path, "r") as f:
                    return json.load(f)
            logger.warning(f"Assistant file not found: {assistant_id}")
            return None
        except Exception as e:
            logger.error(f"Error loading assistant {assistant_id}: {e}")
            return None

    
    async def build_assistant_context(self, assistant_data: dict) -> str:
        """Build context string from assistant's files, tools, and collections."""
        context_parts = []
        
        # Add assistant identity
        assistant_name = assistant_data.get("name", "Assistant")
        context_parts.append(f"## Your Identity\nYou are **{assistant_name}**.")
        
        # Add instructions
        if assistant_data.get("instructions"):
            context_parts.append(f"## Your Instructions\n{assistant_data['instructions']}")
        
        # Add tools context - be very explicit
        tools_list = assistant_data.get("tools", [])
        if tools_list:
            tools_info = []
            for tool in tools_list:
                if tool.get("type") == "function" and tool.get("function"):
                    func = tool["function"]
                    tools_info.append(f"- **{func.get('name')}**: {func.get('description', 'No description')}")
            if tools_info:
                context_parts.append("## YOUR ASSIGNED TOOLS\nYou have been assigned the following tools:\n" + "\n".join(tools_info))
            else:
                context_parts.append("## YOUR ASSIGNED TOOLS\nNo tools assigned.")
        else:
            context_parts.append("## YOUR ASSIGNED TOOLS\nNo tools assigned.")
        
        # Add files context - be very explicit
        file_ids = assistant_data.get("file_ids", [])
        if file_ids:
            files_info = [f"- **{fid}**" for fid in file_ids]
            context_parts.append("## YOUR ASSIGNED FILES\nYou have been assigned the following files:\n" + "\n".join(files_info))
        else:
            context_parts.append("## YOUR ASSIGNED FILES\nNo files assigned.")
        
        # Add collections context - be very explicit
        collections = assistant_data.get("collections", [])
        if collections:
            collections_info = [f"- **{c}**" for c in collections]
            context_parts.append("## YOUR ASSIGNED COLLECTIONS\nYou have been assigned the following vector database collections:\n" + "\n".join(collections_info))
        else:
            context_parts.append("## YOUR ASSIGNED COLLECTIONS\nNo collections assigned.")
        
        # Add directive to use this context
        context_parts.append("""## IMPORTANT DIRECTIVE
When asked about your assigned files, tools, or collections, answer DIRECTLY using the information above.
Do NOT say you don't have access. Do NOT show your reasoning process.
Simply list what is assigned to you based on the context provided.""")
        
        return "\n\n".join(context_parts)

    async def enrich_messages_with_context(
        self, 
        messages: List[dict], 
        assistant_data: dict
    ) -> List[dict]:
        """Enrich messages with assistant's context (files, tools, collections)."""
        assistant_context = await self.build_assistant_context(assistant_data)
        
        if not assistant_context:
            return messages
        
        enriched_messages = list(messages)  # Create a proper copy
        
        # Find existing system message
        system_idx = next((i for i, m in enumerate(enriched_messages) if m.get("role") == "system"), None)
        
        if system_idx is not None:
            # Prepend context to existing system message
            existing_content = enriched_messages[system_idx].get("content", "")
            enriched_messages[system_idx] = {
                "role": "system",
                "content": f"{assistant_context}\n\n---\n\n{existing_content}"
            }
        else:
            # Insert new system message at the beginning
            enriched_messages.insert(0, {
                "role": "system",
                "content": assistant_context
            })
        
        logger.debug(f"System message content: {enriched_messages[0].get('content', '')[:500]}...")
        return enriched_messages

