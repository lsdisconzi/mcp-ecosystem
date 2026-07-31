import requests
import logging
import os
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from config.settings import settings

logger = logging.getLogger(__name__)

class LocalLLMClient:
    """Client for interacting with local LLM models"""

    DEFAULT_MODEL = "hermes3:8b"
    
    def __init__(self):
        # Resolve Ollama base URL from env → settings → hardcoded fallback
        env_url = os.environ.get('OLLAMA_BASE_URL', '')
        if not env_url:
            try:
                env_url = settings.ollama_base_url
            except Exception:
                pass
        self.base_url = (env_url or 'http://localhost:11436').rstrip('/')
        
        # Increase timeout for large documents
        self.timeout = 300  # 5 minutes instead of 120 seconds
        
    def get_available_models(self) -> List[Dict[str, str]]:
        """Get list of available models from Ollama"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [{"id": model["name"], "name": model["name"]} for model in models]
            return []
        except Exception as e:
            logger.error(f"Error getting models: {e}")
            return []
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List available models in OpenAI format"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "id": model["name"],
                        "object": "model",
                        "created": int(datetime.now().timestamp()),
                        "owned_by": "ollama"
                    })
                return models
            return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            # Return default models as fallback
            return [
                {
                    "id": self.DEFAULT_MODEL,
                    "object": "model",
                    "created": int(datetime.now().timestamp()),
                    "owned_by": "ollama"
                }
            ]

    def _parse_ollama_stream(self, response: requests.Response, model: str) -> Dict[str, Any]:
        """Parse NDJSON chunks returned by Ollama when stream=true."""
        full_text = ""
        prompt_tokens = 0
        completion_tokens = 0

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON stream chunk from Ollama")
                continue

            if isinstance(chunk, dict) and chunk.get("error"):
                return {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"API error: {chunk.get('error')}"
                            },
                            "finish_reason": "error"
                        }
                    ],
                    "error": str(chunk.get("error"))
                }

            # For /api/chat endpoint the token is under message.content
            msg = chunk.get("message", {})
            token_piece = msg.get("content", "") if msg else chunk.get("response", "")
            if token_piece:
                full_text += token_piece

            if chunk.get("done"):
                prompt_tokens = int(chunk.get("prompt_eval_count") or prompt_tokens)
                completion_tokens = int(chunk.get("eval_count") or completion_tokens)

        if not full_text:
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Error: Empty streaming response from model."
                        },
                        "finish_reason": "error"
                    }
                ],
                "error": "Empty streaming response from model"
            }

        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_text
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }
    
    def generate_completion(self, messages: Optional[List[Dict[str, Any]]] = None, prompt: Optional[str] = None, 
                           model: Optional[str] = None, temperature: float = 0.1, 
                           max_tokens: Optional[int] = None, stream: bool = False) -> Dict[str, Any]:
        """Generate text completion using local LLM.

        Either `messages` or `prompt` must be provided.

        Note: The `max_tokens` parameter defaults to None. If provided, it is included in the payload as 'num_predict'.
        """
        if model is None:
            model = self.DEFAULT_MODEL
        if messages is None and prompt is None:
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Error: Either 'messages' or 'prompt' must be provided."
                        },
                        "finish_reason": "error"
                    }
                ],
                "error": "Either 'messages' or 'prompt' must be provided."
            }
        try:
            # Handle both messages (OpenAI format) and prompt (direct format)
            if messages:
                # Convert messages to prompt
                prompt_text = ""
                for msg in messages:
                    if isinstance(msg, dict):
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                    else:
                        # fallback for object with attributes
                        role = getattr(msg, "role", "user")
                        content = getattr(msg, "content", "")
                    if role == "system":
                        prompt_text += f"System: {content}\n"
                    elif role == "user":
                        prompt_text += f"User: {content}\n"
                    elif role == "assistant":
                        prompt_text += f"Assistant: {content}\n"
                prompt_text += "Assistant: "
            else:
                prompt_text = prompt or ""
            
            payload = {
                "model": model,
                "prompt": prompt_text,
                "stream": stream,
                "temperature": temperature
            }
            
            if max_tokens is not None:
                payload["options"] = {"num_predict": max_tokens}
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=stream,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                if stream:
                    return self._parse_ollama_stream(response, model)

                result = response.json()
                if "response" in result:
                    return {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": result["response"]
                                },
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {
                            "prompt_tokens": result.get("prompt_eval_count", 0),
                            "completion_tokens": result.get("eval_count", 0),
                            "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0)
                        }
                    }
                else:
                    return {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "Error: No response from model."
                                },
                                "finish_reason": "error"
                            }
                        ],
                        "error": "No response from model."
                    }
            else:
                return {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"API error: {response.status_code} - {response.text}"
                            },
                            "finish_reason": "error"
                        }
                    ],
                    "error": f"API error: {response.status_code} - {response.text}"
                }
        except Exception as e:
            logger.error(f"Error generating completion: {e}")
            # Return error response instead of raising exception
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Error: Unable to generate response. {str(e)}"
                        },
                        "finish_reason": "error"
                    }
                ],
                "error": str(e)
            }

    def generate_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "llama3.1:8b",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Generate completion using Ollama /api/chat (supports multimodal/vision).

        Accepts messages with an optional ``images`` list (base64 data URLs) per
        message — the format Ollama vision models expect.
        """
        # Strip data:image/...;base64, prefix from Ollama images payload
        chat_messages = []
        for msg in messages:
            entry = {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            raw_images = msg.get("images", [])
            if raw_images:
                cleaned = []
                for img in raw_images:
                    # data:image/jpeg;base64,XXXX → XXXX
                    if "," in img:
                        img = img.split(",", 1)[1]
                    cleaned.append(img)
                entry["images"] = cleaned
            chat_messages.append(entry)

        payload = {
            "model": model,
            "messages": chat_messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        url = f"{self.base_url}/api/chat"

        try:
            if stream:
                response = requests.post(url, json=payload, stream=True, timeout=self.timeout)
            else:
                response = requests.post(url, json=payload, timeout=self.timeout)

            if not response.ok:
                try:
                    detail = response.json()
                except Exception:
                    detail = response.text
                logger.error(f"Ollama chat error {response.status_code}: {detail}")
                return {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": f"API error: {detail}"},
                        "finish_reason": "error"
                    }],
                    "error": str(detail)
                }

            if stream:
                return self._parse_ollama_stream(response, model)

            data = response.json()
            msg = data.get("message", {})
            content = msg.get("content", "")

            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": data.get("model", model),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                }
            }

        except requests.exceptions.Timeout:
            logger.error("Ollama chat request timed out")
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Error: Request timed out"},
                    "finish_reason": "error"
                }],
                "error": "Request timed out"
            }
        except Exception as e:
            logger.error(f"Error generating chat completion: {e}")
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": f"Error: {str(e)}"},
                    "finish_reason": "error"
                }],
                "error": str(e)
            }

    def health_check(self) -> bool:
        """Check if Ollama is available and responsive - synchronous version"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False