import base64
import os
from typing import Any, Dict, Optional
from pathlib import Path

import httpx


class GarageApiError(RuntimeError):
    """Raised when Garage API returns an error response."""


def _auth_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = os.getenv("GARAGE_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def get_base_url() -> str:
    return os.getenv("GARAGE_BASE_URL", "http://127.0.0.1:8066").rstrip("/")


async def garage_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """Perform a JSON request against Garage and raise clear exceptions on failure."""
    base_url = get_base_url()
    url = f"{base_url}{path}"

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.request(
            method=method.upper(),
            url=url,
            headers=_auth_headers(),
            params=params,
            json=json_body,
        )

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                detail = str(payload["detail"])
        except Exception:
            pass
        raise GarageApiError(f"{method.upper()} {path} failed ({response.status_code}): {detail}")

    if not response.content:
        return {"success": True}

    try:
        data = response.json()
    except Exception as exc:
        raise GarageApiError(f"{method.upper()} {path} returned non-JSON response") from exc

    if isinstance(data, dict):
        return data
    return {"data": data}


async def garage_multipart_request(
    method: str,
    path: str,
    *,
    file_field: str,
    file_path: str,
    form_fields: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 300.0,
) -> Dict[str, Any]:
    """Perform a multipart/form-data request against Garage."""
    base_url = get_base_url()
    url = f"{base_url}{path}"

    src = Path(file_path)
    if not src.exists() or not src.is_file():
        raise GarageApiError(f"File not found: {file_path}")

    headers = _auth_headers()
    # Let httpx set the multipart boundary automatically.
    headers.pop("Content-Type", None)

    with open(src, "rb") as fh:
        files = {file_field: (src.name, fh)}
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                data=form_fields or {},
                files=files,
            )

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                detail = str(payload["detail"])
        except Exception:
            pass
        raise GarageApiError(f"{method.upper()} {path} failed ({response.status_code}): {detail}")

    if not response.content:
        return {"success": True}

    try:
        data = response.json()
    except Exception as exc:
        raise GarageApiError(f"{method.upper()} {path} returned non-JSON response") from exc

    if isinstance(data, dict):
        return data
    return {"data": data}


async def garage_raw_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """Perform a request that may return non-JSON content (for downloads/binary)."""
    base_url = get_base_url()
    url = f"{base_url}{path}"

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.request(
            method=method.upper(),
            url=url,
            headers=_auth_headers(),
            params=params,
        )

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                detail = str(payload["detail"])
        except Exception:
            pass
        raise GarageApiError(f"{method.upper()} {path} failed ({response.status_code}): {detail}")

    content_type = response.headers.get("content-type", "")
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {
            "content_type": content_type,
            "data": payload,
        }
    except Exception:
        data = response.content or b""
        return {
            "content_type": content_type,
            "bytes": len(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }
