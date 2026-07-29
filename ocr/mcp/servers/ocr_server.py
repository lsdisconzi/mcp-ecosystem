#!/usr/bin/env python3
"""MCP tools for OCR image processing workflows."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (
    add_project_root_to_path,
    apply_deepseek_base_url,
    error_payload,
    get_deepseek_api_key,
    resolve_project_path,
    to_relative,
)

try:
    from fastmcp import FastMCP
except Exception:
    from mcp.server.fastmcp import FastMCP

add_project_root_to_path()

import ocr_with_llm_enhancement as ocr_module  # noqa: E402

apply_deepseek_base_url(ocr_module)

mcp = FastMCP("ocr")


@mcp.tool(name="ocr_list_images")
def ocr_list_images(
    input_dir: str = "screenshots",
    extensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """List image files available for OCR processing."""
    try:
        resolved_input = resolve_project_path(input_dir)
        resolved_ext = extensions or ocr_module.DEFAULT_CONFIG["supported_extensions"]
        files = ocr_module.get_image_files(str(resolved_input), resolved_ext)

        return {
            "ok": True,
            "input_dir": to_relative(resolved_input),
            "count": len(files),
            "files": [to_relative(path) for path in files],
            "extensions": resolved_ext,
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="ocr_process_image")
def ocr_process_image(
    image_path: str,
    include_llm: bool = False,
    review_prompt_override: str = "",
) -> Dict[str, Any]:
    """Run OCR on one image and optionally refine with DeepSeek."""
    try:
        resolved_image = resolve_project_path(image_path)
        ocr_result = ocr_module.process_image_with_ocr(str(resolved_image))

        response: Dict[str, Any] = {
            "ok": "error" not in ocr_result,
            "image_path": to_relative(resolved_image),
            "ocr_result": ocr_result,
            "llm_enabled": include_llm,
        }

        if include_llm and "error" not in ocr_result:
            api_key = get_deepseek_api_key()
            client = ocr_module.DeepSeekClient(api_key=api_key)
            prompt = review_prompt_override.strip() or ocr_module.DEFAULT_CONFIG["review_prompt"]
            refined_result = client.refine_ocr_results(ocr_result, prompt)
            comparison = client.compare_and_validate(ocr_result, refined_result)

            response["refined_result"] = refined_result
            response["comparison"] = comparison
            response["ok"] = "error" not in refined_result

        return response
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="ocr_compare_results")
def ocr_compare_results(
    original_ocr: Dict[str, Any],
    refined_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare raw OCR output against LLM-refined output."""
    try:
        api_key = get_deepseek_api_key()
        client = ocr_module.DeepSeekClient(api_key=api_key)
        comparison = client.compare_and_validate(original_ocr, refined_result)
        return {"ok": True, "comparison": comparison}
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="ocr_run_batch")
def ocr_run_batch(
    input_dir: str = "screenshots",
    output_dir: str = "llm_enhanced_results",
    include_llm: bool = True,
) -> Dict[str, Any]:
    """Run batch OCR for all images in a directory."""
    try:
        resolved_input = resolve_project_path(input_dir)
        resolved_output = resolve_project_path(output_dir)
        resolved_output.mkdir(parents=True, exist_ok=True)

        config = dict(ocr_module.DEFAULT_CONFIG)
        config["input_dir"] = str(resolved_input)
        config["output_dir"] = str(resolved_output)

        deepseek_client = None
        if include_llm:
            api_key = get_deepseek_api_key()
            deepseek_client = ocr_module.DeepSeekClient(api_key=api_key)

        results = ocr_module.process_batch(
            input_dir=str(resolved_input),
            output_dir=str(resolved_output),
            config=config,
            deepseek_client=deepseek_client,
        )

        summaries = sorted(
            glob.glob(str(resolved_output / "processing_summary_*.json")),
            key=lambda path: Path(path).stat().st_mtime,
            reverse=True,
        )

        return {
            "ok": True,
            "input_dir": to_relative(resolved_input),
            "output_dir": to_relative(resolved_output),
            "include_llm": include_llm,
            "results": results,
            "latest_summary": to_relative(summaries[0]) if summaries else None,
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="ocr_list_output_artifacts")
def ocr_list_output_artifacts(output_dir: str = "llm_enhanced_results") -> Dict[str, Any]:
    """List generated output artifacts from OCR processing."""
    try:
        resolved_output = resolve_project_path(output_dir)
        if not resolved_output.exists():
            return {
                "ok": False,
                "error": f"Output directory does not exist: {to_relative(resolved_output)}",
            }

        artifacts = {
            "raw_ocr": sorted((resolved_output / "raw_ocr").glob("*.json")),
            "llm_refined": sorted((resolved_output / "llm_refined").glob("*.json")),
            "comparisons": sorted((resolved_output / "comparisons").glob("*.json")),
            "summaries": sorted(resolved_output.glob("processing_summary_*.json")),
            "logs": sorted((resolved_output / "logs").glob("*")),
        }

        return {
            "ok": True,
            "output_dir": to_relative(resolved_output),
            "counts": {key: len(value) for key, value in artifacts.items()},
            "artifacts": {
                key: [to_relative(path) for path in value]
                for key, value in artifacts.items()
            },
        }
    except Exception as error:
        return error_payload(error)


if __name__ == "__main__":
    import os
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8125"))

    if transport in ("sse", "streamable-http"):
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
