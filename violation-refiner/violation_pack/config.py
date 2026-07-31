"""Environment-driven configuration for the optional extensions.

The core library stays dependency-free; this module is only imported when
the user wires up Qdrant / Neo4j / Ollama. A `.env` file at the project
root is parsed manually so we don't need python-dotenv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _infer_llm_provider(explicit: str | None, base_url: str | None) -> str:
    """Resolve provider from explicit env first, then from base_url hint."""
    if explicit:
        return explicit.strip().lower()
    host = (base_url or "").strip().lower()
    if "deepseek" in host:
        return "deepseek"
    if "openrouter" in host:
        return "openrouter"
    if "anthropic" in host:
        return "anthropic"
    if "openai" in host:
        return "openai"
    if "11436" in host or "ollama" in host:
        return "ollama"
    return "openrouter"


def _resolve_llm_api_key(provider: str) -> str | None:
    """Resolve API key from generic and provider-specific env names."""
    if os.environ.get("LLM_API_KEY"):
        return os.environ.get("LLM_API_KEY")
    provider_key_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "ollama": "OLLAMA_API_KEY",
    }
    key_name = provider_key_map.get(provider.strip().lower())
    if key_name:
        return os.environ.get(key_name) or None
    return None


def _resolve_llm_model(provider: str) -> str | None:
    """Resolve model from generic and provider-specific env names.

    Precedence: generic LLM_MODEL (if set) > provider-specific <PROVIDER>_MODEL.
    Returns None when neither is set; caller falls back to the llm.py default.
    """
    if os.environ.get("LLM_MODEL"):
        return os.environ.get("LLM_MODEL")
    provider_model_map = {
        "openrouter": "OPENROUTER_MODEL",
        "anthropic": "ANTHROPIC_MODEL",
        "deepseek": "DEEPSEEK_MODEL",
        "openai": "OPENAI_MODEL",
        "ollama": "OLLAMA_MODEL",
    }
    key_name = provider_model_map.get(provider.strip().lower())
    if key_name:
        return os.environ.get(key_name) or None
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser. Ignores comments and blanks. Does not
    expand variables. Quotes around the value are stripped."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def load_dotenv(env_file: Path | None = None, override: bool = False) -> dict[str, str]:
    """Load .env values into os.environ. Returns the dict that was loaded."""
    if env_file is None:
        env_file = Path(__file__).resolve().parent.parent / ".env"
    values = _parse_env_file(env_file)
    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v
    return values


@dataclass(frozen=True)
class Settings:
    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_collection_prefix: str

    neo4j_uri: str | None
    neo4j_user: str | None
    neo4j_password: str | None
    neo4j_database: str

    ollama_host: str | None
    ollama_embed_model: str

    # LLM enrichment ---------------------------------------------------------
    llm_provider: str
    llm_model: str | None
    llm_api_key: str | None
    llm_base_url: str | None
    llm_temperature: float
    llm_max_tokens: int
    llm_token_budget: int
    llm_timeout_seconds: float

    # Confidence --------------------------------------------------------------
    authority_verification_floor: float

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file=env_file, override=False)
        llm_base_url = os.environ.get("LLM_BASE_URL") or None
        llm_provider = _infer_llm_provider(
            os.environ.get("LLM_PROVIDER"),
            llm_base_url,
        )
        # When LLM_PROVIDER is set explicitly (not inferred from LLM_BASE_URL),
        # drop a non-matching LLM_BASE_URL so the provider's default applies.
        explicit_provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
        if explicit_provider and llm_base_url:
            host = llm_base_url.lower()
            mismatched = (
                (explicit_provider == "openrouter" and "openrouter" not in host)
                or (explicit_provider == "deepseek" and "deepseek" not in host)
                or (explicit_provider == "anthropic" and "anthropic" not in host)
                or (explicit_provider == "openai" and "openai.com" not in host)
            )
            if mismatched:
                llm_base_url = None
        llm_api_key = _resolve_llm_api_key(llm_provider)
        llm_model = _resolve_llm_model(llm_provider)
        return cls(
            qdrant_url=os.environ.get("QDRANT_URL") or None,
            qdrant_api_key=os.environ.get("QDRANT_API_KEY") or None,
            qdrant_collection_prefix=os.environ.get(
                "QDRANT_COLLECTION_PREFIX", "violationrefiner_v1"
            ),
            neo4j_uri=os.environ.get("NEO4J_LOCAL_URI")
            or os.environ.get("NEO4J_URI")
            or None,
            neo4j_user=os.environ.get("NEO4J_LOCAL_USER")
            or os.environ.get("NEO4J_USER")
            or None,
            neo4j_password=os.environ.get("NEO4J_LOCAL_PASS")
            or os.environ.get("NEO4J_PASSWORD")
            or None,
            neo4j_database=os.environ.get(
                "NEO4J_DATABASE", "agent.violation.refiner"
            ),
            ollama_host=os.environ.get("OLLAMA_HOST") or None,
            ollama_embed_model=os.environ.get(
                "OLLAMA_EMBED_MODEL", "bge-m3"
            ),
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_temperature=float(os.environ.get("LLM_TEMPERATURE", "0.1")),
            llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "8000")),
            llm_token_budget=int(os.environ.get("LLM_TOKEN_BUDGET", "250000")),
            llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "90")),
            authority_verification_floor=float(
                os.environ.get("AUTHORITY_VERIFICATION_FLOOR", "0.85")
            ),
        )

    def llm_client(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        """Construct the configured LLM client. Lazy-imports llm.py so the
        core package stays import-cheap and dependency-free. Any keyword
        argument overrides the Settings value."""
        from .llm import build_client

        return build_client(
            provider=provider or self.llm_provider,
            model=model or self.llm_model,
            api_key=api_key or self.llm_api_key,
            base_url=base_url or self.llm_base_url,
            timeout=timeout or self.llm_timeout_seconds,
        )
