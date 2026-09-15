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
from typing import Any, Callable, Protocol


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
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        """Send messages, return a parsed JSON object. Raises LLMError on
        repeated parse / transport failures.

        `max_tokens` defaults to the client's configured budget, then to
        `LLM_MAX_TOKENS`. See `_json_within_budget` for the one automatic
        retry at a larger budget."""
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
# Output budget
#
# A reasoning model (DeepSeek's reasoner/flash, o1-style, ...) spends its
# `reasoning_tokens` out of the SAME `max_tokens` allowance as the answer. The
# enrichment prompts are large -- `_violation_snapshot` keeps every article's
# full `verbatim_excerpt` -- so the reasoner can consume the entire allowance
# thinking and never emit a single character of JSON. The provider then
# answers 200 OK with `content: ""` and `finish_reason: "length"`, and all the
# pipeline ever saw was `json.loads("")`:
#
#     model did not return valid JSON: Expecting value: line 1 column 1 (char 0)
#     --- raw ---
#
# ...with an empty raw excerpt, which named neither the cause nor the fix.
# The budget below is the first line of defence; the one-shot escalation in
# `_json_within_budget` is the second.
# ---------------------------------------------------------------------------

# Initial output budget, overridable per client or per call.
DEFAULT_MAX_TOKENS = 16000

# Hard cap for the automatic escalation retry. DeepSeek accepted 131072 in a
# probe, so this is a cost guard rather than a provider limit.
MAX_TOKENS_CEILING = 65536

# Multiplier applied to the budget for the single retry.
_BUDGET_ESCALATION = 4

# `finish_reason` values that mean "the provider cut the reply off because the
# output budget ran out". OpenAI-compatible backends say "length"; Anthropic
# says "max_tokens".
_TRUNCATED_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


@dataclass(frozen=True)
class Completion:
    """The parts of a chat completion the JSON path actually needs.

    `reasoning_content` is never used as the answer -- it is the model's
    scratch pad -- but its SIZE is the single most useful diagnostic when a
    reply comes back empty, so it is recorded here.
    """

    content: str
    finish_reason: str | None
    reasoning_chars: int
    reasoning_tokens: int | None
    completion_tokens: int | None

    @property
    def blank(self) -> bool:
        return not self.content.strip()

    @property
    def truncated(self) -> bool:
        return self.finish_reason in _TRUNCATED_REASONS


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def default_max_tokens() -> int:
    """Initial output budget. Read per call, not at import time: `.env` is
    loaded by `Settings.from_env()`, which runs after this module imports."""
    return _env_positive_int("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)


def _escalated(budget: int) -> int | None:
    """The budget for the escalation retry, or None when there is no room."""
    scaled = min(budget * _BUDGET_ESCALATION, MAX_TOKENS_CEILING)
    return scaled if scaled > budget else None


def _openai_completion(payload: dict[str, Any]) -> Completion:
    """Read an OpenAI-compatible `chat.completions` payload."""
    choice = payload["choices"][0]
    message = choice.get("message") or {}
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    return Completion(
        content=content if isinstance(content, str) else "",
        finish_reason=choice.get("finish_reason"),
        reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
        reasoning_tokens=details.get("reasoning_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )


def _anthropic_completion(payload: dict[str, Any]) -> Completion:
    """Read an Anthropic `messages` payload."""
    parts = payload["content"]
    text = "".join(
        p.get("text", "") for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    )
    usage = payload.get("usage") or {}
    return Completion(
        content=text,
        finish_reason=payload.get("stop_reason"),
        # Anthropic exposes reasoning only as signed thinking blocks, which
        # this adapter deliberately does not request.
        reasoning_chars=0,
        reasoning_tokens=None,
        completion_tokens=usage.get("output_tokens"),
    )


def _budget_error(
    label: str,
    reply: Completion,
    budget: int,
    *,
    escalation: int | None,
    refusal: str | None,
    retried: bool,
    cause: LLMError | None,
) -> LLMError:
    """Build the error for a reply that was empty or cut off by the budget."""
    facts = ", ".join(
        f"{name}={value}"
        for name, value in (
            ("finish_reason", repr(reply.finish_reason)),
            ("completion_tokens", reply.completion_tokens),
            ("reasoning_tokens", reply.reasoning_tokens),
            ("reasoning_chars", reply.reasoning_chars or None),
            ("max_tokens", budget),
        )
        if value is not None
    )

    if reply.blank:
        what = f"{label}: the model returned no content ({facts})"
    else:
        what = f"{label}: the reply was cut off before the JSON was complete ({facts})"

    lines = [what]
    if reply.blank and (reply.reasoning_chars or reply.reasoning_tokens):
        lines.append(
            "reasoning_content shares the max_tokens allowance with the answer: "
            "the model spent the whole budget thinking and never started the JSON."
        )
    if refusal is not None:
        lines.append(f"the retry at {escalation} tokens was refused: {refusal}")
    elif retried:
        lines.append(
            f"the retry at {escalation} tokens failed the same way, so the prompt "
            "itself is the likely limit -- shorten it or split the stage."
        )
    elif escalation is None:
        lines.append(
            f"max_tokens ({budget}) is already at or above the "
            f"{MAX_TOKENS_CEILING} escalation ceiling, so there was no room to retry."
        )
    else:
        lines.append("raise LLM_MAX_TOKENS.")
    if cause is not None:
        lines.append(str(cause))
    return LLMError("\n".join(lines))


def _try_parse(text: str) -> tuple[dict[str, Any] | None, LLMError | None]:
    """Parse, returning `(obj, None)` or `(None, the error to raise later)."""
    try:
        return _parse_json(text), None
    except LLMError as exc:
        return None, exc


def _json_within_budget(
    *,
    label: str,
    budget: int,
    send: Callable[[int], Completion],
) -> dict[str, Any]:
    """Send at `budget`; retry once at a larger budget if the reply was empty
    or cut off by the token cap.

    Only a budget failure is retried -- a reply that is complete but garbled
    is a prompt problem, and paying for it twice will not fix it.
    """
    reply = send(budget)
    obj, cause = _try_parse(reply.content)
    if obj is not None:
        return obj

    if not (reply.blank or reply.truncated):
        assert cause is not None
        raise cause

    escalation = _escalated(budget)
    if escalation is None:
        raise _budget_error(
            label, reply, budget,
            escalation=None, refusal=None, retried=False, cause=cause,
        )

    try:
        retry = send(escalation)
    except LLMError as refused:
        # A hard per-model ceiling turns the bigger budget into a 400. The
        # first attempt's diagnosis is the more useful error, so keep it and
        # name the refusal.
        raise _budget_error(
            label, reply, budget,
            escalation=escalation, refusal=str(refused), retried=False, cause=cause,
        ) from None

    obj, cause = _try_parse(retry.content)
    if obj is not None:
        return obj
    raise _budget_error(
        label, retry, escalation,
        escalation=escalation, refusal=None, retried=True, cause=cause,
    )


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
    max_tokens: int | None = None

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
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

        url = self.base_url.rstrip("/") + "/chat/completions"

        def send(budget: int) -> Completion:
            body: dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "temperature": temperature,
                "max_tokens": budget,
                "response_format": {"type": "json_object"},
            }
            try:
                r = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
            except httpx.HTTPError as exc:
                raise LLMError(f"{self.provider}: transport error: {exc}") from exc
            if r.status_code >= 400:
                raise LLMError(
                    f"{self.provider}: HTTP {r.status_code} from {url}: {r.text[:1000]}"
                )
            try:
                return _openai_completion(r.json())
            except Exception as exc:
                raise LLMError(
                    f"{self.provider}: malformed response: {exc}\n{r.text[:1000]}"
                ) from exc

        budget = max_tokens or self.max_tokens or default_max_tokens()
        return _json_within_budget(
            label=f"{self.provider}/{self.model}",
            budget=budget,
            send=send,
        )


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
    max_tokens: int | None = None

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
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

        url = self.base_url.rstrip("/") + "/messages"

        def send(budget: int) -> Completion:
            body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": budget,
                "temperature": temperature,
                "messages": anth_messages,
            }
            if system:
                body["system"] = system
            try:
                r = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
            except httpx.HTTPError as exc:
                raise LLMError(f"anthropic: transport error: {exc}") from exc
            if r.status_code >= 400:
                raise LLMError(f"anthropic: HTTP {r.status_code}: {r.text[:1000]}")
            try:
                return _anthropic_completion(r.json())
            except Exception as exc:
                raise LLMError(
                    f"anthropic: malformed response: {exc}\n{r.text[:1000]}"
                ) from exc

        budget = max_tokens or self.max_tokens or default_max_tokens()
        return _json_within_budget(
            label=f"anthropic/{self.model}",
            budget=budget,
            send=send,
        )


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
    max_tokens: int | None = None,
) -> LLMClient:
    """Construct an LLMClient. All arguments fall back to env vars.

    `max_tokens` is the output budget per call. It defaults to `LLM_MAX_TOKENS`
    at request time, so leaving it unset is fine; passing it explicitly is how
    `Settings.llm_max_tokens` reaches the client.
    """
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
            max_tokens=max_tokens,
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
        max_tokens=max_tokens,
    )
