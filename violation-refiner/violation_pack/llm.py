"""Pluggable LLM client for enrichment.

Provides a minimal `LLMClient` Protocol with one method, `chat_json`, that
takes a list of messages and returns a parsed JSON object. Five backends
are supported, selected via `LLM_PROVIDER`:

    openrouter   (default; OpenAI-compatible, https://openrouter.ai/api/v1)
    anthropic    (Anthropic native messages API)
    deepseek     (OpenAI-compatible, https://api.deepseek.com)
    openai       (OpenAI native, https://api.openai.com/v1)
    ollama       (local, http://localhost:11436, OpenAI-compatible /v1 or
                  native /api/chat with JSON mode)

Why one method? Enrichment never streams; it asks for a structured JSON
object, retries on parse failure once, and is otherwise fire-and-forget.
Streaming, tool-calling, function-calling, etc. are deliberately out of
scope here — the layer functions are the schema, not the LLM provider.

The four OpenAI-compatible backends (openrouter, deepseek, openai, ollama)
share `OpenAICompatibleClient`; only base URLs and default headers differ.
Anthropic uses a separate adapter because its message format is different.

httpx is imported lazily so the core package stays dependency-free.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Raised when an LLM call fails after retries."""


class LLMClient(Protocol):
    """Minimal protocol every adapter satisfies."""

    provider: str
    model: str

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8000,
        system: str | None = None,
    ) -> dict[str, Any]:
        """Send messages, return a parsed JSON object. Raises LLMError on
        repeated parse / transport failures."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _httpx():
    try:
        import httpx  # type: ignore
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise LLMError(
            "httpx is required for LLM calls. Install with: pip install -e '.[llm]'"
        ) from exc
    return httpx


def _strip_code_fence(s: str) -> str:
    """Some models wrap JSON in ```json ... ``` even with JSON mode set.
    Strip a single leading/trailing fence if present."""
    s = s.strip()
    if s.startswith("```"):
        # remove first line (``` or ```json) and trailing ```
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(text)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model did not return valid JSON: {exc}\n--- raw ---\n{text[:2000]}") from exc
    if not isinstance(obj, dict):
        raise LLMError(f"model returned non-object JSON: {type(obj).__name__}")
    return obj


# ---------------------------------------------------------------------------
# OpenAI-compatible backends (OpenRouter, DeepSeek, OpenAI, Ollama /v1)
# ---------------------------------------------------------------------------

@dataclass
class OpenAICompatibleClient:
    provider: str
    model: str
    base_url: str
    api_key: str | None = None
    extra_headers: dict[str, str] | None = None
    timeout: float = 120.0

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8000,
        system: str | None = None,
    ) -> dict[str, Any]:
        httpx = _httpx()
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.extra_headers:
            headers.update(self.extra_headers)

        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        url = self.base_url.rstrip("/") + "/chat/completions"
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.provider}: transport error: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(
                f"{self.provider}: HTTP {r.status_code} from {url}: {r.text[:1000]}"
            )
        try:
            payload = r.json()
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"{self.provider}: malformed response: {exc}\n{r.text[:1000]}") from exc
        return _parse_json(content)


# ---------------------------------------------------------------------------
# Anthropic native
# ---------------------------------------------------------------------------

@dataclass
class AnthropicClient:
    provider: str = "anthropic"
    model: str = "claude-3-5-sonnet-latest"
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    timeout: float = 120.0

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8000,
        system: str | None = None,
    ) -> dict[str, Any]:
        httpx = _httpx()
        # Anthropic message shape: role + content; system is a top-level field.
        anth_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        # Append a JSON-only instruction to force JSON output without a real
        # `response_format` field (Anthropic doesn't support one yet).
        if anth_messages and anth_messages[-1]["role"] == "user":
            anth_messages[-1]["content"] = (
                anth_messages[-1]["content"]
                + "\n\nReturn ONLY a single JSON object. No prose, no code fences."
            )

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
        }
        if system:
            body["system"] = system

        url = self.base_url.rstrip("/") + "/messages"
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic: transport error: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(f"anthropic: HTTP {r.status_code}: {r.text[:1000]}")
        try:
            payload = r.json()
            parts = payload["content"]
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        except Exception as exc:
            raise LLMError(f"anthropic: malformed response: {exc}\n{r.text[:1000]}") from exc
        return _parse_json(text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Per-provider defaults. base_url and the env var that holds the API key.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-3.5-sonnet",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-sonnet-latest",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "ollama": {
        # Ollama's OpenAI-compatible endpoint lives under /v1 since 0.1.34.
        "base_url": "http://127.0.0.1:11436/v1",
        "api_key_env": "OLLAMA_API_KEY",  # usually unset; bearer ignored
        "default_model": "qwen2.5:14b-instruct",
    },
}


def build_client(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
) -> LLMClient:
    """Construct an LLMClient. All arguments fall back to env vars."""
    provider = (provider or os.environ.get("LLM_PROVIDER") or "openrouter").lower().strip()
    if provider not in PROVIDER_DEFAULTS:
        raise LLMError(
            f"unknown LLM_PROVIDER={provider!r}; supported: {sorted(PROVIDER_DEFAULTS)}"
        )
    defaults = PROVIDER_DEFAULTS[provider]
    model = model or os.environ.get("LLM_MODEL") or defaults["default_model"]
    base_url = base_url or os.environ.get("LLM_BASE_URL") or defaults["base_url"]
    api_key = (
        api_key
        or os.environ.get("LLM_API_KEY")
        or os.environ.get(defaults["api_key_env"])
    )
    timeout = timeout or float(os.environ.get("LLM_TIMEOUT_SECONDS", "90"))

    if provider == "anthropic":
        return AnthropicClient(
            model=model, api_key=api_key, base_url=base_url, timeout=timeout,
        )

    # Build OpenAI-compatible client with provider-specific extras.
    extra_headers: dict[str, str] = {}
    if provider == "openrouter":
        # OpenRouter recommends these so usage is attributable to the project.
        ref = os.environ.get("OPENROUTER_REFERER") or "https://github.com/violation-refiner"
        title = os.environ.get("OPENROUTER_TITLE") or "violation-refiner"
        extra_headers["HTTP-Referer"] = ref
        extra_headers["X-Title"] = title

    return OpenAICompatibleClient(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        extra_headers=extra_headers or None,
        timeout=timeout,
    )
