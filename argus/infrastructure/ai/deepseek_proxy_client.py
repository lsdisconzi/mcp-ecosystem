# -*- coding: utf-8 -*-
"""
infrastructure/ai/deepseek_proxy_client.py

Wraps HTTP calls to the DeepSeek Reasoner proxy running at localhost:8019.
This is the only place in the codebase that calls requests.post() for AI.
"""
import json
from typing import Any, Dict, Generator, Iterator

import requests


_DEFAULT_ENDPOINT = "http://localhost:8019/v1/assistants/deepseek-stream-proxy"
_DEFAULT_TIMEOUT = 320


class DeepseekProxyClient:
    """Client for the local DeepSeek Reasoner proxy (streaming SSE)."""

    def __init__(
        self,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout

    def stream(self, payload: Dict[str, Any]) -> Generator[str, None, None]:
        """
        POST payload to the proxy and yield raw SSE lines as they arrive.
        Caller is responsible for parsing each line.
        """
        response = requests.post(
            self._endpoint,
            json=payload,
            stream=True,
            timeout=self._timeout,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                yield line.decode("utf-8") + "\n"
