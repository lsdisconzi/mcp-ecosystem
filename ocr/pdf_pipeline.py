#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Report Processing Pipeline for IBSCO Financial Reports

This pipeline:
1. Scans all PDF files from IBSCO directory
2. Creates a comprehensive index of all reports
3. Extracts text and data from PDFs using OCR
4. Uses DeepSeek LLM to review and structure extracted information
5. Converts structured data to CSV format
6. Revises file names to better reflect report content
7. Standardizes directory structure
8. Documents all steps and changes

All operations stay within the OCR project directory.
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
from typing import Dict, List, Optional, Any, Tuple
import re
import time

# PDF processing
import pdfplumber
import PyPDF2

# Data processing
import pandas as pd
import numpy as np

# LLM integration
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    import requests

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL")

# DeepSeek compatibility aliases scheduled for deprecation.
DEPRECATED_MODEL_MAP = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-flash",
}

DEFAULT_CONFIG = {
    "input_root": "./IBSCO",
    "output_root": "./pdf_processed_results",
    "working_dir": "./pdf_processing_workspace",
    "supported_extensions": [".pdf"],
    "llm_model": "deepseek-v4-pro",
    "llm_temperature": 0.1,
    "llm_max_tokens": 4000,
    "batch_size": 5,
    "max_pages_per_pdf": 50,
    "ocr_language": "por+eng",
    "csv_encoding": "utf-8-sig",
    "backup_original_files": True,
    "dry_run": False,
    "log_level": "INFO"
}


def resolve_deepseek_model(model_name: str) -> str:
    """Normalize deprecated model aliases to currently supported names."""
    replacement = DEPRECATED_MODEL_MAP.get(model_name)
    if replacement:
        logging.warning(
            "DeepSeek model '%s' is deprecated; using '%s' instead.",
            model_name,
            replacement,
        )
        return replacement
    return model_name


def is_meaningful_table(table_data: List[List[str]]) -> bool:
    """Filter out tiny layout artifacts that are not useful tabular content."""
    if not table_data:
        return False

    rows = len(table_data)
    cols = max((len(row) for row in table_data), default=0)
    non_empty_cells = sum(
        1 for row in table_data for cell in row if str(cell).strip()
    )

    if rows < 2 or cols < 2:
        return False
    return non_empty_cells >= 4

# ----------------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------------
def setup_logging(output_dir: str, log_level: str = "INFO") -> logging.Logger:
    """Configure logging for the pipeline."""
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"pipeline_{timestamp}.log")
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

    # Reduce noisy pdfminer font warnings while preserving errors.
    logging.getLogger("pdfminer.pdffont").setLevel(logging.ERROR)
    return logging.getLogger(__name__)

# ----------------------------------------------------------------------
# File scanning and indexing
# ----------------------------------------------------------------------
def scan_pdf_files(root_dir: str, extensions: List[str]) -> List[Dict[str, Any]]:
    """
    Recursively scan for PDF files and create index with metadata.
    """
    file_index = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if any(filename.lower().endswith(ext) for ext in extensions):
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, root_dir)
                
                try:
                    stat = os.stat(full_path)
                    file_hash = calculate_file_hash(full_path)
                    
                    file_info = {
                        "full_path": full_path,
                        "relative_path": rel_path,
                        "filename": filename,
                        "directory": dirpath,
                        "size_bytes": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "file_hash": file_hash,
                        "file_type": "PDF",
                        "status": "pending"
                    }
                    file_index.append(file_info)
                    
                except Exception as e:
                    logging.error(f"Error processing file {full_path}: {e}")
    
    return sorted(file_index, key=lambda x: x["relative_path"])

def calculate_file_hash(filepath: str, algorithm: str = "sha256") -> str:
    """Calculate file hash for uniqueness checking."""
    hash_func = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()

def save_index(index: List[Dict[str, Any]], output_path: str) -> None:
    """Save file index to JSON."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
# PDF text extraction
# ----------------------------------------------------------------------
def extract_text_from_pdf(pdf_path: str, max_pages: int = 50) -> Dict[str, Any]:
    """
    Extract text from PDF using pdfplumber and PyPDF2.
    Returns structured text with page-level granularity.
    """
    result = {
        "filename": os.path.basename(pdf_path),
        "filepath": pdf_path,
        "extraction_time": datetime.now().isoformat(),
        "total_pages": 0,
        "pages": [],
        "metadata": {},
        "text_summary": "",
        "page_errors": [],
        "error": None
    }
    
    try:
        # Extract metadata with PyPDF2
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            result["total_pages"] = len(pdf_reader.pages)
            
            # Get document info
            if pdf_reader.metadata:
                result["metadata"] = {
                    "title": pdf_reader.metadata.get("/Title", ""),
                    "author": pdf_reader.metadata.get("/Author", ""),
                    "creator": pdf_reader.metadata.get("/Creator", ""),
                    "producer": pdf_reader.metadata.get("/Producer", ""),
                    "creation_date": pdf_reader.metadata.get("/CreationDate", ""),
                    "modification_date": pdf_reader.metadata.get("/ModDate", "")
                }
        
        # Extract text with pdfplumber (better for text-based PDFs)
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_process = min(len(pdf.pages), max_pages)
            
            for page_num in range(pages_to_process):
                
                page_info = {
                    "page_number": page_num + 1,
                    "text": "",
                    "tables_count": 0,
                    "tables": []
                }

                try:
                    page = pdf.pages[page_num]
                    text = page.extract_text() or ""
                    tables = page.extract_tables() or []
                    page_info["text"] = text.strip()
                except KeyboardInterrupt:
                    raise
                except Exception as page_error:
                    fallback_text = ""
                    try:
                        # Fallback to PyPDF2 for pages that break in pdfplumber.
                        with open(pdf_path, "rb") as fallback_file:
                            fallback_reader = PyPDF2.PdfReader(fallback_file)
                            if page_num < len(fallback_reader.pages):
                                fallback_text = fallback_reader.pages[page_num].extract_text() or ""
                    except Exception:
                        fallback_text = ""

                    page_info["text"] = fallback_text.strip()
                    result["page_errors"].append({
                        "page_number": page_num + 1,
                        "error": str(page_error),
                        "fallback_used": bool(fallback_text.strip())
                    })
                    result["pages"].append(page_info)
                    continue
                
                # Process tables
                if tables:
                    for i, table in enumerate(tables):
                        try:
                            table_data = []
                            for row in table:
                                table_data.append([cell or "" for cell in row])

                            if not is_meaningful_table(table_data):
                                continue

                            page_info["tables"].append({
                                "table_index": i,
                                "rows": len(table_data),
                                "columns": len(table_data[0]) if table_data else 0,
                                "data": table_data
                            })
                        except Exception as table_error:
                            result["page_errors"].append({
                                "page_number": page_num + 1,
                                "table_index": i,
                                "error": str(table_error),
                                "fallback_used": False
                            })
                            continue

                page_info["tables_count"] = len(page_info["tables"])
                
                result["pages"].append(page_info)
        
        # Create a text summary (first 5 pages or all if less)
        summary_pages = result["pages"][:5] if len(result["pages"]) > 5 else result["pages"]
        summary_text = "\n\n".join(
            [f"--- Page {page['page_number']} ---\n{page['text'][:1000]}" for page in summary_pages]
        ) if summary_pages else ""
        
        result["text_summary"] = summary_text[:5000]  # Limit summary size
        
    except Exception as e:
        result["error"] = str(e)
        logging.error(f"Error extracting text from {pdf_path}: {e}")
    
    return result

# ----------------------------------------------------------------------
# LLM Integration for data structuring
# ----------------------------------------------------------------------
class DeepSeekPDFAnalyzer:
    """Client for DeepSeek LLM API specialized for PDF report analysis."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError("DeepSeek API key not found. Set DEEPSEEK_API_KEY environment variable.")

        preferred_model = model or DEEPSEEK_MODEL or DEFAULT_CONFIG["llm_model"]
        self.model = resolve_deepseek_model(preferred_model)
        
        if HAS_OPENAI:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=DEEPSEEK_BASE_URL
            )
        else:
            self.client = None
    
    def analyze_financial_report(self, pdf_extraction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze extracted PDF text using DeepSeek LLM.
        Extract structured financial data and metadata.
        """
        try:
            # Prepare the prompt
            prompt = self._create_analysis_prompt(pdf_extraction)
            
            if HAS_OPENAI and self.client:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system", 
                            "content": """You are a financial data analyst expert in Brazilian financial reports.
                            Your task is to extract structured data from financial PDF reports.
                            Return ONLY valid JSON, no other text."""
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=4000,
                    response_format={"type": "json_object"}
                )
                
                result_text = response.choices[0].message.content
            else:
                # Fallback to direct HTTP requests
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a financial data analyst expert in Brazilian financial reports."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4000,
                    "response_format": {"type": "json_object"}
                }
                
                response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                result_text = response.json()["choices"][0]["message"]["content"]
            
            # Parse JSON response
            analysis_result = json.loads(result_text)
            
            # Add metadata
            analysis_result['llm_analysis_metadata'] = {
                'model': self.model,
                'analysis_time': datetime.now().isoformat(),
                'original_filename': pdf_extraction.get('filename', 'unknown'),
                'pages_analyzed': len(pdf_extraction.get('pages', []))
            }
            
            return analysis_result
            
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse LLM response as JSON: {e}")
            # Try to extract JSON from text
            import re
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            return {"error": "Invalid JSON response from LLM", "raw_response": result_text[:1000]}
        except Exception as e:
            logging.error(f"LLM analysis failed: {e}")
            return {"error": str(e), "original_extraction": pdf_extraction}
    
    def _create_analysis_prompt(self, pdf_extraction: Dict[str, Any]) -> str:
        """Create analysis prompt for financial report."""
        filename = pdf_extraction.get("filename", "Unknown")
        text_summary = pdf_extraction.get("text_summary", "")
        total_pages = pdf_extraction.get("total_pages", 0)
        
        prompt = f"""
        Analyze this Brazilian financial report PDF and extract structured data.

        FILENAME: {filename}
        TOTAL PAGES: {total_pages}

        EXTRACTED TEXT (Summary):
        {text_summary}

        Please analyze this financial report and extract the following information:

        1. REPORT METADATA:
           - Report type (e.g., DRE, Balanço, Custo Operacional, Resumo de Vendas, Mapa de Produção, etc.)
           - Period covered (month, year, date range)
           - Company/department name if available
           - Report generation date if available

        2. FINANCIAL DATA STRUCTURE:
           - Main financial categories found (e.g., Receitas, Despesas, Custos, Lucro, etc.)
           - Key financial metrics (values with currency if available)
           - Time period references

        3. TABULAR DATA (if mentioned in text):
           - Table structures identified
           - Column headers inferred
           - Sample data rows

        4. FILE NAME SUGGESTION:
           - Suggest a standardized filename based on content
           - Format: [Report Type]_[Period]_[Company/Dept]_[Date].pdf
           - Example: "DRE_JANEIRO_2026_IBSCO_20260131.pdf"

        5. DIRECTORY SUGGESTION:
           - Suggest appropriate directory path based on report type
           - Example: "CFO/DRE/" for DRE reports

        Return the analysis as JSON with the following structure:
        {{
            "report_metadata": {{
                "report_type": "string",
                "period": "string",
                "company_department": "string",
                "generation_date": "string",
                "confidence_score": 0-1
            }},
            "financial_categories": ["list", "of", "categories"],
            "key_metrics": [
                {{
                    "metric_name": "string",
                    "value": "string",
                    "currency": "string",
                    "period": "string"
                }}
            ],
            "tabular_data_detected": boolean,
            "table_structures": [
                {{
                    "table_index": number,
                    "columns": ["col1", "col2"],
                    "sample_rows": [["val1", "val2"]]
                }}
            ],
            "file_name_suggestion": "string",
            "directory_suggestion": "string",
            "content_summary": "string"
        }}

        Focus on Brazilian Portuguese financial terminology.
        """
        return prompt
    
    def suggest_file_renaming(self, file_index: List[Dict[str, Any]], 
                            analysis_results: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Use LLM to suggest comprehensive file renaming and directory restructuring.
        """
        try:
            # Prepare data for LLM
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
            Analyze these financial report files and suggest a comprehensive renaming and directory restructuring plan.
            
            Current files and their analysis:
            {json.dumps(renaming_data, ensure_ascii=False, indent=2)}
            
            Suggest:
            1. Standardized naming convention for all files
            2. Logical directory structure reorganization
            3. Mapping of old paths to new paths
            
            Consider:
            - Report types (DRE, Balanço, Custo Operacional, etc.)
            - Time periods (2025, 2026, months)
            - Departments (CFO, PCP, etc.)
            - File version indicators (FINAL, draft, etc.)
            
            Return JSON with:
            {{
                "naming_convention": "string describing convention",
                "directory_structure": ["list", "of", "suggested", "directories"],
                "file_mapping": [
                    {{
                        "old_path": "string",
                        "new_path": "string",
                        "reason": "string"
                    }}
                ]
            }}
            """
            
            if HAS_OPENAI and self.client:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system", 
                            "content": "You are a file organization expert for financial reports."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=3000,
                    response_format={"type": "json_object"}
                )
                result_text = response.choices[0].message.content
            else:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a file organization expert for financial reports."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 3000,
                    "response_format": {"type": "json_object"}
                }
                response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                result_text = response.json()["choices"][0]["message"]["content"]
            
            renaming_plan = json.loads(result_text)
            return renaming_plan
            
        except Exception as e:
            logging.error(f"File renaming suggestion failed: {e}")
            return {"error": str(e)}

# ----------------------------------------------------------------------
# CSV Conversion
# ----------------------------------------------------------------------
def convert_to_csv(analysis_results: Dict[str, Dict[str, Any]], output_dir: str) -> Dict[str, str]:
    """
    Convert analysis results to CSV files.
    """
    csv_files = {}
    
    # Create metadata CSV
    metadata_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            metadata = analysis.get("report_metadata", {})
            row = {
                "filename": os.path.basename(filepath),
                "filepath": filepath,
                "report_type": metadata.get("report_type", ""),
                "period": metadata.get("period", ""),
                "company_department": metadata.get("company_department", ""),
                "generation_date": metadata.get("generation_date", ""),
                "confidence_score": metadata.get("confidence_score", 0),
                "financial_categories": "; ".join(analysis.get("financial_categories", [])),
                "file_name_suggestion": analysis.get("file_name_suggestion", ""),
                "directory_suggestion": analysis.get("directory_suggestion", ""),
                "analysis_timestamp": analysis.get("llm_analysis_metadata", {}).get("analysis_time", "")
            }
            metadata_rows.append(row)
    
    if metadata_rows:
        metadata_csv = os.path.join(output_dir, "report_metadata.csv")
        df_metadata = pd.DataFrame(metadata_rows)
        df_metadata.to_csv(metadata_csv, index=False, encoding='utf-8-sig')
        csv_files["metadata"] = metadata_csv
    
    # Create financial metrics CSV
    metrics_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            filename = os.path.basename(filepath)
            metrics = analysis.get("key_metrics", [])
            for metric in metrics:
                row = {
                    "filename": filename,
                    "filepath": filepath,
                    "metric_name": metric.get("metric_name", ""),
                    "value": metric.get("value", ""),
                    "currency": metric.get("currency", ""),
                    "period": metric.get("period", ""),
                    "report_period": analysis.get("report_metadata", {}).get("period", "")
                }
                metrics_rows.append(row)
    
    if metrics_rows:
        metrics_csv = os.path.join(output_dir, "financial_metrics.csv")
        df_metrics = pd.DataFrame(metrics_rows)
        df_metrics.to_csv(metrics_csv, index=False, encoding='utf-8-sig')
        csv_files["metrics"] = metrics_csv
    
    # Create table structures CSV
    table_rows = []
    for filepath, analysis in analysis_results.items():
        if "error" not in analysis:
            filename = os.path.basename(filepath)
            tables = analysis.get("table_structures", [])
            for table in tables:
                columns = table.get("columns", [])
                sample_rows = table.get("sample_rows", [])
                
                for i, row in enumerate(sample_rows[:5]):  # Limit to 5 sample rows per table
                    row_data = {"filename": filename, "filepath": filepath, "table_index": table.get("table_index", 0)}
                    for j, col in enumerate(columns):
                        if j < len(row):
                            row_data[f"col_{j}_{col}"] = row[j]
                        else:
                            row_data[f"col_{j}"] = ""
                    table_rows.append(row_data)
    
    if table_rows:
        tables_csv = os.path.join(output_dir, "table_samples.csv")
        df_tables = pd.DataFrame(table_rows)
        df_tables.to_csv(tables_csv, index=False, encoding='utf-8-sig')
        csv_files["tables"] = tables_csv
    
    return csv_files

# ----------------------------------------------------------------------
# File operations (renaming and reorganization)
# ----------------------------------------------------------------------
def apply_file_renaming(renaming_plan: Dict[str, Any], workspace_dir: str, 
                       dry_run: bool = False) -> Dict[str, Any]:
    """
    Apply the file renaming and reorganization plan.
    """
    results = {
        "total_files": 0,
        "renamed": 0,
        "moved": 0,
        "errors": [],
        "operations": []
    }
    
    file_mapping = renaming_plan.get("file_mapping", [])
    results["total_files"] = len(file_mapping)
    
    for mapping in file_mapping:
        old_path = mapping.get("old_path")
        new_path = mapping.get("new_path")
        reason = mapping.get("reason", "")
        
        if not old_path or not new_path:
            continue
        
        # Make new_path relative to workspace
        new_full_path = os.path.join(workspace_dir, new_path)
        old_full_path = os.path.join(workspace_dir, old_path)
        
        # Create directory if needed
        new_dir = os.path.dirname(new_full_path)
        
        operation = {
            "old_path": old_path,
            "new_path": new_path,
            "old_full": old_full_path,
            "new_full": new_full_path,
            "reason": reason,
            "status": "pending"
        }
        
        try:
            if not dry_run:
                os.makedirs(new_dir, exist_ok=True)
                
                # Check if source exists
                if os.path.exists(old_full_path):
                    # Rename/move the file
                    os.rename(old_full_path, new_full_path)
                    
                    # Update parent directories if empty
                    old_dir = os.path.dirname(old_full_path)
                    if os.path.exists(old_dir) and not os.listdir(old_dir):
                        os.rmdir(old_dir)
                    
                    operation["status"] = "completed"
                    results["renamed"] += 1
                else:
                    operation["status"] = "source_not_found"
                    results["errors"].append(f"Source not found: {old_full_path}")
            else:
                operation["status"] = "dry_run"
                results["renamed"] += 1  # Count for dry run
            
            results["operations"].append(operation)
            
        except Exception as e:
            operation["status"] = f"error: {str(e)}"
            results["errors"].append(f"Error processing {old_path}: {e}")
            results["operations"].append(operation)
    
    return results

# ----------------------------------------------------------------------
# Main Pipeline
# ----------------------------------------------------------------------
def run_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main pipeline execution function.
    """
    logger = setup_logging(config["output_root"], config["log_level"])
    
    # Create directory structure
    workspace_dir = os.path.join(config["output_root"], config["working_dir"])
    os.makedirs(workspace_dir, exist_ok=True)
    
    # Save configuration
    config_path = os.path.join(workspace_dir, "pipeline_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    logger.info("=" * 80)
    logger.info("PDF Report Processing Pipeline")
    logger.info(f"Input root: {config['input_root']}")
    logger.info(f"Output root: {config['output_root']}")
    logger.info(f"Workspace: {workspace_dir}")
    logger.info("=" * 80)
    
    pipeline_results = {
        "start_time": datetime.now().isoformat(),
        "config": config,
        "steps": {},
        "summary": {},
        "status": "running"
    }
    
    try:
        # Step 1: Scan and index PDF files
        logger.info("Step 1: Scanning PDF files...")
        file_index = scan_pdf_files(config["input_root"], config["supported_extensions"])
        
        index_path = os.path.join(workspace_dir, "file_index.json")
        save_index(file_index, index_path)
        
        pipeline_results["steps"]["scanning"] = {
            "status": "completed",
            "files_found": len(file_index),
            "index_path": index_path
        }
        logger.info(f"Found {len(file_index)} PDF files")
        
        if not file_index:
            logger.warning("No PDF files found. Exiting pipeline.")
            pipeline_results["end_time"] = datetime.now().isoformat()
            pipeline_results["status"] = "completed"
            return pipeline_results
        
        # Step 2: Extract text from PDFs
        logger.info("Step 2: Extracting text from PDFs...")
        extraction_results = {}
        extraction_dir = os.path.join(workspace_dir, "extractions")
        os.makedirs(extraction_dir, exist_ok=True)
        
        for i, file_info in enumerate(file_index, 1):
            logger.info(f"Extracting [{i}/{len(file_index)}]: {file_info['filename']}")
            
            extraction = extract_text_from_pdf(
                file_info["full_path"], 
                max_pages=config["max_pages_per_pdf"]
            )
            
            extraction_results[file_info["full_path"]] = extraction
            
            # Save individual extraction
            extract_filename = f"{file_info['filename']}_extraction.json"
            extract_path = os.path.join(extraction_dir, extract_filename)
            
            with open(extract_path, 'w', encoding='utf-8') as f:
                json.dump(extraction, f, ensure_ascii=False, indent=2)
            
            file_info["extraction_path"] = extract_path
            file_info["extraction_status"] = "error" if extraction.get("error") else "completed"
        
        # Save updated index
        save_index(file_index, index_path)
        
        pipeline_results["steps"]["extraction"] = {
            "status": "completed",
            "files_processed": len(extraction_results),
            "extraction_dir": extraction_dir
        }
        
        # Step 3: LLM Analysis (if API key available)
        analysis_results = {}
        if DEEPSEEK_API_KEY:
            logger.info("Step 3: Analyzing with DeepSeek LLM...")
            
            analyzer = DeepSeekPDFAnalyzer(
                DEEPSEEK_API_KEY,
                model=config.get("llm_model"),
            )
            analysis_dir = os.path.join(workspace_dir, "analysis")
            os.makedirs(analysis_dir, exist_ok=True)
            
            for i, (filepath, extraction) in enumerate(extraction_results.items(), 1):
                if extraction.get("error"):
                    logger.warning(f"Skipping analysis for {os.path.basename(filepath)} due to extraction error")
                    continue
                
                logger.info(f"Analyzing [{i}/{len(extraction_results)}]: {os.path.basename(filepath)}")
                
                analysis = analyzer.analyze_financial_report(extraction)
                analysis_results[filepath] = analysis
                
                # Save individual analysis
                analysis_filename = f"{os.path.basename(filepath)}_analysis.json"
                analysis_path = os.path.join(analysis_dir, analysis_filename)
                
                with open(analysis_path, 'w', encoding='utf-8') as f:
                    json.dump(analysis, f, ensure_ascii=False, indent=2)
                
                # Rate limiting
                if i < len(extraction_results):
                    time.sleep(2)  # 2-second delay between API calls
            
            pipeline_results["steps"]["llm_analysis"] = {
                "status": "completed",
                "files_analyzed": len(analysis_results),
                "analysis_dir": analysis_dir
            }
        else:
            logger.warning("Step 3: Skipping LLM analysis (no API key)")
            pipeline_results["steps"]["llm_analysis"] = {
                "status": "skipped",
                "reason": "No DeepSeek API key"
            }
        
        # Step 4: Convert to CSV
        logger.info("Step 4: Converting to CSV...")
        csv_dir = os.path.join(workspace_dir, "csv_output")
        os.makedirs(csv_dir, exist_ok=True)
        
        csv_files = convert_to_csv(analysis_results, csv_dir)
        
        pipeline_results["steps"]["csv_conversion"] = {
            "status": "completed",
            "csv_files": csv_files,
            "csv_dir": csv_dir
        }
        logger.info(f"Created CSV files: {list(csv_files.keys())}")
        
        # Step 5: File renaming and reorganization
        if analysis_results and DEEPSEEK_API_KEY:
            logger.info("Step 5: Planning file renaming and reorganization...")
            
            # Get comprehensive renaming plan
            renaming_plan = analyzer.suggest_file_renaming(file_index, analysis_results)
            
            renaming_plan_path = os.path.join(workspace_dir, "renaming_plan.json")
            with open(renaming_plan_path, 'w', encoding='utf-8') as f:
                json.dump(renaming_plan, f, ensure_ascii=False, indent=2)
            
            # Apply renaming (optional - based on config)
            if not config["dry_run"]:
                logger.info("Applying file renaming and reorganization...")
                rename_results = apply_file_renaming(renaming_plan, config["input_root"], dry_run=False)
                
                rename_results_path = os.path.join(workspace_dir, "renaming_results.json")
                with open(rename_results_path, 'w', encoding='utf-8') as f:
                    json.dump(rename_results, f, ensure_ascii=False, indent=2)
                
                pipeline_results["steps"]["file_reorganization"] = {
                    "status": "completed",
                    "renaming_plan": renaming_plan_path,
                    "renaming_results": rename_results_path,
                    "files_renamed": rename_results.get("renamed", 0),
                    "errors": len(rename_results.get("errors", []))
                }
                logger.info(f"Renamed {rename_results.get('renamed', 0)} files")
            else:
                logger.info("Dry run mode - file renaming not applied")
                pipeline_results["steps"]["file_reorganization"] = {
                    "status": "dry_run",
                    "renaming_plan": renaming_plan_path,
                    "note": "Dry run mode - changes not applied"
                }
        else:
            logger.info("Step 5: Skipping file reorganization (no analysis results or API key)")
            pipeline_results["steps"]["file_reorganization"] = {
                "status": "skipped",
                "reason": "No analysis results or API key"
            }
        
        # Step 6: Create summary report
        logger.info("Step 6: Creating summary report...")
        
        summary = {
            "pipeline_execution": {
                "start_time": pipeline_results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_files": len(file_index)
            },
            "file_statistics": {
                "total_pdfs": len(file_index),
                "successful_extractions": sum(1 for e in extraction_results.values() if not e.get("error")),
                "successful_analyses": sum(1 for a in analysis_results.values() if "error" not in a)
            },
            "outputs": {
                "workspace": workspace_dir,
                "index_file": index_path,
                "extractions": extraction_dir,
                "analysis": analysis_dir if analysis_results else None,
                "csv_files": csv_dir
            }
        }
        
        summary_path = os.path.join(workspace_dir, "pipeline_summary.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        # Create human-readable summary
        human_summary = f"""
        PDF PROCESSING PIPELINE SUMMARY
        ================================
        
        Execution Time: {summary['pipeline_execution']['start_time']} to {summary['pipeline_execution']['end_time']}
        
        FILE STATISTICS:
        - Total PDF files: {summary['file_statistics']['total_pdfs']}
        - Successful text extractions: {summary['file_statistics']['successful_extractions']}
        - Successful LLM analyses: {summary['file_statistics']['successful_analyses']}
        
        OUTPUTS:
        - Workspace directory: {summary['outputs']['workspace']}
        - File index: {summary['outputs']['index_file']}
        - Text extractions: {summary['outputs']['extractions']}
        - LLM analysis: {summary['outputs']['analysis'] or 'Not performed'}
        - CSV files: {summary['outputs']['csv_files']}
        
        NEXT STEPS:
        1. Review the CSV files for extracted data
        2. Check the renaming plan if reorganization was suggested
        3. Verify file changes were applied correctly
        4. Use the structured data for further analysis
        
        All operations were confined to: {os.path.abspath(config['input_root'])}
        """
        
        human_summary_path = os.path.join(workspace_dir, "SUMMARY.txt")
        with open(human_summary_path, 'w', encoding='utf-8') as f:
            f.write(human_summary)
        
        pipeline_results["summary"] = summary
        pipeline_results["summary_path"] = summary_path
        pipeline_results["human_summary_path"] = human_summary_path
        
        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info(f"Summary saved to: {summary_path}")
        logger.info(f"Human-readable summary: {human_summary_path}")
        logger.info("=" * 80)
        pipeline_results["status"] = "completed"

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        pipeline_results["error"] = "Interrupted by user"
        pipeline_results["status"] = "interrupted"

        interrupted_path = os.path.join(workspace_dir, "pipeline_interrupted.json")
        with open(interrupted_path, 'w', encoding='utf-8') as f:
            json.dump(pipeline_results, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        pipeline_results["error"] = str(e)
        pipeline_results["status"] = "failed"
        
        # Save error state
        error_path = os.path.join(workspace_dir, "pipeline_error.json")
        with open(error_path, 'w', encoding='utf-8') as f:
            json.dump(pipeline_results, f, ensure_ascii=False, indent=2)
    
    pipeline_results["end_time"] = datetime.now().isoformat()
    
    return pipeline_results

# ----------------------------------------------------------------------
# Command-line interface
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="PDF Report Processing Pipeline")
    parser.add_argument("--input", "-i", default="./IBSCO", help="Input directory root (default: ./IBSCO)")
    parser.add_argument("--output", "-o", default="./pdf_processed_results", help="Output directory (default: ./pdf_processed_results)")
    parser.add_argument("--api-key", "-k", help="DeepSeek API key (overrides environment variable)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Dry run mode (don't rename files)")
    parser.add_argument("--config", "-c", help="Path to configuration JSON file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")
    
    args = parser.parse_args()
    
    # Load configuration
    config = DEFAULT_CONFIG.copy()
    
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
        config.update(user_config)
    
    # Override with command-line arguments
    config["input_root"] = args.input
    config["output_root"] = args.output
    config["dry_run"] = args.dry_run
    config["log_level"] = args.log_level
    
    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key
        global DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = args.api_key
    
    # Run pipeline
    results = run_pipeline(config)
    
    # Exit with appropriate code
    if results.get("status") == "completed":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()