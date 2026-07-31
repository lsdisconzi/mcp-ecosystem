#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image‑Based Report Processing Pipeline (Final Corrected)

- Max tokens: 8192
- OCR text truncated to 3000 chars
- Strict JSON‑only prompt
- Retry logic
- Extracts JSON from reasoning if content empty
"""

import os
import sys
import json
import csv
import argparse
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import re
import time

from PIL import Image
import pytesseract

try:
    import pyheif
    HAS_HEIC = True
except ImportError:
    HAS_HEIC = False

import pandas as pd

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEFAULT_CONFIG = {
    "input_root": "./IBSCO",
    "output_root": "./pdf_processed_results",
    "working_dir": "./image_processing_workspace",
    "supported_extensions": [".heic", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
    "llm_provider": os.getenv("LLM_PROVIDER", "ollama"),       # deepseek, ollama, openai
    "llm_model": os.getenv("LLM_MODEL", "llama3.1"),          # use a text model
    "ollama_model": os.getenv("OLLAMA_MODEL", "llama3.1"),
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    "llm_temperature": 0.1,
    "llm_max_tokens": 8192,                                   # increased!
    "ocr_language": "por+eng",
    "csv_encoding": "utf-8-sig",
    "dry_run": False,
    "log_level": "INFO",
    "max_ocr_chars": 3000                                     # truncate OCR text
}

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def setup_logging(output_dir: str, log_level: str = "INFO") -> logging.Logger:
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"pipeline_{timestamp}.log")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding='utf-8')]
    )
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    return logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def calculate_file_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def clean_ocr_text(text: str) -> str:
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
    return text.strip()

def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cutoff = text[:max_chars].rfind('.')
    if cutoff == -1:
        cutoff = max_chars
    return text[:cutoff] + " [...]"

# ----------------------------------------------------------------------
# File scanning & OCR
# ----------------------------------------------------------------------
def scan_image_files(root_dir: str, extensions: List[str]) -> List[Dict[str, Any]]:
    file_index = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if any(filename.lower().endswith(ext) for ext in extensions):
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, root_dir)
                stat = os.stat(full_path)
                try:
                    with Image.open(full_path) as img:
                        width, height = img.size
                        fmt = img.format
                except Exception:
                    width, height, fmt = None, None, None
                file_index.append({
                    "full_path": full_path,
                    "relative_path": rel_path,
                    "filename": filename,
                    "directory": dirpath,
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_hash": calculate_file_hash(full_path),
                    "file_type": "Image",
                    "image_format": fmt,
                    "image_width": width,
                    "image_height": height,
                    "status": "pending"
                })
    return sorted(file_index, key=lambda x: x["relative_path"])

def save_index(index: List[Dict[str, Any]], output_path: str) -> None:
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def extract_text_from_image(image_path: str, ocr_lang: str = "por+eng") -> Dict[str, Any]:
    result = {
        "filename": os.path.basename(image_path),
        "filepath": image_path,
        "extraction_time": datetime.now().isoformat(),
        "total_pages": 1,
        "pages": [],
        "metadata": {},
        "text_summary": "",
        "page_errors": [],
        "error": None
    }
    try:
        ext = os.path.splitext(image_path)[1].lower()
        if ext == '.heic' and HAS_HEIC:
            heif_file = pyheif.read(image_path)
            image = Image.frombytes(
                heif_file.mode, heif_file.size, heif_file.data,
                "raw", heif_file.mode, heif_file.stride,
            )
        else:
            image = Image.open(image_path)

        ocr_text = pytesseract.image_to_string(image, lang=ocr_lang)
        ocr_text = clean_ocr_text(ocr_text)

        page_info = {
            "page_number": 1,
            "text": ocr_text,
            "tables_count": 0,
            "tables": []
        }
        result["pages"].append(page_info)

        stat = os.stat(image_path)
        result["metadata"] = {
            "creation_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modification_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "image_format": image.format,
            "width": image.width,
            "height": image.height,
        }
        result["text_summary"] = ocr_text[:5000]
    except Exception as e:
        result["error"] = str(e)
        logging.error(f"OCR error on {image_path}: {e}")
    return result

# ----------------------------------------------------------------------
# LLM Analyzer (with retry and reasoning fallback)
# ----------------------------------------------------------------------
class LLMAnalyzer:
    def __init__(self, config: Dict[str, Any]):
        self.provider = config.get("llm_provider", "ollama").lower()
        self.temperature = config.get("llm_temperature", 0.1)
        self.max_tokens = config.get("llm_max_tokens", 8192)
        self.client = None

        if self.provider == "ollama":
            self.model = config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])
            base_url = config.get("ollama_base_url", DEFAULT_CONFIG["ollama_base_url"])
            self.client = OpenAI(api_key="ollama", base_url=base_url)
            self.supports_json_mode = False
        elif self.provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("DeepSeek API key required. Set DEEPSEEK_API_KEY.")
            self.model = config.get("llm_model", "deepseek-v4")   # use non‑reasoning model if possible
            self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            self.supports_json_mode = True
        elif self.provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OpenAI API key required. Set OPENAI_API_KEY.")
            self.model = config.get("llm_model", "gpt-4o-mini")
            self.client = OpenAI(api_key=api_key)
            self.supports_json_mode = True
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        self.max_ocr_chars = config.get("max_ocr_chars", 3000)

    def _chat_completion(self, messages: List[Dict[str, str]], use_json: bool = True) -> Dict[str, Any]:
        if self.client:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if use_json and self.supports_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
            return response.model_dump() if hasattr(response, 'model_dump') else response
        else:
            raise NotImplementedError("OpenAI client required")

    def _parse_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None

    def _create_analysis_prompt(self, extraction: Dict[str, Any]) -> str:
        filename = extraction.get("filename", "Unknown")
        ocr_text = extraction.get("text_summary", "")
        ocr_text = truncate_text(ocr_text, self.max_ocr_chars)

        prompt = f"""
        Analyze the following text extracted from an image (OCR may contain errors). 
        The document is likely a report (medical, financial, invoice, etc.).
        Extract the following information and return a JSON object with these fields:

        {{
            "report_metadata": {{
                "report_type": "string (e.g., BMD Report, Invoice, DRE, etc.)",
                "period_covered": "string (date or range if mentioned)",
                "company_name": "string (if any)",
                "patient": "string (patient name if medical)",
                "report_generation_date": "string (if any)",
                "confidence_score": 0.0 (optional)
            }},
            "financial_categories": ["list of categories found (if applicable)"],
            "key_metrics": [
                {{"metric_name": "string", "value": "string", "unit": "string", "period": "string"}}
            ],
            "tabular_data_detected": true/false,
            "table_structures": [
                {{
                    "headers": ["col1", "col2", ...],
                    "sample_rows": [["val1", "val2", ...], ...]
                }}
            ],
            "file_name_suggestion": "suggested filename (e.g., BMD_Report_2026-05-08_XMED.pdf)",
            "directory_suggestion": "suggested directory (e.g., Medical/Reports/)",
            "content_summary": "brief description of document content"
        }}

        If a field is not found, use empty string or empty list. Do not invent data.
        Output ONLY the JSON object, no other text (including no reasoning or explanation).

        FILENAME: {filename}
        OCR TEXT:
        {ocr_text}
        """
        return prompt

    def analyze_report(self, extraction_result: Dict[str, Any]) -> Dict[str, Any]:
        max_retries = 2
        for attempt in range(max_retries + 1):
            prompt = self._create_analysis_prompt(extraction_result)
            messages = [
                {"role": "system", "content": "You are a data extraction assistant. Output **only** a valid JSON object. Do not include any extra text, explanations, reasoning, or markdown."},
                {"role": "user", "content": prompt}
            ]
            if attempt > 0:
                self.max_tokens = 8192  # ensure maximum on retry
            try:
                raw = self._chat_completion(messages, use_json=self.supports_json_mode)
                content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                reasoning = raw.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")

                parsed = self._parse_json_from_text(content)
                if parsed:
                    parsed["llm_analysis_metadata"] = {
                        "model": self.model,
                        "provider": self.provider,
                        "analysis_time": datetime.now().isoformat(),
                        "attempt": attempt + 1,
                        "original_filename": extraction_result.get("filename", "unknown")
                    }
                    return parsed

                # Fallback: try to extract JSON from reasoning
                if not content and reasoning:
                    logging.warning("Content empty, attempting to parse reasoning.")
                    parsed = self._parse_json_from_text(reasoning)
                    if parsed:
                        parsed["llm_analysis_metadata"] = {
                            "model": self.model,
                            "provider": self.provider,
                            "analysis_time": datetime.now().isoformat(),
                            "attempt": attempt + 1,
                            "original_filename": extraction_result.get("filename", "unknown"),
                            "extracted_from": "reasoning"
                        }
                        return parsed

                logging.warning(f"Attempt {attempt+1} returned non‑JSON content. Snippet: {content[:200]}")
            except Exception as e:
                logging.error(f"LLM call failed: {e}")
            time.sleep(2)

        return {
            "error": "Analysis failed after retries",
            "raw_ocr_summary": extraction_result.get("text_summary", "")[:500],
            "llm_analysis_metadata": {
                "model": self.model,
                "provider": self.provider,
                "analysis_time": datetime.now().isoformat(),
                "failed": True,
                "original_filename": extraction_result.get("filename", "unknown")
            }
        }

    def suggest_file_renaming(self, file_index: List[Dict[str, Any]],
                              analysis_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        try:
            renaming_data = []
            for item in file_index:
                filename = item["filename"]
                rel_path = item["relative_path"]
                analysis = analysis_results.get(item["full_path"], {})
                renaming_data.append({
                    "current_filename": filename,
                    "current_directory": os.path.dirname(rel_path),
                    "analysis": analysis.get("report_metadata", {}),
                    "file_name_suggestion": analysis.get("file_name_suggestion", ""),
                    "directory_suggestion": analysis.get("directory_suggestion", "")
                })
            prompt = f"""
            Given the following file analysis data, suggest a renaming and directory structure plan.
            For each file, propose a new path (including directory) that is logical.
            Return JSON with structure:
            {{
                "naming_convention": "explanation",
                "directory_structure": ["list of directories"],
                "file_mapping": [
                    {{"old_path": "relative/path/current.jpg", "new_path": "new/dir/newname.pdf", "reason": "why"}}
                ]
            }}
            If a file_name_suggestion is given in analysis, use it as basename (replace extension with .pdf).
            Data:
            {json.dumps(renaming_data, ensure_ascii=False, indent=2)}
            """
            messages = [
                {"role": "system", "content": "You are a file organization expert. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ]
            raw = self._chat_completion(messages, use_json=self.supports_json_mode)
            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = self._parse_json_from_text(content)
            if parsed:
                return parsed
            reasoning = raw.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
            if reasoning:
                parsed = self._parse_json_from_text(reasoning)
                if parsed:
                    return parsed
            return {"error": "No valid JSON", "file_mapping": []}
        except Exception as e:
            logging.error(f"Renaming suggestion failed: {e}")
            return {"error": str(e), "file_mapping": []}

# ----------------------------------------------------------------------
# CSV Conversion (unchanged)
# ----------------------------------------------------------------------
def convert_to_csv(analysis_results: Dict[str, Dict[str, Any]], output_dir: str) -> Dict[str, str]:
    csv_files = {}
    metadata_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            meta = analysis.get("report_metadata", {})
            row = {
                "filename": os.path.basename(filepath),
                "filepath": filepath,
                "report_type": meta.get("report_type", ""),
                "period": meta.get("period_covered", ""),
                "company": meta.get("company_name", ""),
                "patient": meta.get("patient", ""),
                "generation_date": meta.get("report_generation_date", ""),
                "confidence_score": meta.get("confidence_score", 0),
                "financial_categories": "; ".join(analysis.get("financial_categories", [])),
                "file_name_suggestion": analysis.get("file_name_suggestion", ""),
                "directory_suggestion": analysis.get("directory_suggestion", ""),
                "analysis_timestamp": analysis.get("llm_analysis_metadata", {}).get("analysis_time", "")
            }
            metadata_rows.append(row)
    if metadata_rows:
        meta_csv = os.path.join(output_dir, "report_metadata.csv")
        pd.DataFrame(metadata_rows).to_csv(meta_csv, index=False, encoding='utf-8-sig')
        csv_files["metadata"] = meta_csv

    # Metrics
    metrics_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            fname = os.path.basename(filepath)
            for m in analysis.get("key_metrics", []):
                metrics_rows.append({
                    "filename": fname,
                    "filepath": filepath,
                    "metric_name": m.get("metric_name", ""),
                    "value": m.get("value", ""),
                    "unit": m.get("unit", ""),
                    "period": m.get("period", ""),
                    "report_period": analysis.get("report_metadata", {}).get("period_covered", "")
                })
    if metrics_rows:
        metrics_csv = os.path.join(output_dir, "metrics.csv")
        pd.DataFrame(metrics_rows).to_csv(metrics_csv, index=False, encoding='utf-8-sig')
        csv_files["metrics"] = metrics_csv

    # Tables
    table_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            fname = os.path.basename(filepath)
            for ti, tbl in enumerate(analysis.get("table_structures", [])):
                headers = tbl.get("headers", [])
                samples = tbl.get("sample_rows", [])
                for si, row in enumerate(samples[:5]):
                    d = {"filename": fname, "filepath": filepath, "table_index": ti}
                    for ci, col in enumerate(headers):
                        val = row[ci] if ci < len(row) else ""
                        d[f"col_{ci}_{col}"] = val
                    table_rows.append(d)
    if table_rows:
        tbl_csv = os.path.join(output_dir, "tables.csv")
        pd.DataFrame(table_rows).to_csv(tbl_csv, index=False, encoding='utf-8-sig')
        csv_files["tables"] = tbl_csv

    return csv_files

# ----------------------------------------------------------------------
# File renaming (with fallback)
# ----------------------------------------------------------------------
def apply_file_renaming(file_index: List[Dict[str, Any]], renaming_plan: Dict[str, Any],
                         workspace_dir: str, dry_run: bool = False) -> Dict[str, Any]:
    results = {"total_files": 0, "renamed": 0, "errors": [], "operations": []}
    file_mapping = renaming_plan.get("file_mapping", [])
    results["total_files"] = len(file_mapping)
    for mapping in file_mapping:
        old_rel = mapping.get("old_path")
        new_rel = mapping.get("new_path")
        if not old_rel or not new_rel:
            continue
        old_abs = os.path.join(workspace_dir, old_rel)
        new_abs = os.path.join(workspace_dir, new_rel)
        op = {"old_path": old_rel, "new_path": new_rel, "status": "pending"}
        try:
            if not dry_run:
                os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                if os.path.exists(old_abs):
                    os.rename(old_abs, new_abs)
                    old_dir = os.path.dirname(old_abs)
                    if os.path.exists(old_dir) and not os.listdir(old_dir):
                        os.rmdir(old_dir)
                    op["status"] = "completed"
                    results["renamed"] += 1
                else:
                    op["status"] = "source_not_found"
                    results["errors"].append(f"Source not found: {old_abs}")
            else:
                op["status"] = "dry_run"
                results["renamed"] += 1
        except Exception as e:
            op["status"] = f"error: {e}"
            results["errors"].append(str(e))
        results["operations"].append(op)
    return results

# ----------------------------------------------------------------------
# Main Pipeline
# ----------------------------------------------------------------------
def run_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    logger = setup_logging(config["output_root"], config["log_level"])
    workspace = os.path.join(config["output_root"], config["working_dir"])
    os.makedirs(workspace, exist_ok=True)

    config_path = os.path.join(workspace, "pipeline_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    logger.info("="*80)
    logger.info("Image‑Based Report Processing Pipeline (Final Corrected)")
    logger.info(f"Input: {config['input_root']}  Output: {workspace}")
    logger.info("="*80)

    pipeline = {
        "start_time": datetime.now().isoformat(),
        "steps": {},
        "status": "running"
    }

    # Step 1: Scan
    logger.info("Step 1: Scanning images...")
    file_index = scan_image_files(config["input_root"], config["supported_extensions"])
    index_path = os.path.join(workspace, "file_index.json")
    save_index(file_index, index_path)
    logger.info(f"Found {len(file_index)} images")
    pipeline["steps"]["scanning"] = {"status": "completed", "files": len(file_index)}

    if not file_index:
        logger.warning("No images found. Exiting.")
        pipeline["status"] = "completed"
        pipeline["end_time"] = datetime.now().isoformat()
        return pipeline

    # Step 2: OCR
    logger.info("Step 2: OCR extraction...")
    extraction_dir = os.path.join(workspace, "extractions")
    os.makedirs(extraction_dir, exist_ok=True)
    extraction_results = {}
    for i, fi in enumerate(file_index, 1):
        logger.info(f"OCR {i}/{len(file_index)}: {fi['filename']}")
        extr = extract_text_from_image(fi["full_path"], ocr_lang=config["ocr_language"])
        extraction_results[fi["full_path"]] = extr
        ext_path = os.path.join(extraction_dir, f"{fi['filename']}_extraction.json")
        with open(ext_path, 'w', encoding='utf-8') as f:
            json.dump(extr, f, ensure_ascii=False, indent=2)
        fi["extraction_path"] = ext_path
        fi["extraction_status"] = "error" if extr.get("error") else "completed"
    save_index(file_index, index_path)
    pipeline["steps"]["extraction"] = {"status": "completed", "processed": len(extraction_results)}

    # Step 3: LLM Analysis
    analysis_results = {}
    llm_provider = config.get("llm_provider", "none").lower()
    if llm_provider != "none":
        logger.info("Step 3: LLM analysis using %s...", llm_provider)
        analysis_dir = os.path.join(workspace, "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        try:
            analyzer = LLMAnalyzer(config)
        except Exception as e:
            logger.error(f"LLM init failed: {e}")
            pipeline["steps"]["llm_analysis"] = {"status": "failed", "error": str(e)}
        else:
            for i, (path, extr) in enumerate(extraction_results.items(), 1):
                if extr.get("error"):
                    logger.warning(f"Skipping {os.path.basename(path)} due to OCR error")
                    continue
                logger.info(f"Analyzing {i}/{len(extraction_results)}: {os.path.basename(path)}")
                analysis = analyzer.analyze_report(extr)
                analysis_results[path] = analysis
                analysis_path = os.path.join(analysis_dir, f"{os.path.basename(path)}_analysis.json")
                with open(analysis_path, 'w', encoding='utf-8') as f:
                    json.dump(analysis, f, ensure_ascii=False, indent=2)
                time.sleep(1)
            pipeline["steps"]["llm_analysis"] = {"status": "completed", "analyzed": len(analysis_results)}
    else:
        logger.info("Step 3: Skipping LLM analysis")
        pipeline["steps"]["llm_analysis"] = {"status": "skipped"}

    # Step 4: CSV
    logger.info("Step 4: Converting to CSV...")
    csv_dir = os.path.join(workspace, "csv_output")
    os.makedirs(csv_dir, exist_ok=True)
    csv_files = convert_to_csv(analysis_results, csv_dir)
    pipeline["steps"]["csv_conversion"] = {"status": "completed", "files": list(csv_files.keys())}
    logger.info(f"CSV files: {list(csv_files.keys())}")

    # Step 5: File renaming
    if llm_provider != "none" and analysis_results:
        logger.info("Step 5: Planning file renaming...")
        try:
            analyzer = LLMAnalyzer(config)
            renaming_plan = analyzer.suggest_file_renaming(file_index, analysis_results)
        except Exception as e:
            logger.error(f"Renaming plan failed: {e}")
            renaming_plan = {"error": str(e), "file_mapping": []}

        if "error" in renaming_plan or not renaming_plan.get("file_mapping"):
            logger.warning("LLM renaming plan failed; using fallback.")
            fallback_mapping = []
            for item in file_index:
                old_rel = item["relative_path"]
                base = os.path.splitext(item["filename"])[0]
                analysis = analysis_results.get(item["full_path"], {})
                suggested_name = analysis.get("file_name_suggestion", "")
                suggested_dir = analysis.get("directory_suggestion", "Misc/")
                if suggested_name:
                    new_name = suggested_name
                else:
                    new_name = f"{base}.pdf"
                new_rel = os.path.join(suggested_dir, new_name)
                fallback_mapping.append({
                    "old_path": old_rel,
                    "new_path": new_rel,
                    "reason": "fallback (LLM failed)"
                })
            renaming_plan = {"file_mapping": fallback_mapping}

        plan_path = os.path.join(workspace, "renaming_plan.json")
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(renaming_plan, f, ensure_ascii=False, indent=2)

        if not config["dry_run"]:
            logger.info("Applying renaming...")
            rename_results = apply_file_renaming(file_index, renaming_plan, config["input_root"], dry_run=False)
            res_path = os.path.join(workspace, "renaming_results.json")
            with open(res_path, 'w', encoding='utf-8') as f:
                json.dump(rename_results, f, ensure_ascii=False, indent=2)
            pipeline["steps"]["file_reorganization"] = {
                "status": "completed",
                "renamed": rename_results["renamed"],
                "errors": len(rename_results["errors"])
            }
            logger.info(f"Renamed {rename_results['renamed']} files")
        else:
            logger.info("Dry run: renaming not applied")
            pipeline["steps"]["file_reorganization"] = {"status": "dry_run"}
    else:
        logger.info("Step 5: Skipping file renaming")
        pipeline["steps"]["file_reorganization"] = {"status": "skipped"}

    # Step 6: Summary
    logger.info("Step 6: Generating summary...")
    summary = {
        "pipeline_execution": {
            "start_time": pipeline["start_time"],
            "end_time": datetime.now().isoformat(),
            "total_files": len(file_index)
        },
        "file_statistics": {
            "total_images": len(file_index),
            "successful_ocr": sum(1 for e in extraction_results.values() if not e.get("error")),
            "successful_analyses": sum(1 for a in analysis_results.values() if "error" not in a)
        },
        "outputs": {
            "workspace": workspace,
            "index_file": index_path,
            "extractions": extraction_dir,
            "analysis": os.path.join(workspace, "analysis") if analysis_results else None,
            "csv_files": csv_dir
        }
    }
    summary_path = os.path.join(workspace, "pipeline_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    human_summary = f"""
    IMAGE PROCESSING PIPELINE SUMMARY
    =================================
    Time: {summary['pipeline_execution']['start_time']} – {summary['pipeline_execution']['end_time']}
    Images: {summary['file_statistics']['total_images']}
    Successful OCR: {summary['file_statistics']['successful_ocr']}
    Successful Analyses: {summary['file_statistics']['successful_analyses']}
    Outputs: {summary['outputs']}
    """
    with open(os.path.join(workspace, "SUMMARY.txt"), 'w', encoding='utf-8') as f:
        f.write(human_summary)

    pipeline["summary"] = summary
    pipeline["status"] = "completed"
    logger.info("Pipeline completed.")
    return pipeline

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Image‑Based Report Processing Pipeline (Final)")
    parser.add_argument("--input", "-i", default="./IBSCO")
    parser.add_argument("--output", "-o", default="./pdf_processed_results")
    parser.add_argument("--llm-provider", choices=["deepseek", "ollama", "openai", "none"])
    parser.add_argument("--llm-model", help="LLM model name (e.g., llama3.1, deepseek-v4)")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max tokens for LLM output")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--config", "-c", help="JSON config file")
    parser.add_argument("--log-level", choices=["DEBUG","INFO","WARNING","ERROR"], default="INFO")
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            config.update(json.load(f))

    config["input_root"] = args.input
    config["output_root"] = args.output
    config["dry_run"] = args.dry_run
    config["log_level"] = args.log_level
    if args.llm_provider:
        config["llm_provider"] = args.llm_provider
    if args.llm_model:
        config["llm_model"] = args.llm_model
    config["llm_max_tokens"] = args.max_tokens

    results = run_pipeline(config)
    sys.exit(0 if results.get("status") == "completed" else 1)

if __name__ == "__main__":
    main()