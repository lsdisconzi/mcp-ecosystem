#!/usr/bin/env python3
"""
Generate MCP-oriented catalog from Juris FastAPI OpenAPI schema.

Usage:
    .venv/bin/python3 mcp/generate_tool_catalog.py

Environment:
    JURIS_BASE_URL
        Default: http://127.0.0.1:8000

    MCP_CATALOG_OUT_JSON
        Default:
        mcp/catalog/juris_openapi_catalog.json

    MCP_CATALOG_OUT_MD
        Default:
        mcp/catalog/juris_openapi_catalog.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx


BASE_URL = os.getenv(
    "JURIS_BASE_URL",
    "http://127.0.0.1:8000"
)


OUT_JSON = Path(
    os.getenv(
        "MCP_CATALOG_OUT_JSON",
        "mcp/catalog/juris_openapi_catalog.json"
    )
)


OUT_MD = Path(
    os.getenv(
        "MCP_CATALOG_OUT_MD",
        "mcp/catalog/juris_openapi_catalog.md"
    )
)


def to_tool_name(
    method: str,
    path: str,
    operation_id: str | None
) -> str:

    seed = operation_id or f"{method}_{path}"

    cleaned = []

    for ch in seed.lower():
        if ch.isalnum() or ch == "_":
            cleaned.append(ch)
        else:
            cleaned.append("_")

    name = "".join(cleaned)

    while "__" in name:
        name = name.replace("__", "_")

    return name.strip("_")


def summarize_schema(schema: Dict[str, Any] | None):

    if not schema:
        return {}

    if "$ref" in schema:
        return {
            "$ref": schema["$ref"]
        }

    # `Optional[X]` renders as `anyOf: [{type: X}, {type: null}]`. Collapse it
    # back to a single readable type instead of the useless "any".
    any_of = schema.get("anyOf")

    if isinstance(any_of, list) and any_of:

        non_null = [
            s for s in any_of
            if isinstance(s, dict) and s.get("type") != "null"
        ]

        nullable = len(non_null) < len(any_of)

        if len(non_null) == 1:
            collapsed = summarize_schema(non_null[0])
            if nullable and "type" in collapsed:
                collapsed["type"] = f"{collapsed['type']} | null"
            return collapsed

        return {
            "type": " | ".join(
                str(summarize_schema(s).get("type", "any"))
                for s in any_of
            )
        }

    result = {}

    for key in (
        "title",
        "type",
        "description",
        "enum",
        "default"
    ):
        if key in schema:
            result[key] = schema[key]

    if "properties" in schema:
        result["properties"] = {
            k: summarize_schema(v)
            for k, v in schema["properties"].items()
        }

    if "required" in schema:
        result["required"] = schema["required"]

    if "items" in schema:
        result["items"] = summarize_schema(
            schema["items"]
        )

    return result


def summarize_request_body(
    request_body: Dict[str, Any] | None,
    components: Dict[str, Any] | None = None
):
    """Summarize an OpenAPI `requestBody` into a compact, tool-friendly shape.

    FastAPI declares Pydantic request models under `requestBody`, not under
    `parameters`, so ignoring this field hides every search/filter option from
    the catalog (e.g. all of `SearchFields`).

    When `components` is supplied, `$ref`s are resolved one level so the actual
    field names/descriptions appear inline in the catalog.
    """

    if not request_body:
        return {}

    result: Dict[str, Any] = {
        "required": request_body.get("required", False),
        "content_types": {},
    }

    def resolve_ref(ref: str):

        prefix = "#/components/schemas/"

        if not components or not ref.startswith(prefix):
            return None

        return components.get(ref[len(prefix):])

    for content_type, media in (request_body.get("content") or {}).items():

        schema = summarize_schema(
            media.get("schema") if isinstance(media, dict) else None
        )

        ref = schema.get("$ref")

        if ref:

            resolved = resolve_ref(ref)

            entry: Dict[str, Any] = {
                "$ref": ref,
            }

            if resolved:
                entry.update(
                    summarize_schema(resolved)
                )

            result["content_types"][content_type] = entry

        else:
            result["content_types"][content_type] = schema

    return result


def build_catalog(
    spec: Dict[str, Any],
    base_url: str
):

    tools = []

    for route, methods in sorted(
        spec.get("paths", {}).items()
    ):

        if not isinstance(methods, dict):
            continue


        for method, operation in sorted(
            methods.items()
        ):

            method = method.upper()

            if method not in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE"
            }:
                continue


            if not isinstance(operation, dict):
                continue


            tool_name = to_tool_name(
                method,
                route,
                operation.get(
                    "operationId"
                )
            )


            parameters = []

            for param in operation.get(
                "parameters",
                []
            ):

                parameters.append(
                    {
                        "name": param.get("name"),
                        "location": param.get("in"),
                        "required": param.get(
                            "required",
                            False
                        ),
                        "schema":
                            summarize_schema(
                                param.get(
                                    "schema"
                                )
                            )
                    }
                )


            tools.append(
                {
                    "tool_name": tool_name,
                    "method": method,
                    "path": route,
                    "url":
                        f"{base_url.rstrip('/')}{route}",
                    "operation_id":
                        operation.get(
                            "operationId"
                        ),
                    "summary":
                        operation.get(
                            "summary",
                            ""
                        ),
                    "description":
                        operation.get(
                            "description",
                            ""
                        ),
                    "tags":
                        operation.get(
                            "tags",
                            []
                        ),
                    "parameters":
                        parameters,

                    "request_body":
                        summarize_request_body(
                            operation.get(
                                "requestBody"
                            ),
                            spec.get(
                                "components", {}
                            ).get("schemas", {}),
                        ),
                }
            )


    return {
        "generated_from":
            f"{base_url.rstrip('/')}/openapi.json",

        "title":
            spec.get("info", {}).get(
                "title"
            ),

        "version":
            spec.get("info", {}).get(
                "version"
            ),

        "tool_count":
            len(tools),

        "tools":
            tools,
    }


def write_markdown(
    catalog,
    output: Path
):

    lines = []

    lines.append(
        "# Juris MCP Route Catalog"
    )

    lines.append("")

    lines.append(
        f"Source: {catalog['generated_from']}"
    )

    lines.append("")

    lines.append(
        f"Routes: {catalog['tool_count']}"
    )

    lines.append("")

    lines.append(
        "| Method | Path | Tags | Tool |"
    )

    lines.append(
        "|---|---|---|---|"
    )


    for tool in catalog["tools"]:

        tags = ", ".join(
            tool.get(
                "tags",
                []
            )
        )

        lines.append(
            f"| {tool['method']} | "
            f"{tool['path']} | "
            f"{tags} | "
            f"{tool['tool_name']} |"
        )


    # ── Request body schemas ──────────────────────────────────────────────
    # FastAPI puts Pydantic request models here (not in `parameters`), so
    # without this the search/filter fields are invisible in the catalog.
    bodies = [
        t for t in catalog["tools"]
        if (t.get("request_body") or {}).get("content_types")
    ]

    if bodies:

        lines.append("")
        lines.append("## Request Body Schemas")
        lines.append("")

        for tool in bodies:

            lines.append(
                f"### `{tool['method']} {tool['path']}`"
            )
            lines.append("")

            for content_type, schema in (
                tool["request_body"]["content_types"].items()
            ):

                lines.append(
                    f"`{content_type}`"
                    + (
                        f" — `{schema['$ref']}`"
                        if schema.get("$ref") else ""
                    )
                )
                lines.append("")

                props = schema.get("properties") or {}

                if not props:
                    lines.append(
                        "_Schema could not be resolved._"
                    )
                    lines.append("")
                    continue

                required = set(
                    schema.get("required") or []
                )

                lines.append(
                    "| Field | Type | Required | Description |"
                )
                lines.append(
                    "|---|---|---|---|"
                )

                for name, meta in props.items():

                    ftype = meta.get("type") or "any"

                    if not meta.get("type") and meta.get("anyOf"):
                        ftype = "anyOf"

                    enum = meta.get("enum")

                    if enum:
                        ftype += (
                            " ("
                            + ", ".join(
                                f"`{e}`" for e in enum
                            )
                            + ")"
                        )

                    description = (
                        meta.get("description") or ""
                    ).replace("|", "\\|").replace("\n", " ")

                    lines.append(
                        f"| `{name}` | {ftype} | "
                        f"{'yes' if name in required else ''} | "
                        f"{description} |"
                    )

                lines.append("")

    output.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )



def main():

    with httpx.Client(
        timeout=30
    ) as client:

        response = client.get(
            f"{BASE_URL}/openapi.json"
        )

        response.raise_for_status()

        spec = response.json()


    catalog = build_catalog(
        spec,
        BASE_URL
    )


    OUT_JSON.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    OUT_JSON.write_text(
        json.dumps(
            catalog,
            indent=2
        ),
        encoding="utf-8"
    )


    write_markdown(
        catalog,
        OUT_MD
    )


    print(
        json.dumps(
            {
                "generated":
                    str(OUT_JSON),

                "routes":
                    catalog["tool_count"]
            },
            indent=2
        )
    )


if __name__ == "__main__":
    main()