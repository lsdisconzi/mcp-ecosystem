#!/usr/bin/env python3
"""MCP tools for PDF analysis and pipeline orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from common import (
    add_project_root_to_path,
    apply_deepseek_base_url,
    error_payload,
    get_deepseek_api_key,
    load_json,
    resolve_project_path,
    save_json,
    to_relative,
)

try:
    from fastmcp import FastMCP
except Exception:
    from mcp.server.fastmcp import FastMCP

add_project_root_to_path()

import pdf_pipeline as pdf_module  # noqa: E402

apply_deepseek_base_url(pdf_module)

mcp = FastMCP("pdf")


def _slugify(value: str) -> str:
    import re

    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_") or "UNKNOWN"


def _build_renaming_plan_from_metadata(metadata_df: pd.DataFrame) -> Dict[str, Any]:
    """Generate deterministic renaming suggestions from metadata rows."""
    report_type_map = {
        "dre": "DRE",
        "mapa de producao": "MAPA_PRODUCAO",
        "mapa de producao/transformacao": "MAPA_TRANSFORMACAO",
        "custo operacional": "CUSTO_OPERACIONAL",
        "posicao financeira do estoque": "POSICAO_FINANCEIRA_ESTOQUE",
        "balancete": "BALANCETE",
        "extrato contabil": "EXTRATO_CONTABIL",
        "resultado bruto": "RESULTADO_BRUTO",
        "resumo de compras": "RESUMO_COMPRAS",
        "resumo de vendas": "RESUMO_VENDAS",
        "despesas financeiras": "DESPESAS_FINANCEIRAS",
        "irpj": "IRPJ_CSL",
        "receitas financeiras": "RECEITAS_FINANCEIRAS",
    }

    file_mapping: List[Dict[str, Any]] = []

    for _, row in metadata_df.iterrows():
        report_type = str(row.get("report_type", "")).strip()
        period = str(row.get("period", "")).strip()
        current_path = str(row.get("filepath", "")).strip()
        current_name = str(row.get("filename", "")).strip()
        suggested_name = str(row.get("file_name_suggestion", "")).strip()
        suggested_dir = str(row.get("directory_suggestion", "")).strip()

        normalized_type = "REPORTE"
        report_type_lower = report_type.lower()
        for key, value in report_type_map.items():
            if key in report_type_lower:
                normalized_type = value
                break

        normalized_period = _slugify(period) if period and period.lower() != "nan" else "PERIODO_DESCONHECIDO"

        if not suggested_name or suggested_name.lower() == "nan":
            suggested_name = "{}_{}_IBSCO.pdf".format(normalized_type, normalized_period)
        if not suggested_name.lower().endswith(".pdf"):
            suggested_name += ".pdf"

        if not suggested_dir or suggested_dir.lower() == "nan":
            if "dre" in report_type_lower:
                suggested_dir = "Financeiro/DRE/"
            elif "transformacao" in report_type_lower:
                suggested_dir = "Producao/Transformacao/"
            elif "producao" in report_type_lower:
                suggested_dir = "Producao/Mapas_de_Producao/"
            elif "custo" in report_type_lower:
                suggested_dir = "Financeiro/Custos_Operacionais/"
            elif "estoque" in report_type_lower:
                suggested_dir = "Financeiro/Estoque/"
            elif "vendas" in report_type_lower:
                suggested_dir = "Financeiro/Vendas/"
            elif "compras" in report_type_lower:
                suggested_dir = "Financeiro/Compras/"
            else:
                suggested_dir = "Financeiro/Outros/"

        if not suggested_dir.endswith("/"):
            suggested_dir += "/"

        file_mapping.append(
            {
                "old_path": current_path,
                "old_filename": current_name,
                "new_path": "{}{}".format(suggested_dir, suggested_name),
                "new_filename": suggested_name,
                "new_directory": suggested_dir,
                "report_type": report_type,
                "period": period,
                "reason": "Standardization based on report metadata",
            }
        )

    return {
        "naming_convention": "[ReportType]_[Period]_IBSCO.pdf",
        "directory_structure": sorted({entry["new_directory"] for entry in file_mapping}),
        "file_mapping": file_mapping,
        "summary": {
            "total_files": len(file_mapping),
            "unique_directories": len({entry["new_directory"] for entry in file_mapping}),
        },
    }


@mcp.tool(name="pdf_scan_files")
def pdf_scan_files(
    input_root: str = "IBSCO",
    extensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Scan directory tree and return PDF file index metadata."""
    try:
        resolved_input = resolve_project_path(input_root)
        resolved_extensions = extensions or [".pdf"]
        files = pdf_module.scan_pdf_files(str(resolved_input), resolved_extensions)
        return {
            "ok": True,
            "input_root": to_relative(resolved_input),
            "count": len(files),
            "files": files,
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_extract_text")
def pdf_extract_text(pdf_path: str, max_pages: int = 50) -> Dict[str, Any]:
    """Extract text and table structures from a PDF file."""
    try:
        resolved_pdf = resolve_project_path(pdf_path)
        extraction = pdf_module.extract_text_from_pdf(str(resolved_pdf), max_pages=max_pages)
        return {
            "ok": extraction.get("error") is None,
            "pdf_path": to_relative(resolved_pdf),
            "extraction": extraction,
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_analyze_pdf")
def pdf_analyze_pdf(
    pdf_path: str,
    max_pages: int = 50,
    include_llm: bool = True,
) -> Dict[str, Any]:
    """Extract a PDF and optionally run DeepSeek analysis."""
    try:
        resolved_pdf = resolve_project_path(pdf_path)
        extraction = pdf_module.extract_text_from_pdf(str(resolved_pdf), max_pages=max_pages)

        response: Dict[str, Any] = {
            "ok": extraction.get("error") is None,
            "pdf_path": to_relative(resolved_pdf),
            "extraction": extraction,
            "llm_enabled": include_llm,
        }

        if include_llm and extraction.get("error") is None:
            api_key = get_deepseek_api_key()
            analyzer = pdf_module.DeepSeekPDFAnalyzer(api_key=api_key)
            analysis = analyzer.analyze_financial_report(extraction)
            response["analysis"] = analysis
            response["ok"] = "error" not in analysis

        return response
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_convert_analysis_directory_to_csv")
def pdf_convert_analysis_directory_to_csv(
    analysis_dir: str,
    output_dir: str,
) -> Dict[str, Any]:
    """Convert a directory of *_analysis.json files into CSV outputs."""
    try:
        resolved_analysis_dir = resolve_project_path(analysis_dir)
        resolved_output_dir = resolve_project_path(output_dir)
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

        analysis_results: Dict[str, Dict[str, Any]] = {}
        analysis_files = sorted(resolved_analysis_dir.glob("*_analysis.json"))

        for analysis_file in analysis_files:
            payload = load_json(analysis_file)
            key = payload.get("llm_analysis_metadata", {}).get("original_filename")
            if not key:
                key = analysis_file.stem.replace("_analysis", "")
            analysis_results[key] = payload

        csv_files = pdf_module.convert_to_csv(analysis_results, str(resolved_output_dir))

        return {
            "ok": True,
            "analysis_dir": to_relative(resolved_analysis_dir),
            "output_dir": to_relative(resolved_output_dir),
            "analysis_files": [to_relative(path) for path in analysis_files],
            "csv_files": {name: to_relative(path) for name, path in csv_files.items()},
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_generate_renaming_plan_from_csv")
def pdf_generate_renaming_plan_from_csv(
    metadata_csv_path: str,
    output_plan_path: str = "pdf_processed_results/renaming_plan_from_mcp.json",
) -> Dict[str, Any]:
    """Generate deterministic renaming plan from metadata CSV."""
    try:
        resolved_metadata_csv = resolve_project_path(metadata_csv_path)
        resolved_output_plan = resolve_project_path(output_plan_path)

        metadata_df = pd.read_csv(resolved_metadata_csv, encoding="utf-8-sig")
        plan = _build_renaming_plan_from_metadata(metadata_df)
        save_json(resolved_output_plan, plan)

        return {
            "ok": True,
            "metadata_csv": to_relative(resolved_metadata_csv),
            "output_plan": to_relative(resolved_output_plan),
            "summary": plan["summary"],
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_apply_renaming_plan")
def pdf_apply_renaming_plan(
    renaming_plan_path: str,
    input_root: str = "IBSCO",
    dry_run: bool = True,
    confirm: bool = False,
) -> Dict[str, Any]:
    """Apply file renaming plan. Destructive mode requires confirm=true."""
    try:
        if not dry_run and not confirm:
            raise ValueError("Destructive rename requires confirm=true")

        resolved_plan = resolve_project_path(renaming_plan_path)
        resolved_input_root = resolve_project_path(input_root)

        plan = load_json(resolved_plan)
        results = pdf_module.apply_file_renaming(
            renaming_plan=plan,
            workspace_dir=str(resolved_input_root),
            dry_run=dry_run,
        )

        return {
            "ok": True,
            "renaming_plan_path": to_relative(resolved_plan),
            "input_root": to_relative(resolved_input_root),
            "dry_run": dry_run,
            "results": results,
        }
    except Exception as error:
        return error_payload(error)


@mcp.tool(name="pdf_run_pipeline")
def pdf_run_pipeline(
    input_root: str = "IBSCO",
    output_root: str = "pdf_processed_results",
    dry_run: bool = True,
    max_pages_per_pdf: int = 50,
    log_level: str = "INFO",
) -> Dict[str, Any]:
    """Execute the full PDF processing pipeline."""
    try:
        resolved_input = resolve_project_path(input_root)
        resolved_output = resolve_project_path(output_root)
        resolved_output.mkdir(parents=True, exist_ok=True)

        config = dict(pdf_module.DEFAULT_CONFIG)
        config["input_root"] = str(resolved_input)
        config["output_root"] = str(resolved_output)
        config["dry_run"] = dry_run
        config["max_pages_per_pdf"] = max_pages_per_pdf
        config["log_level"] = log_level

        if os.getenv("DEEPSEEK_API_KEY"):
            config["llm_enabled"] = True
        else:
            config["llm_enabled"] = False

        results = pdf_module.run_pipeline(config)

        return {
            "ok": results.get("status") == "completed",
            "input_root": to_relative(resolved_input),
            "output_root": to_relative(resolved_output),
            "dry_run": dry_run,
            "results": results,
        }
    except Exception as error:
        return error_payload(error)


if __name__ == "__main__":
    import os
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8126"))

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in ("sse", "streamable-http"):
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        print(f"Unknown transport: {transport}. Using stdio.", file=__import__('sys').stderr)
        mcp.run(transport="stdio")
