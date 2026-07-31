#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image‑Based Report Processing Pipeline (Context‑Aware)
======================================================
- Trims prompt to fit within 4096‑token context window for vision models like qwen3‑vl:4b
- Resizes images to reduce token usage
- Keeps full OCR coordinate data only for text‑only models
"""

import os, sys, json, csv, argparse, logging, hashlib, base64, re, time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import cv2
import numpy as np
from PIL import Image
import pytesseract
import pandas as pd

try:
    import pyheif
    HAS_HEIC = True
except ImportError:
    HAS_HEIC = False

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
# Default configuration
# ----------------------------------------------------------------------
DEFAULT_CONFIG = {
    "input_root": "images",
    "output_root": ".results",
    "working_dir": "./image_processing_workspace",
    "supported_extensions": [".heic", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
    "llm_provider": os.getenv("LLM_PROVIDER", "deepseek"),
    "llm_model": os.getenv("LLM_MODEL", "ldeepseek-v4-flash"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "lfm2.5:8b"),
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    "llm_temperature": 0.1,
    "llm_max_tokens": int(os.getenv("LLM_MAX_TOKENS", 1024)),
    "ocr_language": "por+eng",
    "csv_encoding": "utf-8-sig",
    "backup_original_files": True,
    "dry_run": False,
    "log_level": "INFO",
    "preprocessing_enabled": True,
    "vision_max_dim": 800,
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

def image_to_base64_resized(image: np.ndarray, max_dim: int = 800, fmt: str = ".jpg") -> str:
    """Resize image to reduce token usage, then encode to base64."""
    if image is None:
        return ""
    h, w = image.shape[:2]
    if max_dim > 0 and max_dim < max(h, w):
        scale = max_dim / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _, buffer = cv2.imencode(fmt, image)
    return base64.b64encode(buffer).decode("utf-8")

# ----------------------------------------------------------------------
# OpenCV preprocessing
# ----------------------------------------------------------------------
def preprocess_image(image_path: str) -> Optional[np.ndarray]:
    try:
        if image_path.lower().endswith(".heic") and HAS_HEIC:
            heif_file = pyheif.read(image_path)
            pil_img = Image.frombytes(
                heif_file.mode, heif_file.size, heif_file.data,
                "raw", heif_file.mode, heif_file.stride,
            )
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        else:
            img = cv2.imread(image_path)
        if img is None:
            logging.error(f"Could not read image: {image_path}")
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 11
        )
        return processed
    except Exception as e:
        logging.error(f"Preprocessing failed for {image_path}: {e}")
        return None

# ----------------------------------------------------------------------
# OCR extraction (coordinates + confidence)
# ----------------------------------------------------------------------
def extract_ocr_data(image: np.ndarray, ocr_lang: str = "por+eng") -> Dict[str, Any]:
    if image is None:
        return {"error": "No image provided", "word_boxes": [], "text_summary": ""}
    try:
        data = pytesseract.image_to_data(
            image, lang=ocr_lang, output_type=pytesseract.Output.DATAFRAME
        )
        data = data[data.conf != -1]
        data = data[data.text.notna() & (data.text.str.strip() != "")]
        word_boxes = []
        for _, row in data.iterrows():
            word_boxes.append({
                "text": row.text.strip(),
                "left": int(row.left),
                "top": int(row.top),
                "width": int(row.width),
                "height": int(row.height),
                "conf": int(row.conf),
            })
        plain_text = pytesseract.image_to_string(image, lang=ocr_lang)
        return {"word_boxes": word_boxes, "text_summary": plain_text[:5000]}
    except Exception as e:
        logging.error(f"OCR extraction failed: {e}")
        return {"error": str(e), "word_boxes": [], "text_summary": ""}

# ----------------------------------------------------------------------
# Coordinate‑based table reconstruction
# ----------------------------------------------------------------------
def reconstruct_tables_from_boxes(word_boxes: List[Dict]) -> List[Dict[str, Any]]:
    if not word_boxes:
        return []
    boxes = sorted(word_boxes, key=lambda b: (b["top"], b["left"]))
    lines = []
    current_line = [boxes[0]]
    line_top = boxes[0]["top"]
    for b in boxes[1:]:
        if abs(b["top"] - line_top) <= 5:
            current_line.append(b)
        else:
            lines.append(sorted(current_line, key=lambda x: x["left"]))
            current_line = [b]
            line_top = b["top"]
    lines.append(sorted(current_line, key=lambda x: x["left"]))
    all_lefts = []
    for line in lines:
        all_lefts.extend([w["left"] for w in line])
    all_lefts = sorted(set(all_lefts))
    col_centers = []
    cluster = [all_lefts[0]]
    for x in all_lefts[1:]:
        if x - cluster[-1] <= 20:
            cluster.append(x)
        else:
            col_centers.append(int(np.mean(cluster)))
            cluster = [x]
    col_centers.append(int(np.mean(cluster)))

    def nearest_col(left, centers):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - left))

    table_lines = []
    for line in lines:
        row = [""] * len(col_centers)
        for word in line:
            col_idx = nearest_col(word["left"], col_centers)
            row[col_idx] = (row[col_idx] + " " + word["text"]).strip()
        if any(cell != "" for cell in row):
            table_lines.append(row)
    if len(table_lines) > 1 and len(col_centers) > 1:
        return [{"headers": table_lines[0], "rows": table_lines[1:]}]
    return []

# ----------------------------------------------------------------------
# Robust JSON extraction
# ----------------------------------------------------------------------
def extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    text = text.strip()
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError("No valid JSON object found in LLM response")

# ----------------------------------------------------------------------
# LLM Analyzer (context‑aware)
# ----------------------------------------------------------------------
class LLMAnalyzer:
    def __init__(self, config: Dict[str, Any]):
        self.provider = config.get("llm_provider", "ollama").lower()
        self.temperature = config.get("llm_temperature", 0.1)
        self.max_tokens = config.get("llm_max_tokens", 1024)
        self.vision_max_dim = config.get("vision_max_dim", 800)
        self.client = None

        if self.provider == "ollama":
            self.model = config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])
            base_url = config.get("ollama_base_url", DEFAULT_CONFIG["ollama_base_url"])
            self.client = OpenAI(api_key="ollama", base_url=base_url)
            self.supports_json_mode = False
        elif self.provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key: raise ValueError("DeepSeek API key required.")
            self.model = config.get("llm_model", "deepseek-v4-flash")
            self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            self.supports_json_mode = True
        elif self.provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key: raise ValueError("OpenAI API key required.")
            self.model = config.get("llm_model", "gpt-4o-mini")
            self.client = OpenAI(api_key=api_key)
            self.supports_json_mode = True
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        self.is_vision_model = (
            self.provider == "ollama" and ("vl" in self.model.lower() or "vision" in self.model.lower())
        )

    def _chat_completion(
        self, messages: List[Dict], use_json: bool = True, images: List[str] = None
    ) -> str:
        if self.client is None:
            raise RuntimeError("OpenAI client not initialised")

        if images and self.is_vision_model:
            if messages[-1]["role"] == "user":
                text = messages[-1]["content"]
                content_parts = [{"type": "text", "text": text}]
                for img_b64 in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
                messages[-1]["content"] = content_parts

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if use_json and self.supports_json_mode and not images:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            content = choice.message.content or ""
            if not content:
                reasoning = getattr(choice.message, "reasoning", None)
                if reasoning:
                    logging.warning(
                        "LLM returned empty content but had reasoning. "
                        "Attempting to extract JSON from reasoning."
                    )
                    try:
                        return extract_json(reasoning)
                    except ValueError:
                        pass
                logging.error(
                    "LLM returned empty content and no extractable JSON. "
                    "Full response:\n%s", response.model_dump_json(indent=2)
                )
            return content
        except Exception as e:
            logging.error(f"LLM call failed: {e}")
            raise

    def analyze_report(
        self,
        extraction: Dict[str, Any],
        preprocessed_image: Optional[np.ndarray] = None,
        original_image_path: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            if self.is_vision_model and preprocessed_image is not None:
                prompt = self._create_vision_prompt()
                img_b64 = image_to_base64_resized(preprocessed_image, max_dim=self.vision_max_dim)
                images = [img_b64] if img_b64 else []
            else:
                prompt = self._create_ocr_prompt(extraction)
                images = []

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an expert data extraction assistant. "
                        "Return ONLY a valid JSON object. No explanations."
                    )
                },
                {"role": "user", "content": prompt}
            ]

            result_text = self._chat_completion(
                messages, use_json=not bool(images), images=images
            )

            if isinstance(result_text, dict):
                analysis = result_text
            else:
                analysis = extract_json(result_text)

            analysis["llm_analysis_metadata"] = {
                "model": self.model,
                "provider": self.provider,
                "analysis_time": datetime.now().isoformat(),
                "original_filename": extraction.get("filename", "unknown"),
            }
            return analysis
        except Exception as e:
            logging.error(f"LLM analysis failed: {e}")
            return {"error": str(e), "original_extraction": extraction}

    def _create_vision_prompt(self) -> str:
        return (
            "Extract all tables, metrics, and metadata from the document in the image. "
            "Return JSON with fields: report_metadata (report_type, period_covered, company_name, patient_name, report_date), "
            "key_metrics (list of {metric_name, value, unit, period}), "
            "table_structures (list of {headers, rows}), "
            "file_name_suggestion (e.g., 'BMD_Report_2026-05-08_XMED.pdf'), "
            "directory_suggestion (e.g., 'Medical/Reports/'), "
            "content_summary (short). "
            "Preserve all numeric values exactly. Use empty strings for missing fields. "
            "Return ONLY the JSON object, no markdown."
        )

    def _create_ocr_prompt(self, extraction: Dict[str, Any]) -> str:
        # Not used for vision models, kept for completeness.
        # This is a shortened version of the earlier prompt.
        word_boxes = extraction.get("word_boxes", [])
        tables = extraction.get("tables", [])
        text_summary = extraction.get("text_summary", "")

        ocr_table = "OCR data (word, left, top, width, height, confidence):\n"
        ocr_table += "text | left | top | width | height | conf\n"
        for w in word_boxes[:100]:
            ocr_table += f"{w['text']} | {w['left']} | {w['top']} | {w['width']} | {w['height']} | {w['conf']}\n"

        table_text = ""
        if tables:
            for i, tbl in enumerate(tables):
                table_text += f"\nReconstructed Table {i+1}:\n"
                table_text += "Headers: " + " | ".join(tbl["headers"]) + "\n"
                for row in tbl["rows"]:
                    table_text += "Row: " + " | ".join(row) + "\n"

        return f"""
Extract structured data from this OCR output.
Document type: report/invoice/medical.
Return JSON with:
  report_metadata (report_type, period_covered, company_name, patient_name, report_date)
  key_metrics (list of {{metric_name, value, unit, period}})
  table_structures (list of {{headers, rows}})
  file_name_suggestion, directory_suggestion, content_summary.
Preserve numbers exactly. Use empty strings for missing fields.

{ocr_table}
{table_text}
Plain text: {text_summary[:1000]}

Output ONLY the JSON object, no markdown.
"""

    def suggest_file_renaming(self, file_index, analysis_results):
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
        prompt = (
            "Given the file analysis data, suggest a renaming plan. "
            "Return JSON with naming_convention, directory_structure (list), "
            "and file_mapping (list of {old_path, new_path, reason}). "
            f"Data: {json.dumps(renaming_data, ensure_ascii=False, indent=2)}"
        )
        messages = [
            {"role": "system", "content": "You are a file organization expert. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ]
        result_text = self._chat_completion(messages, use_json=True, images=None)
        if isinstance(result_text, dict):
            return result_text
        try:
            return extract_json(result_text)
        except ValueError:
            return {"error": "Could not parse renaming plan", "raw": result_text}

# ----------------------------------------------------------------------
# CSV conversion
# ----------------------------------------------------------------------
def convert_to_csv(analysis_results: Dict[str, Dict[str, Any]], output_dir: str) -> Dict[str, str]:
    csv_files = {}
    # Metadata
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
                "patient": meta.get("patient_name", ""),
                "generation_date": meta.get("report_date", ""),
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
                rows = tbl.get("rows", [])
                for ri, row in enumerate(rows):
                    d = {"filename": fname, "filepath": filepath, "table_index": ti, "row_index": ri}
                    for ci, h in enumerate(headers):
                        d[h] = row[ci] if ci < len(row) else ""
                    table_rows.append(d)
    if table_rows:
        tbl_csv = os.path.join(output_dir, "tables.csv")
        pd.DataFrame(table_rows).to_csv(tbl_csv, index=False, encoding='utf-8-sig')
        csv_files["tables"] = tbl_csv

    return csv_files

# ----------------------------------------------------------------------
# File scanning
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

# ----------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------
def run_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    logger = setup_logging(config["output_root"], config["log_level"])
    workspace = os.path.join(config["output_root"], config["working_dir"])
    os.makedirs(workspace, exist_ok=True)

    config_path = os.path.join(workspace, "pipeline_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    logger.info("=" * 80)
    logger.info("Image‑Based Report Processing Pipeline (Context‑Aware)")
    logger.info(f"Input: {config['input_root']}  Output: {workspace}")
    logger.info("=" * 80)

    pipeline_meta = {"start_time": datetime.now().isoformat(), "steps": {}, "status": "running"}

    # Step 1: Scan
    logger.info("Step 1: Scanning images...")
    file_index = scan_image_files(config["input_root"], config["supported_extensions"])
    index_path = os.path.join(workspace, "file_index.json")
    save_index(file_index, index_path)
    logger.info(f"Found {len(file_index)} images")
    pipeline_meta["steps"]["scanning"] = {"status": "completed", "files": len(file_index)}
    if not file_index:
        logger.warning("No images found.")
        pipeline_meta["status"] = "completed"
        return pipeline_meta

    # Step 2: OCR + analysis
    llm_provider = config.get("llm_provider", "none").lower()
    analysis_results = {}
    analyzer = None
    if llm_provider != "none":
        try:
            analyzer = LLMAnalyzer(config)
        except Exception as e:
            logger.error(f"LLM init failed: {e}")
            pipeline_meta["steps"]["llm_analysis"] = {"status": "failed", "error": str(e)}
            analysis_results = {}
    else:
        pipeline_meta["steps"]["llm_analysis"] = {"status": "skipped"}

    for i, fi in enumerate(file_index, 1):
        logger.info(f"Processing {i}/{len(file_index)}: {fi['filename']}")
        image_path = fi["full_path"]

        # Preprocessing
        processed = None
        if config.get("preprocessing_enabled", True):
            processed = preprocess_image(image_path)
            if processed is None:
                logger.warning(f"Preprocessing failed, falling back to original image")
                processed = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        else:
            processed = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

        ocr_data = extract_ocr_data(processed, ocr_lang=config["ocr_language"])
        ocr_data["filename"] = fi["filename"]
        tables = reconstruct_tables_from_boxes(ocr_data.get("word_boxes", []))
        ocr_data["tables"] = tables

        extraction_dir = os.path.join(workspace, "extractions")
        os.makedirs(extraction_dir, exist_ok=True)
        ext_path = os.path.join(extraction_dir, f"{fi['filename']}_extraction.json")
        with open(ext_path, 'w', encoding='utf-8') as f:
            json.dump(ocr_data, f, ensure_ascii=False, indent=2)
        fi["extraction_path"] = ext_path

        if analyzer and "error" not in ocr_data:
            analysis = analyzer.analyze_report(
                ocr_data,
                preprocessed_image=processed,
                original_image_path=image_path
            )
            analysis_results[image_path] = analysis
            analysis_dir = os.path.join(workspace, "analysis")
            os.makedirs(analysis_dir, exist_ok=True)
            analysis_path = os.path.join(analysis_dir, f"{fi['filename']}_analysis.json")
            with open(analysis_path, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)
            time.sleep(1)
        else:
            analysis_results[image_path] = {"error": ocr_data.get("error", "No LLM provider")}

    pipeline_meta["steps"]["llm_analysis"] = {"status": "completed", "analyzed": len(analysis_results)}

    # Step 3: CSV
    logger.info("Converting to CSV...")
    csv_dir = os.path.join(workspace, "csv_output")
    os.makedirs(csv_dir, exist_ok=True)
    csv_files = convert_to_csv(analysis_results, csv_dir)
    pipeline_meta["steps"]["csv_conversion"] = {"status": "completed", "files": list(csv_files.keys())}
    logger.info(f"CSV files: {list(csv_files.keys())}")

    # Step 4: Renaming (fallback if needed)
    if llm_provider != "none" and analysis_results and analyzer:
        logger.info("Planning file renaming...")
        renaming_plan = analyzer.suggest_file_renaming(file_index, analysis_results)
        if "error" in renaming_plan or not renaming_plan.get("file_mapping"):
            logger.warning("Using fallback renaming.")
            fallback = []
            for item in file_index:
                analysis = analysis_results.get(item["full_path"], {})
                suggested = analysis.get("file_name_suggestion", "")
                suggested_dir = analysis.get("directory_suggestion", "Misc/")
                if not suggested:
                    suggested = os.path.splitext(item["filename"])[0] + ".pdf"
                fallback.append({
                    "old_path": item["relative_path"],
                    "new_path": os.path.join(suggested_dir, suggested),
                    "reason": "fallback"
                })
            renaming_plan = {"file_mapping": fallback}

        plan_path = os.path.join(workspace, "renaming_plan.json")
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(renaming_plan, f, ensure_ascii=False, indent=2)

        if not config["dry_run"]:
            logger.info("Applying renaming...")
            renamed = 0
            errors = []
            for mapping in renaming_plan.get("file_mapping", []):
                old_rel = mapping["old_path"]
                new_rel = mapping["new_path"]
                old_abs = os.path.join(config["input_root"], old_rel)
                new_abs = os.path.join(config["input_root"], new_rel)
                try:
                    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                    if os.path.exists(old_abs):
                        os.rename(old_abs, new_abs)
                        renamed += 1
                        old_dir = os.path.dirname(old_abs)
                        if os.path.exists(old_dir) and not os.listdir(old_dir):
                            os.rmdir(old_dir)
                    else:
                        errors.append(f"Source not found: {old_abs}")
                except Exception as e:
                    errors.append(str(e))
            pipeline_meta["steps"]["file_reorganization"] = {"renamed": renamed, "errors": errors}
            logger.info(f"Renamed {renamed} files")
        else:
            pipeline_meta["steps"]["file_reorganization"] = {"status": "dry_run"}
    else:
        pipeline_meta["steps"]["file_reorganization"] = {"status": "skipped"}

    # Summary
    logger.info("Generating summary...")
    summary = {
        "pipeline_execution": {
            "start_time": pipeline_meta["start_time"],
            "end_time": datetime.now().isoformat(),
            "total_files": len(file_index)
        },
        "file_statistics": {
            "total_images": len(file_index),
            "successful_analyses": sum(1 for a in analysis_results.values() if "error" not in a)
        },
        "outputs": {
            "workspace": workspace,
            "index_file": index_path,
            "csv_files": csv_dir
        }
    }
    summary_path = os.path.join(workspace, "pipeline_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(workspace, "SUMMARY.txt"), 'w', encoding='utf-8') as f:
        f.write(f"Pipeline completed. {len(file_index)} files processed.\n")
    pipeline_meta["summary"] = summary
    pipeline_meta["status"] = "completed"
    logger.info("Pipeline completed.")
    return pipeline_meta

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Context‑Aware Image Processing Pipeline")
    parser.add_argument("--input", "-i", default="./IBSCO")
    parser.add_argument("--output", "-o", default="./pdf_processed_results")
    parser.add_argument("--llm-provider", choices=["deepseek", "ollama", "openai", "none"])
    parser.add_argument("--llm-model", help="Model name (e.g., lfm2.5:8b)")
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
        config["ollama_model"] = args.llm_model

    results = run_pipeline(config)
    sys.exit(0 if results.get("status") == "completed" else 1)

if __name__ == "__main__":
    main()