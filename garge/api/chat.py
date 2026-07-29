"""
api/chat.py — Chat and Models endpoints.

Extracted from main.py (A3): keeps the Ollama model cache and the two
OpenAI-compatible endpoints that drive the main chat UI.
"""

import asyncio
import logging
import time
import unicodedata
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas import ChatRequest, ChatResponse, ModelsListResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Ollama model cache — avoids a blocking subprocess on every request (A7)
# ---------------------------------------------------------------------------
_OLLAMA_MODELS_CACHE: Dict[str, Any] = {"models": [], "fetched_at": 0.0}
_OLLAMA_CACHE_TTL: float = 60.0  # seconds


async def _get_ollama_models() -> List[str]:
    """Return local Ollama model names via HTTP API; cached for 60 s."""
    now = time.time()
    if now - _OLLAMA_MODELS_CACHE["fetched_at"] < _OLLAMA_CACHE_TTL:
        return _OLLAMA_MODELS_CACHE["models"]

    import os as _os
    from config.settings import settings as _settings
    # Honour OLLAMA_BASE_URL env var (set in docker-compose for container access)
    env_url = _os.environ.get('OLLAMA_BASE_URL', '')
    base = (env_url or getattr(_settings, 'ollama_base_url', 'http://localhost:11434')).rstrip('/')
    # Strip OpenAI-compat /v1 suffix to get native Ollama API root
    api_root = base[:-3] if base.endswith('/v1') else base

    models: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{api_root}/api/tags")
        if resp.is_success:
            models = [m['name'] for m in resp.json().get('models', [])]
    except Exception as exc:
        logger.debug(f"Ollama HTTP tags failed ({api_root}): {exc}")

    if not models:
        models = list(_OLLAMA_MODELS_CACHE["models"])  # keep stale on error

    _OLLAMA_MODELS_CACHE.update({"models": models, "fetched_at": now})
    return models


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_DEFAULT_LOCAL_MODEL = "llama3.1:8b"


@router.get("/v1/models", tags=["Models"], response_model=ModelsListResponse)
async def list_models():
    """List available local Ollama models, with llama3.1:8b pinned first."""
    try:
        ollama_names = await _get_ollama_models()
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
        ollama_names = []

    # Pin the preferred default first, then sort the rest alphabetically
    preferred = _DEFAULT_LOCAL_MODEL
    pinned = [preferred] if preferred in ollama_names else []
    rest = sorted(n for n in ollama_names if n != preferred)
    ordered = pinned + rest

    # Fallback: ensure the default always appears even if Ollama is unreachable
    if not ordered:
        ordered = [preferred]

    ts = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": ts, "owned_by": "ollama", "api_type": "local"}
            for name in ordered
        ],
    }


# ---------------------------------------------------------------------------
# External provider routing helpers
# ---------------------------------------------------------------------------
_EXTERNAL_BASE_URLS: Dict[str, str] = {
    "openai":    "https://api.openai.com/v1",
    "anthropic": "https://api.deepseek.com/anthropic",
    "groq":      "https://api.groq.com/openai/v1",
    "xai":       "https://api.x.ai/v1",
}


def _build_external_url(provider: str, base_url: Optional[str]) -> str:
    root = (base_url or _EXTERNAL_BASE_URLS.get(provider, "")).rstrip("/")
    if not root:
        return ""

    if provider == "anthropic":
        if root.endswith("/v1/messages"):
            return root
        if root.endswith("/v1"):
            return f"{root}/messages"
        return f"{root}/v1/messages"

    return f"{root}/chat/completions"


def _to_anthropic_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    system_chunks: List[str] = []
    anthropic_messages: List[Dict[str, str]] = []

    for message in payload.get("messages", []):
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))

        if role == "system":
            if content.strip():
                system_chunks.append(content)
            continue

        anthropic_role = "assistant" if role == "assistant" else "user"
        anthropic_messages.append({"role": anthropic_role, "content": content})

    if not anthropic_messages:
        anthropic_messages = [{"role": "user", "content": ""}]

    anthropic_payload: Dict[str, Any] = {
        "model": payload.get("model"),
        "messages": anthropic_messages,
        "max_tokens": payload.get("max_tokens") or 2048,
    }

    if payload.get("temperature") is not None:
        anthropic_payload["temperature"] = payload["temperature"]
    if system_chunks:
        anthropic_payload["system"] = "\n\n".join(system_chunks)

    return anthropic_payload


def _anthropic_to_chat_completions(response_payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    content_blocks = response_payload.get("content", [])
    text = "".join(
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict)
    ).strip()

    usage = response_payload.get("usage", {})
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)

    return {
        "id": response_payload.get("id", "anthropic-proxy-response"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response_payload.get("model") or model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": response_payload.get("stop_reason") or "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def _forward_to_external_provider(
    provider: str,
    base_url: Optional[str],
    api_key: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Forward a /chat/completions request to an external OpenAI-compatible API."""
    url = _build_external_url(provider, base_url)
    if not url:
        raise HTTPException(status_code=400, detail=f"Unknown external provider: {provider}")

    request_payload = payload

    headers: Dict[str, str]
    if provider == "anthropic":
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }
        headers["anthropic-version"] = "2023-06-01"
        request_payload = _to_anthropic_payload(payload)
    else:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=request_payload, headers=headers)

    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code,
                            detail=f"{provider} API error: {resp.text[:500]}")

    response_payload = resp.json()
    if provider == "anthropic":
        return _anthropic_to_chat_completions(response_payload, str(payload.get("model", "")))
    return response_payload


@router.post("/v1/chat/completions", tags=["Chat"])
async def chat_completions(chat_req: ChatRequest, request: Request):
    """Enhanced chat completions — routes to local Ollama or external provider."""
    # --- External provider path ---
    provider = (chat_req.provider or "").lower()
    if provider and provider != "ollama" and provider != "local":
        api_key = chat_req.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400,
                                detail=f"api_key is required for provider '{provider}'")
        payload = {
            "model": chat_req.model,
            "messages": [m if isinstance(m, dict) else m.model_dump() for m in chat_req.messages],
            "temperature": chat_req.temperature,
            "max_tokens": chat_req.max_tokens,
        }
        return await _forward_to_external_provider(
            provider, chat_req.base_url, api_key, payload
        )

    # --- Local Ollama path ---
    assistant = request.app.state.assistant
    if not assistant:
        raise HTTPException(status_code=500, detail="AssistantCore not initialized")

    try:
        available_tools = None
        if chat_req.tools:
            from data.tools import registry
            available_tools = registry.get_schemas()

        # Normalize content (handles Unicode issues)
        normalized_messages = []
        for msg in chat_req.messages:
            normalized_msg = msg.model_dump()
            if normalized_msg.get("role") == "user" and normalized_msg.get("content"):
                normalized_msg["content"] = unicodedata.normalize("NFC", normalized_msg["content"])
            normalized_messages.append(normalized_msg)

        # Determine model to use
        model_to_use = chat_req.model
        is_local_model = False
        if model_to_use:
            try:
                is_local_model = model_to_use in await _get_ollama_models()
            except Exception:
                pass

        TIMEOUT_SECONDS = 120 if is_local_model else 60

        try:
            response = await asyncio.wait_for(
                assistant.generate_response(
                    messages=normalized_messages,
                    model=model_to_use,
                    temperature=chat_req.temperature,
                    top_p=chat_req.top_p,
                    max_tokens=getattr(chat_req, "max_tokens", 20000),
                    stream=chat_req.stream,
                    tools=available_tools,
                    tool_choice=chat_req.tool_choice,
                    assistant_id=chat_req.assistant_id,
                ),
                timeout=TIMEOUT_SECONDS,
            )

            if chat_req.stream:
                return StreamingResponse(response, media_type="text/event-stream")
            return response

        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Assistant response timed out after {TIMEOUT_SECONDS} seconds",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
