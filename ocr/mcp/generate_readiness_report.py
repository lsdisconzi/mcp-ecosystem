#!/usr/bin/env python3
"""Generate MCP readiness report with endpoint coverage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

REQUIRED_ARTIFACTS = [
    ROOT / "README.md",
    ROOT / "MCP_ARCHITECTURE.md",
    ROOT / "mcpServers.example.json",
    ROOT / "servers" / "ocr_server.py",
    ROOT / "servers" / "pdf_server.py",
    ROOT / "generate_readiness_report.py",
]

DISCOVERED_ENDPOINTS: List[Dict[str, str]] = [
    {
        "endpoint": "ocr_with_llm_enhancement.get_image_files",
        "scope": "in-scope",
        "mapped_tool": "ocr_list_images",
    },
    {
        "endpoint": "ocr_with_llm_enhancement.process_image_with_ocr",
        "scope": "in-scope",
        "mapped_tool": "ocr_process_image",
    },
    {
        "endpoint": "ocr_with_llm_enhancement.DeepSeekClient.refine_ocr_results",
        "scope": "in-scope",
        "mapped_tool": "ocr_process_image",
    },
    {
        "endpoint": "ocr_with_llm_enhancement.DeepSeekClient.compare_and_validate",
        "scope": "in-scope",
        "mapped_tool": "ocr_compare_results",
    },
    {
        "endpoint": "ocr_with_llm_enhancement.process_batch",
        "scope": "in-scope",
        "mapped_tool": "ocr_run_batch",
    },
    {
        "endpoint": "pdf_pipeline.scan_pdf_files",
        "scope": "in-scope",
        "mapped_tool": "pdf_scan_files",
    },
    {
        "endpoint": "pdf_pipeline.extract_text_from_pdf",
        "scope": "in-scope",
        "mapped_tool": "pdf_extract_text",
    },
    {
        "endpoint": "pdf_pipeline.DeepSeekPDFAnalyzer.analyze_financial_report",
        "scope": "in-scope",
        "mapped_tool": "pdf_analyze_pdf",
    },
    {
        "endpoint": "pdf_pipeline.convert_to_csv",
        "scope": "in-scope",
        "mapped_tool": "pdf_convert_analysis_directory_to_csv",
    },
    {
        "endpoint": "pdf_pipeline.apply_file_renaming",
        "scope": "in-scope",
        "mapped_tool": "pdf_apply_renaming_plan",
    },
    {
        "endpoint": "pdf_pipeline.run_pipeline",
        "scope": "in-scope",
        "mapped_tool": "pdf_run_pipeline",
    },
    {
        "endpoint": "generate_renaming_plan.generate_renaming_plan_from_csv",
        "scope": "in-scope",
        "mapped_tool": "pdf_generate_renaming_plan_from_csv",
    },
    {
        "endpoint": "process_new_files.process_new_files",
        "scope": "excluded",
        "mapped_tool": "",
    },
    {
        "endpoint": "pdf_line_reader.parse_report",
        "scope": "excluded",
        "mapped_tool": "",
    },
    {
        "endpoint": "pdf_line_reader_2.parse_transactions",
        "scope": "excluded",
        "mapped_tool": "",
    },
    {
        "endpoint": "refined_converter.ReportConverter",
        "scope": "excluded",
        "mapped_tool": "",
    },
    {
        "endpoint": "run_demo.main",
        "scope": "excluded",
        "mapped_tool": "",
    },
]


def generate_report() -> Dict[str, object]:
    discovered_in_scope = [x for x in DISCOVERED_ENDPOINTS if x["scope"] == "in-scope"]
    mapped = [x for x in discovered_in_scope if x["mapped_tool"]]
    missing = [x for x in discovered_in_scope if not x["mapped_tool"]]

    artifacts = {
        str(path.relative_to(PROJECT_ROOT)): path.exists() for path in REQUIRED_ARTIFACTS
    }

    coverage = 0.0
    if discovered_in_scope:
        coverage = round((len(mapped) / len(discovered_in_scope)) * 100, 2)

    ready = len(missing) == 0 and all(artifacts.values())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "state": "ready" if ready else "not-ready",
        "coverage": {
            "discovered_in_scope_endpoints": len(discovered_in_scope),
            "mapped_endpoints": len(mapped),
            "missing_endpoints": len(missing),
            "coverage_percent": coverage,
        },
        "discovered_endpoints": DISCOVERED_ENDPOINTS,
        "mapped_endpoints": mapped,
        "missing_endpoints": missing,
        "required_artifacts": artifacts,
    }


def write_outputs(report: Dict[str, object]) -> None:
    json_path = ROOT / "readiness_report.json"
    md_path = ROOT / "readiness_report.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# MCP Readiness Report")
    lines.append("")
    lines.append("- Generated at: {}".format(report["generated_at"]))
    lines.append("- State: **{}**".format(report["state"]))
    lines.append("- In-scope endpoints discovered: {}".format(report["coverage"]["discovered_in_scope_endpoints"]))
    lines.append("- Endpoints mapped: {}".format(report["coverage"]["mapped_endpoints"]))
    lines.append("- Missing in-scope endpoints: {}".format(report["coverage"]["missing_endpoints"]))
    lines.append("- Coverage: {}%".format(report["coverage"]["coverage_percent"]))
    lines.append("")

    lines.append("## Required Artifacts")
    for artifact, present in report["required_artifacts"].items():
        status = "OK" if present else "MISSING"
        lines.append("- {}: {}".format(artifact, status))
    lines.append("")

    lines.append("## Endpoint Mapping")
    for endpoint in report["mapped_endpoints"]:
        lines.append(
            "- {} -> {}".format(endpoint["endpoint"], endpoint["mapped_tool"])
        )
    lines.append("")

    lines.append("## Excluded Endpoints")
    for endpoint in [x for x in report["discovered_endpoints"] if x["scope"] == "excluded"]:
        lines.append("- {}".format(endpoint["endpoint"]))

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    report_payload = generate_report()
    write_outputs(report_payload)
    print("Readiness report generated:")
    print("- {}".format(ROOT / "readiness_report.json"))
    print("- {}".format(ROOT / "readiness_report.md"))
