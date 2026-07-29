"""Embedders for the Qdrant-backed VectorIndex.

Strategies shipped in-package, listed best-to-worst for Chilean legal Spanish:

* `VoyageEmbedder`  — voyage-3-large (default). Hosted, multilingual,
  state-of-the-art retrieval quality. Requires VOYAGE_API_KEY.
* `OpenAIEmbedder`  — text-embedding-3-large. Multilingual, 3072-dim.
* `CohereEmbedder`  — embed-multilingual-v3.0, 1024-dim.
* `OllamaEmbedder`  — local model via /api/embeddings. Recommended model:
  `bge-m3` (1024-dim, multilingual). Falls back to `nomic-embed-text`.
* `HashEmbedder`    — deterministic, 384-dim, NOT semantic. Tests only.

Provider is selected by EMBED_PROVIDER env var: voyage|openai|cohere|ollama|hash.
All implement the same `Embedder` Protocol so the VectorIndex is agnostic.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Protocol, runtime_checkable
from urllib import error as _urlerr
from urllib import request as _urlreq


@runtime_checkable
class Embedder(Protocol):
    """Anything that maps strings to fixed-length float vectors."""

    name: str  # short identifier used to namespace collections
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post_json(url: str, body: dict, headers: dict, timeout: float = 60.0) -> dict:
    import time

    last_err: Exception | None = None
    for attempt in range(6):
        req = _urlreq.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except _urlerr.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            # Retry rate-limit / transient server errors with backoff.
            if exc.code in (408, 429, 500, 502, 503, 504) and attempt < 5:
                # Respect Retry-After if present, else exponential backoff.
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except ValueError:
                    delay = 0.0
                if delay <= 0:
                    delay = min(60.0, 2.0 * (2**attempt))
                time.sleep(delay)
                last_err = exc
                continue
            raise RuntimeError(
                f"HTTP {exc.code} from {url}: {body_text[:500]}"
            ) from exc
        except _urlerr.URLError as exc:  # pragma: no cover - network path
            if attempt < 5:
                time.sleep(min(30.0, 2.0 * (2**attempt)))
                last_err = exc
                continue
            raise RuntimeError(f"Embedding request to {url} failed: {exc}") from exc
    raise RuntimeError(f"Embedding request to {url} exhausted retries: {last_err}")


# ---------------------------------------------------------------------------
# HashEmbedder
# ---------------------------------------------------------------------------

class HashEmbedder:
    """Deterministic bag-of-tokens hash embedder. Tests only."""

    name = "hash-384"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in (text or "").lower().split():
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            bucket = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# OllamaEmbedder
# ---------------------------------------------------------------------------

class OllamaEmbedder:
    """Calls Ollama's `/api/embeddings` endpoint. Use `bge-m3` for best
    multilingual retrieval (recommended over `nomic-embed-text` for Spanish)."""

    def __init__(
        self,
        host: str,
        model: str = "bge-m3",
        dim: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._dim = dim
        self.name = f"ollama-{model}"

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self._call("dim"))
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._call(t) for t in texts]

    def _call(self, text: str) -> list[float]:
        payload = _post_json(
            f"{self.host}/api/embeddings",
            {"model": self.model, "prompt": text},
            headers={},
            timeout=self.timeout,
        )
        emb = payload.get("embedding")
        if not isinstance(emb, list):
            raise RuntimeError(f"Unexpected Ollama response: {payload!r}")
        return [float(x) for x in emb]


# ---------------------------------------------------------------------------
# VoyageEmbedder — recommended default
# ---------------------------------------------------------------------------

# voyage-3-large = 1024 dim (default output). voyage-3 = 1024, voyage-3-lite = 512.
_VOYAGE_DIMS = {
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-law-2": 1024,
    "voyage-multilingual-2": 1024,
}


class VoyageEmbedder:
    """Voyage AI embeddings. https://docs.voyageai.com/reference/embeddings-api"""

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3-large",
        input_type: str = "document",
        timeout: float = 60.0,
        batch_size: int = 64,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.input_type = input_type
        self.timeout = timeout
        self.batch_size = batch_size
        self.dim = _VOYAGE_DIMS.get(model, 1024)
        self.name = f"voyage-{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            payload = _post_json(
                "https://api.voyageai.com/v1/embeddings",
                {
                    "input": batch,
                    "model": self.model,
                    "input_type": self.input_type,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            data = payload.get("data") or []
            out.extend([list(map(float, item["embedding"])) for item in data])
        return out


# ---------------------------------------------------------------------------
# OpenAIEmbedder
# ---------------------------------------------------------------------------

_OPENAI_DIMS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder:
    """OpenAI embeddings. Compatible with any OpenAI-shaped endpoint
    (Deepseek, Together, etc.) by overriding `base_url`."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        batch_size: int = 64,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.batch_size = batch_size
        self.dim = _OPENAI_DIMS.get(model, 1536)
        self.name = f"openai-{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            payload = _post_json(
                f"{self.base_url}/embeddings",
                {"input": batch, "model": self.model},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            data = payload.get("data") or []
            out.extend([list(map(float, item["embedding"])) for item in data])
        return out


# ---------------------------------------------------------------------------
# CohereEmbedder
# ---------------------------------------------------------------------------

_COHERE_DIMS = {
    "embed-multilingual-v3.0": 1024,
    "embed-multilingual-light-v3.0": 384,
    "embed-english-v3.0": 1024,
}


class CohereEmbedder:
    """Cohere embeddings. https://docs.cohere.com/reference/embed"""

    def __init__(
        self,
        api_key: str,
        model: str = "embed-multilingual-v3.0",
        input_type: str = "search_document",
        timeout: float = 60.0,
        batch_size: int = 96,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.input_type = input_type
        self.timeout = timeout
        self.batch_size = batch_size
        self.dim = _COHERE_DIMS.get(model, 1024)
        self.name = f"cohere-{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            payload = _post_json(
                "https://api.cohere.com/v2/embed",
                {
                    "texts": batch,
                    "model": self.model,
                    "input_type": self.input_type,
                    "embedding_types": ["float"],
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            embeddings = (payload.get("embeddings") or {}).get("float") or []
            out.extend([list(map(float, e)) for e in embeddings])
        return out


# ---------------------------------------------------------------------------
# default_embedder — provider selection
# ---------------------------------------------------------------------------

def default_embedder(settings=None) -> Embedder:
    """Pick an embedder based on EMBED_PROVIDER and what is configured.

    Order if EMBED_PROVIDER is unset:
        1. Voyage (if VOYAGE_API_KEY)
        2. OpenAI (if OPENAI_API_KEY)
        3. Cohere (if COHERE_API_KEY)
        4. Ollama (if OLLAMA_HOST is reachable)
        5. HashEmbedder (always-available fallback)
    """
    from .config import Settings

    s = settings or Settings.from_env()
    provider = (os.environ.get("EMBED_PROVIDER") or "").lower().strip()

    def _try_voyage() -> Embedder | None:
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            return None
        model = os.environ.get("VOYAGE_MODEL", "voyage-3-large")
        return VoyageEmbedder(api_key=key, model=model)

    def _try_openai() -> Embedder | None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-large")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAIEmbedder(api_key=key, model=model, base_url=base)

    def _try_cohere() -> Embedder | None:
        key = os.environ.get("COHERE_API_KEY")
        if not key:
            return None
        model = os.environ.get("COHERE_EMBED_MODEL", "embed-multilingual-v3.0")
        return CohereEmbedder(api_key=key, model=model)

    def _try_ollama() -> Embedder | None:
        if not s.ollama_host:
            return None
        try:
            emb = OllamaEmbedder(s.ollama_host, s.ollama_embed_model)
            _ = emb.dim  # probe
            return emb
        except Exception:
            return None

    if provider == "voyage":
        return _try_voyage() or _raise("VOYAGE_API_KEY not set")
    if provider == "openai":
        return _try_openai() or _raise("OPENAI_API_KEY not set")
    if provider == "cohere":
        return _try_cohere() or _raise("COHERE_API_KEY not set")
    if provider == "ollama":
        return _try_ollama() or _raise(
            "OLLAMA_HOST not reachable or OLLAMA_EMBED_MODEL not pulled"
        )
    if provider == "hash":
        return HashEmbedder()

    # Auto-select.
    for fn in (_try_voyage, _try_openai, _try_cohere, _try_ollama):
        emb = fn()
        if emb is not None:
            return emb
    return HashEmbedder()


def _raise(msg: str) -> "Embedder":
    raise RuntimeError(msg)

