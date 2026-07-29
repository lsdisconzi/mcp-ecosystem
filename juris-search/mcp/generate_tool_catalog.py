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