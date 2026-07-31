#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image-Based Report Processing Pipeline (Learning Edition)

Adds on top of the previous version:
  1. Persistent Knowledge Base (survives across runs, in output_root/knowledge_base.json)
     - learns canonical patient/company names, report-type vocabulary,
       metric-name normalization, and recurring OCR error -> correction pairs
     - injected back into the LLM prompt as hints, so extraction gets more
       consistent the more the pipeline is run on the same person's documents
  2. File-hash cache (output_root/file_cache.json)
     - skips OCR + LLM analysis entirely for files already processed in a
       previous run and unchanged on disk
  3. Image preprocessing before OCR
     - EXIF auto-orient, grayscale, upscaling of small/low-res photos,
       denoising + deskew (OpenCV if available, PIL-only fallback otherwise)
     - per-file OCR confidence score (mean word confidence from Tesseract)
  4. Cross-file refinement pass (Step 7, after the original pipeline finishes)
     - groups files by canonical report_type + period
     - uses high-confidence siblings to fix spelling/formatting/naming
       inconsistencies in METADATA fields only (patient/company/report_type/
       metric names, content_summary wording)
     - deliberately never fills in or overwrites numeric measurement values
       from a sibling document's consensus -- that would fabricate data.
       It only fixes text formatting, canonicalizes names, and applies
       previously-learned OCR corrections. All changes are logged per file
       with their source so the result is auditable, not silently altered.

Design note on the refinement step: metadata (who the patient is, what kind
of report this is, what a metric is *called*) is expected to repeat across a
person's documents and is safe to reconcile by consensus. Metric *values*
are specific to each document/date and are never touched by consensus -- at
most their OCR'd text is corrected via the learned correction dictionary if
a near-identical wrong->right pair has been seen with high confidence before.
"""

import os
import sys
import json
import argparse
import logging
import hashlib
import difflib
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, Counter

from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import pytesseract
from pytesseract import Output

try:
    import pyheif
    HAS_HEIC = True
except ImportError:
    HAS_HEIC = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

import pandas as pd

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEFAULT_CONFIG = {
    "input_root": "images",
    "output_root": "results",
    "working_dir": "image_processing_workspace",
    "supported_extensions": [".heic", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
    "llm_provider": os.getenv("LLM_PROVIDER", "deepseek"),
    "llm_model": os.getenv("LLM_MODEL", "deepseek-v4-flash"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "llama3.1"),
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11436/v1"),
    "llm_temperature": 0.1,
    "llm_max_tokens": 8192,
    "ocr_language": "por+eng",
    "csv_encoding": "utf-8-sig",
    "dry_run": False,
    "log_level": "INFO",
    "max_ocr_chars": 3000,

    # --- new options ---
    "knowledge_base_file": "knowledge_base.json",   # lives in output_root, persists across runs
    "file_cache_file": "file_cache.json",            # lives in output_root, persists across runs
    "enable_learning": True,
    "enable_cache": True,
    "force_reprocess": False,
    "enable_preprocessing": True,
    "enable_refinement": True,
    "min_ocr_confidence_trusted": 70.0,   # >= this -> treated as a trustworthy "anchor" in a group
    "min_ocr_confidence_flag": 45.0,      # below this -> flagged for refinement priority
    "fuzzy_match_threshold": 0.84,        # similarity threshold for KB canonicalization
    "correction_min_occurrences": 2,      # a learned OCR correction must be seen this many times before auto-applying
    "upscale_target_width": 1800,         # upscale images narrower than this before OCR
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

def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()

def atomic_write_json(path: str, data: Any) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def safe_load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logging.warning(f"Could not parse {path}, starting fresh.")
    return default

# ----------------------------------------------------------------------
# Knowledge Base -- persistent, cross-run learning
# ----------------------------------------------------------------------
class KnowledgeBase:
    """
    Accumulates recurring facts about a single person's documents across
    pipeline runs: canonical names, report-type vocabulary, metric-name
    normalization, and OCR error corrections. Fuzzy-matches new values
    against what it already knows so that "Jhon Silva" and "John Silva"
    converge to one canonical spelling over time instead of both persisting.
    """

    CATEGORIES = ["patient_names", "company_names", "report_types", "metric_vocabulary"]

    def __init__(self, path: str, threshold: float = 0.84):
        self.path = path
        self.threshold = threshold
        self.data = self._default()
        self._load()

    def _default(self) -> Dict[str, Any]:
        return {
            "version": 2,
            "created": datetime.now().isoformat(),
            "last_updated": None,
            "patient_names": {},      # canonical -> {"variants": {variant: count}, "count": n}
            "company_names": {},
            "report_types": {},       # canonical -> {"variants": {...}, "count": n,
                                       #               "filename_suggestions": [...], "directory_suggestions": [...]}
            "metric_vocabulary": {},  # canonical -> {"variants": {...}, "count": n, "units": {unit: count}}
            "ocr_corrections": {},    # "wrong=>right" -> {"count": n, "wrong": .., "right": ..}
            "stats": {"total_runs": 0, "total_files_learned": 0},
        }

    def _load(self) -> None:
        loaded = safe_load_json(self.path, None)
        if loaded:
            self.data.update(loaded)

    def save(self) -> None:
        self.data["last_updated"] = datetime.now().isoformat()
        atomic_write_json(self.path, self.data)

    # ---- canonicalization -------------------------------------------------
    def _best_match(self, category: str, value: str) -> Optional[str]:
        best_key, best_score = None, 0.0
        for canonical in self.data[category].keys():
            score = similarity(canonical, value)
            if score > best_score:
                best_key, best_score = canonical, score
        if best_key and best_score >= self.threshold:
            return best_key
        return None

    def normalize_and_learn(self, category: str, raw_value: str) -> str:
        """Returns the canonical value for raw_value, learning it if new."""
        raw_value = (raw_value or "").strip()
        if not raw_value:
            return raw_value
        bucket = self.data[category]
        match = self._best_match(category, raw_value)
        if match:
            entry = bucket[match]
            entry["variants"][raw_value] = entry["variants"].get(raw_value, 0) + 1
            entry["count"] = entry.get("count", 0) + 1
            # if this exact raw value is now the most frequent variant, learn a
            # correction wrong->right for any less-frequent variant that differs
            # only slightly (cheap OCR-typo learning)
            top_variant = max(entry["variants"].items(), key=lambda kv: kv[1])[0]
            if top_variant != raw_value and similarity(top_variant, raw_value) >= self.threshold:
                self.learn_ocr_correction(raw_value, top_variant)
            return top_variant
        else:
            bucket[raw_value] = {"variants": {raw_value: 1}, "count": 1}
            return raw_value

    def known_values(self, category: str, top_n: int = 12) -> List[str]:
        bucket = self.data[category]
        ranked = sorted(bucket.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)
        return [k for k, _ in ranked[:top_n]]

    def register_metric_unit(self, metric_canonical: str, unit: str) -> None:
        if not unit:
            return
        entry = self.data["metric_vocabulary"].get(metric_canonical)
        if entry is None:
            return
        units = entry.setdefault("units", {})
        units[unit] = units.get(unit, 0) + 1

    def preferred_unit(self, metric_canonical: str) -> Optional[str]:
        entry = self.data["metric_vocabulary"].get(metric_canonical)
        if not entry or not entry.get("units"):
            return None
        return max(entry["units"].items(), key=lambda kv: kv[1])[0]

    def register_report_type_hints(self, canonical: str, filename_suggestion: str, directory_suggestion: str) -> None:
        entry = self.data["report_types"].get(canonical)
        if entry is None:
            return
        if filename_suggestion:
            fs = entry.setdefault("filename_suggestions", [])
            if filename_suggestion not in fs:
                fs.append(filename_suggestion)
                del fs[:-5]  # keep last few
        if directory_suggestion:
            ds = entry.setdefault("directory_suggestions", [])
            if directory_suggestion not in ds:
                ds.append(directory_suggestion)
                del ds[:-5]

    # ---- OCR error learning ------------------------------------------------
    def learn_ocr_correction(self, wrong: str, right: str) -> None:
        if not wrong or not right or wrong == right:
            return
        key = f"{wrong}=>{right}"
        entry = self.data["ocr_corrections"].get(key, {"count": 0, "wrong": wrong, "right": right})
        entry["count"] += 1
        self.data["ocr_corrections"][key] = entry

    def apply_ocr_corrections(self, text: str, min_occurrences: int = 2) -> Tuple[str, List[str]]:
        """Applies only corrections seen >= min_occurrences times, to avoid
        acting on a one-off guess. Returns (corrected_text, applied_list)."""
        if not text:
            return text, []
        applied = []
        for entry in self.data["ocr_corrections"].values():
            if entry["count"] < min_occurrences:
                continue
            wrong, right = entry["wrong"], entry["right"]
            if wrong and wrong in text:
                text = text.replace(wrong, right)
                applied.append(f"{wrong} -> {right}")
        return text, applied

    # ---- prompt hints -------------------------------------------------------
    def as_prompt_hints(self) -> str:
        lines = []
        pn = self.known_values("patient_names")
        cn = self.known_values("company_names")
        rt = self.known_values("report_types")
        mv = self.known_values("metric_vocabulary")
        if pn:
            lines.append(f"Known patient name(s) from prior documents: {', '.join(pn)}")
        if cn:
            lines.append(f"Known company/institution name(s): {', '.join(cn)}")
        if rt:
            lines.append(f"Known report types seen before: {', '.join(rt)}")
        if mv:
            lines.append(f"Known metric names seen before (reuse exact spelling if this matches): {', '.join(mv)}")
        if not lines:
            return ""
        return (
            "Context from previously processed documents belonging to the SAME person "
            "(use to keep naming consistent, but do not invent data not present in this document):\n"
            + "\n".join(f"- {l}" for l in lines)
        )

    def update_from_analysis(self, analysis: Dict[str, Any]) -> Dict[str, str]:
        """Learns from a fresh (non-error) analysis result. Returns a map of
        field -> canonical value actually used (post-normalization)."""
        meta = analysis.get("report_metadata", {})
        result = {}
        if meta.get("patient"):
            result["patient"] = self.normalize_and_learn("patient_names", meta["patient"])
        if meta.get("company_name"):
            result["company_name"] = self.normalize_and_learn("company_names", meta["company_name"])
        if meta.get("report_type"):
            canon_rt = self.normalize_and_learn("report_types", meta["report_type"])
            result["report_type"] = canon_rt
            self.register_report_type_hints(
                canon_rt,
                analysis.get("file_name_suggestion", ""),
                analysis.get("directory_suggestion", ""),
            )
        canon_metrics = []
        for m in analysis.get("key_metrics", []):
            name = m.get("metric_name", "")
            if not name:
                continue
            canon = self.normalize_and_learn("metric_vocabulary", name)
            self.register_metric_unit(canon, m.get("unit", ""))
            canon_metrics.append(canon)
        if canon_metrics:
            result["key_metrics"] = canon_metrics
        self.data["stats"]["total_files_learned"] += 1
        return result

# ----------------------------------------------------------------------
# File cache -- skip re-OCR / re-LLM on unchanged files across runs
# ----------------------------------------------------------------------
class FileCache:
    def __init__(self, path: str):
        self.path = path
        self.data = safe_load_json(path, {"files": {}})

    def get(self, file_hash: str) -> Optional[Dict[str, Any]]:
        return self.data["files"].get(file_hash)

    def put(self, file_hash: str, extraction: Dict[str, Any], analysis: Optional[Dict[str, Any]]) -> None:
        self.data["files"][file_hash] = {
            "extraction": extraction,
            "analysis": analysis,
            "cached_at": datetime.now().isoformat(),
        }

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

# ----------------------------------------------------------------------
# Image preprocessing (new)
# ----------------------------------------------------------------------
def _pil_fallback_preprocess(image: Image.Image, target_width: int) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")  # grayscale
    if image.width < target_width:
        ratio = target_width / float(image.width)
        image = image.resize((target_width, int(image.height * ratio)), Image.LANCZOS)
    image = ImageOps.autocontrast(image, cutoff=1)
    image = image.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.2)
    return image

def _cv2_deskew(gray_np: "np.ndarray") -> "np.ndarray":
    # threshold to find text mask, estimate skew angle from the minimum-area
    # bounding rect of foreground pixels, then rotate to correct
    thresh = cv2.threshold(gray_np, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return gray_np
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.3:  # not worth rotating
        return gray_np
    (h, w) = gray_np.shape
    center = (w // 2, h // 2)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(gray_np, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated

def _cv2_preprocess(image: Image.Image, target_width: int) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    np_img = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)

    h, w = gray.shape
    if w < target_width:
        scale = target_width / float(w)
        gray = cv2.resize(gray, (target_width, int(h * scale)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.fastNlMeansDenoising(gray, h=10)
    gray = _cv2_deskew(gray)
    gray = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return Image.fromarray(gray)

def preprocess_image(image: Image.Image, target_width: int = 1800, enabled: bool = True) -> Image.Image:
    if not enabled:
        return ImageOps.exif_transpose(image)
    try:
        if HAS_CV2:
            return _cv2_preprocess(image, target_width)
        return _pil_fallback_preprocess(image, target_width)
    except Exception as e:
        logging.warning(f"Preprocessing failed, using original image: {e}")
        return ImageOps.exif_transpose(image)

def ocr_with_confidence(image: Image.Image, ocr_lang: str) -> Tuple[str, float]:
    """Runs OCR twice-in-one: image_to_data gives us both text and per-word
    confidences so we get a quality signal for free instead of a second pass."""
    data = pytesseract.image_to_data(image, lang=ocr_lang, output_type=Output.DICT)
    words, confs = [], []
    for i, word in enumerate(data.get("text", [])):
        word = word.strip()
        conf = data.get("conf", ["-1"])[i]
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            conf = -1.0
        if word:
            words.append(word)
            if conf >= 0:
                confs.append(conf)
    text = " ".join(words)
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return text, mean_conf

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
    atomic_write_json(output_path, index)

def extract_text_from_image(image_path: str, ocr_lang: str = "por+eng",
                             preprocessing_enabled: bool = True,
                             target_width: int = 1800) -> Dict[str, Any]:
    result = {
        "filename": os.path.basename(image_path),
        "filepath": image_path,
        "extraction_time": datetime.now().isoformat(),
        "total_pages": 1,
        "pages": [],
        "metadata": {},
        "text_summary": "",
        "ocr_confidence": 0.0,
        "preprocessing_applied": preprocessing_enabled,
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

        original_format = image.format
        processed = preprocess_image(image, target_width=target_width, enabled=preprocessing_enabled)

        ocr_text, mean_conf = ocr_with_confidence(processed, ocr_lang)
        ocr_text = clean_ocr_text(ocr_text)

        page_info = {
            "page_number": 1,
            "text": ocr_text,
            "tables_count": 0,
            "tables": []
        }
        result["pages"].append(page_info)
        result["ocr_confidence"] = round(mean_conf, 2)

        stat = os.stat(image_path)
        result["metadata"] = {
            "creation_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modification_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "image_format": original_format,
            "width": image.width,
            "height": image.height,
        }
        result["text_summary"] = ocr_text[:5000]
    except Exception as e:
        result["error"] = str(e)
        logging.error(f"OCR error on {image_path}: {e}")
    return result

# ----------------------------------------------------------------------
# LLM Analyzer
# ----------------------------------------------------------------------
class LLMAnalyzer:
    def __init__(self, config: Dict[str, Any], knowledge_base: Optional[KnowledgeBase] = None):
        self.provider = config.get("llm_provider", "ollama").lower()
        self.temperature = config.get("llm_temperature", 0.1)
        self.max_tokens = config.get("llm_max_tokens", 8192)
        self.client = None
        self.kb = knowledge_base

        if self.provider == "ollama":
            self.model = config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])
            base_url = config.get("ollama_base_url", DEFAULT_CONFIG["ollama_base_url"])
            self.client = OpenAI(api_key="ollama", base_url=base_url)
            self.supports_json_mode = False
        elif self.provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("DeepSeek API key required. Set DEEPSEEK_API_KEY.")
            self.model = config.get("llm_model", "deepseek-v4")
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

        # apply any high-confidence, previously-learned OCR corrections before
        # sending to the LLM -- cheap, deterministic wins on recurring garbling
        applied_corrections = []
        if self.kb is not None:
            ocr_text, applied_corrections = self.kb.apply_ocr_corrections(ocr_text)

        ocr_text = truncate_text(ocr_text, self.max_ocr_chars)
        kb_hints = self.kb.as_prompt_hints() if self.kb is not None else ""

        prompt = f"""
        Analyze the following text extracted from an image (OCR may contain errors).
        The document is likely a report (medical, financial, invoice, etc.) belonging
        to one specific person, as part of a recurring set of documents.
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
        {"Use the exact spelling of any known name/report-type/metric below when this document clearly matches one of them; otherwise extract what is actually written." if kb_hints else ""}
        {kb_hints}

        Output ONLY the JSON object, no other text (including no reasoning or explanation).

        FILENAME: {filename}
        OCR TEXT:
        {ocr_text}
        """
        return prompt, applied_corrections

    def analyze_report(self, extraction_result: Dict[str, Any]) -> Dict[str, Any]:
        max_retries = 2
        last_applied_corrections = []
        for attempt in range(max_retries + 1):
            prompt, applied_corrections = self._create_analysis_prompt(extraction_result)
            last_applied_corrections = applied_corrections
            messages = [
                {"role": "system", "content": "You are a data extraction assistant. Output **only** a valid JSON object. Do not include any extra text, explanations, reasoning, or markdown."},
                {"role": "user", "content": prompt}
            ]
            if attempt > 0:
                self.max_tokens = 8192
            try:
                raw = self._chat_completion(messages, use_json=self.supports_json_mode)
                content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                reasoning = raw.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")

                parsed = self._parse_json_from_text(content)
                if not parsed and not content and reasoning:
                    logging.warning("Content empty, attempting to parse reasoning.")
                    parsed = self._parse_json_from_text(reasoning)
                    extracted_from = "reasoning"
                else:
                    extracted_from = "content"

                if parsed:
                    parsed["llm_analysis_metadata"] = {
                        "model": self.model,
                        "provider": self.provider,
                        "analysis_time": datetime.now().isoformat(),
                        "attempt": attempt + 1,
                        "original_filename": extraction_result.get("filename", "unknown"),
                        "ocr_confidence": extraction_result.get("ocr_confidence", None),
                        "pre_llm_corrections_applied": last_applied_corrections,
                        "extracted_from": extracted_from,
                    }
                    return parsed

                logging.warning(f"Attempt {attempt+1} returned non-JSON content. Snippet: {content[:200]}")
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
                "original_filename": extraction_result.get("filename", "unknown"),
                "ocr_confidence": extraction_result.get("ocr_confidence", None),
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
# Cross-file refinement (new)
# ----------------------------------------------------------------------
def _group_key(analysis: Dict[str, Any]) -> Tuple[str, str]:
    meta = analysis.get("report_metadata", {})
    return (meta.get("report_type", "").strip().lower(), meta.get("period_covered", "").strip().lower())

def _fuzzy_group(analysis_results: Dict[str, Dict[str, Any]], threshold: float) -> List[List[str]]:
    """Groups file paths whose report_type + period are near-identical, so a
    well-extracted file can help repair a poorly-extracted sibling from the
    same recurring form."""
    paths = [p for p, a in analysis_results.items() if "error" not in a]
    groups: List[List[str]] = []
    assigned = set()
    for p in paths:
        if p in assigned:
            continue
        group = [p]
        assigned.add(p)
        key_p = analysis_results[p].get("report_metadata", {})
        for q in paths:
            if q in assigned:
                continue
            key_q = analysis_results[q].get("report_metadata", {})
            rt_sim = similarity(key_p.get("report_type", ""), key_q.get("report_type", ""))
            period_sim = similarity(key_p.get("period_covered", ""), key_q.get("period_covered", ""))
            if rt_sim >= threshold and period_sim >= threshold:
                group.append(q)
                assigned.add(q)
        groups.append(group)
    return groups

def refine_analysis_results(analysis_results: Dict[str, Dict[str, Any]],
                             extraction_results: Dict[str, Dict[str, Any]],
                             kb: KnowledgeBase,
                             config: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Metadata-only consensus refinement. For each group of documents that look
    like the same recurring report type + period:
      - textual metadata fields (patient, company_name, report_type,
        content_summary wording) are reconciled towards the value seen in the
        highest-OCR-confidence sibling and towards KB canonical spelling
      - metric_name spelling is canonicalized via the KB; metric VALUES and
        UNITS are left untouched -- those are per-document facts, not
        something to infer from another file
      - anything changed is logged with before/after and the reason, so the
        refinement is fully auditable rather than a silent overwrite
    """
    trusted = config["min_ocr_confidence_trusted"]
    min_occ = config["correction_min_occurrences"]

    refined: Dict[str, Dict[str, Any]] = {p: json.loads(json.dumps(a)) for p, a in analysis_results.items()}
    change_log: List[Dict[str, Any]] = []

    groups = _fuzzy_group(analysis_results, config["fuzzy_match_threshold"])

    for group in groups:
        if len(group) < 2:
            # still worth applying KB text corrections to a lone file
            for p in group:
                _apply_text_corrections(refined[p], kb, min_occ, change_log, p)
            continue

        # rank group members by OCR confidence to find the most trustworthy "anchor"
        ranked = sorted(
            group,
            key=lambda p: extraction_results.get(p, {}).get("ocr_confidence", 0.0),
            reverse=True
        )
        anchor_path = ranked[0]
        anchor_meta = refined[anchor_path].get("report_metadata", {})
        anchor_conf = extraction_results.get(anchor_path, {}).get("ocr_confidence", 0.0)

        for p in group:
            meta = refined[p].get("report_metadata", {})
            file_conf = extraction_results.get(p, {}).get("ocr_confidence", 0.0)
            for field in ("patient", "company_name", "report_type"):
                current = (meta.get(field) or "").strip()
                anchor_val = (anchor_meta.get(field) or "").strip()
                if not anchor_val:
                    continue
                if not current:
                    # fill a genuinely missing metadata field from a trusted sibling
                    if anchor_conf >= trusted and p != anchor_path:
                        meta[field] = anchor_val
                        change_log.append({
                            "file": p, "field": field, "before": "", "after": anchor_val,
                            "reason": f"filled from higher-confidence sibling ({os.path.basename(anchor_path)})"
                        })
                elif similarity(current, anchor_val) >= config["fuzzy_match_threshold"] and current != anchor_val:
                    # same value, different spelling/OCR noise -> converge on the
                    # more trustworthy version (learns the correction too)
                    if anchor_conf >= file_conf:
                        meta[field] = anchor_val
                        kb.learn_ocr_correction(current, anchor_val)
                        change_log.append({
                            "file": p, "field": field, "before": current, "after": anchor_val,
                            "reason": f"reconciled spelling with higher-confidence sibling ({os.path.basename(anchor_path)})"
                        })
            refined[p]["report_metadata"] = meta

            # canonicalize metric NAMES only (never touch value/unit)
            for m in refined[p].get("key_metrics", []):
                name = m.get("metric_name", "")
                if not name:
                    continue
                canonical = kb.normalize_and_learn("metric_vocabulary", name)
                if canonical != name:
                    change_log.append({
                        "file": p, "field": "key_metrics.metric_name",
                        "before": name, "after": canonical,
                        "reason": "canonicalized against known metric vocabulary"
                    })
                    m["metric_name"] = canonical

            _apply_text_corrections(refined[p], kb, min_occ, change_log, p)

    refinement_report = {
        "generated_at": datetime.now().isoformat(),
        "groups_found": len(groups),
        "files_with_changes": len({c["file"] for c in change_log}),
        "total_changes": len(change_log),
        "changes": change_log,
    }
    return refined, refinement_report

def _apply_text_corrections(analysis: Dict[str, Any], kb: KnowledgeBase, min_occ: int,
                             change_log: List[Dict[str, Any]], path: str) -> None:
    summary = analysis.get("content_summary", "")
    if summary:
        corrected, applied = kb.apply_ocr_corrections(summary, min_occ)
        if applied:
            change_log.append({
                "file": path, "field": "content_summary",
                "before": summary, "after": corrected,
                "reason": f"applied learned OCR corrections: {', '.join(applied)}"
            })
            analysis["content_summary"] = corrected

# ----------------------------------------------------------------------
# CSV Conversion
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
# File renaming
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
    os.makedirs(config["output_root"], exist_ok=True)
    logger = setup_logging(config["output_root"], config["log_level"])
    workspace = os.path.join(config["output_root"], config["working_dir"])
    os.makedirs(workspace, exist_ok=True)

    config_path = os.path.join(workspace, "pipeline_config.json")
    atomic_write_json(config_path, config)

    logger.info("=" * 80)
    logger.info("Image-Based Report Processing Pipeline (Learning Edition)")
    logger.info(f"Input: {config['input_root']}  Output: {workspace}")
    logger.info(f"Learning: {config['enable_learning']}  Cache: {config['enable_cache']}  "
                f"Preprocessing: {config['enable_preprocessing']}  Refinement: {config['enable_refinement']}")
    logger.info("=" * 80)

    pipeline = {"start_time": datetime.now().isoformat(), "steps": {}, "status": "running"}

    # persistent stores live in output_root so they survive across runs / workspaces
    kb_path = os.path.join(config["output_root"], config["knowledge_base_file"])
    cache_path = os.path.join(config["output_root"], config["file_cache_file"])
    kb = KnowledgeBase(kb_path, threshold=config["fuzzy_match_threshold"]) if config["enable_learning"] else None
    cache = FileCache(cache_path) if config["enable_cache"] else None
    if kb is not None:
        kb.data["stats"]["total_runs"] += 1

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

    # Step 2: OCR (with cache + preprocessing)
    logger.info("Step 2: OCR extraction...")
    extraction_dir = os.path.join(workspace, "extractions")
    os.makedirs(extraction_dir, exist_ok=True)
    extraction_results: Dict[str, Dict[str, Any]] = {}
    cached_extraction_hits = 0
    for i, fi in enumerate(file_index, 1):
        logger.info(f"OCR {i}/{len(file_index)}: {fi['filename']}")
        cached = cache.get(fi["file_hash"]) if (cache and not config["force_reprocess"]) else None
        if cached and cached.get("extraction"):
            extr = cached["extraction"]
            cached_extraction_hits += 1
            logger.info(f"  -> using cached OCR result (unchanged since a prior run)")
        else:
            extr = extract_text_from_image(
                fi["full_path"], ocr_lang=config["ocr_language"],
                preprocessing_enabled=config["enable_preprocessing"],
                target_width=config["upscale_target_width"],
            )
        extraction_results[fi["full_path"]] = extr
        ext_path = os.path.join(extraction_dir, f"{fi['filename']}_extraction.json")
        atomic_write_json(ext_path, extr)
        fi["extraction_path"] = ext_path
        fi["extraction_status"] = "error" if extr.get("error") else "completed"
        fi["ocr_confidence"] = extr.get("ocr_confidence", 0.0)
    save_index(file_index, index_path)
    pipeline["steps"]["extraction"] = {
        "status": "completed", "processed": len(extraction_results),
        "cache_hits": cached_extraction_hits
    }

    # Step 3: LLM Analysis (with cache + KB hints)
    analysis_results: Dict[str, Dict[str, Any]] = {}
    llm_provider = config.get("llm_provider", "none").lower()
    cached_analysis_hits = 0
    if llm_provider != "none":
        logger.info("Step 3: LLM analysis using %s...", llm_provider)
        analysis_dir = os.path.join(workspace, "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        try:
            analyzer = LLMAnalyzer(config, knowledge_base=kb)
        except Exception as e:
            logger.error(f"LLM init failed: {e}")
            pipeline["steps"]["llm_analysis"] = {"status": "failed", "error": str(e)}
        else:
            for i, fi in enumerate(file_index, 1):
                path = fi["full_path"]
                extr = extraction_results[path]
                if extr.get("error"):
                    logger.warning(f"Skipping {os.path.basename(path)} due to OCR error")
                    continue

                cached = cache.get(fi["file_hash"]) if (cache and not config["force_reprocess"]) else None
                if cached and cached.get("analysis") and "error" not in cached["analysis"]:
                    analysis = cached["analysis"]
                    cached_analysis_hits += 1
                    logger.info(f"Analysis {i}/{len(file_index)}: {os.path.basename(path)} -> cached")
                else:
                    logger.info(f"Analyzing {i}/{len(file_index)}: {os.path.basename(path)}")
                    analysis = analyzer.analyze_report(extr)
                    time.sleep(1)

                if kb is not None and "error" not in analysis:
                    kb.update_from_analysis(analysis)

                analysis_results[path] = analysis
                analysis_path = os.path.join(analysis_dir, f"{os.path.basename(path)}_analysis.json")
                atomic_write_json(analysis_path, analysis)

                if cache is not None:
                    cache.put(fi["file_hash"], extr, analysis)

            pipeline["steps"]["llm_analysis"] = {
                "status": "completed", "analyzed": len(analysis_results),
                "cache_hits": cached_analysis_hits
            }
    else:
        logger.info("Step 3: Skipping LLM analysis")
        pipeline["steps"]["llm_analysis"] = {"status": "skipped"}

    if cache is not None:
        cache.save()
    if kb is not None:
        kb.save()

    # Step 4: CSV (from raw analysis, pre-refinement -- kept for comparison)
    logger.info("Step 4: Converting to CSV (raw)...")
    csv_dir = os.path.join(workspace, "csv_output")
    os.makedirs(csv_dir, exist_ok=True)
    csv_files = convert_to_csv(analysis_results, csv_dir)
    pipeline["steps"]["csv_conversion"] = {"status": "completed", "files": list(csv_files.keys())}
    logger.info(f"CSV files: {list(csv_files.keys())}")

    # Step 5: File renaming
    if llm_provider != "none" and analysis_results:
        logger.info("Step 5: Planning file renaming...")
        try:
            analyzer = LLMAnalyzer(config, knowledge_base=kb)
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
                new_name = suggested_name if suggested_name else f"{base}.pdf"
                new_rel = os.path.join(suggested_dir, new_name)
                fallback_mapping.append({
                    "old_path": old_rel, "new_path": new_rel, "reason": "fallback (LLM failed)"
                })
            renaming_plan = {"file_mapping": fallback_mapping}

        plan_path = os.path.join(workspace, "renaming_plan.json")
        atomic_write_json(plan_path, renaming_plan)

        if not config["dry_run"]:
            logger.info("Applying renaming...")
            rename_results = apply_file_renaming(file_index, renaming_plan, config["input_root"], dry_run=False)
            res_path = os.path.join(workspace, "renaming_results.json")
            atomic_write_json(res_path, rename_results)
            pipeline["steps"]["file_reorganization"] = {
                "status": "completed", "renamed": rename_results["renamed"], "errors": len(rename_results["errors"])
            }
            logger.info(f"Renamed {rename_results['renamed']} files")
        else:
            logger.info("Dry run: renaming not applied")
            pipeline["steps"]["file_reorganization"] = {"status": "dry_run"}
    else:
        logger.info("Step 5: Skipping file renaming")
        pipeline["steps"]["file_reorganization"] = {"status": "skipped"}

    # Step 6: Cross-file refinement (new)
    refined_results = analysis_results
    if config["enable_refinement"] and kb is not None and analysis_results:
        logger.info("Step 6: Cross-file refinement using knowledge base...")
        refined_results, refinement_report = refine_analysis_results(
            analysis_results, extraction_results, kb, config
        )
        refine_dir = os.path.join(workspace, "analysis_refined")
        os.makedirs(refine_dir, exist_ok=True)
        for path, analysis in refined_results.items():
            out_path = os.path.join(refine_dir, f"{os.path.basename(path)}_analysis_refined.json")
            atomic_write_json(out_path, analysis)
        report_path = os.path.join(workspace, "refinement_report.json")
        atomic_write_json(report_path, refinement_report)
        kb.save()  # refinement can learn new corrections too

        refined_csv_dir = os.path.join(workspace, "csv_output_refined")
        os.makedirs(refined_csv_dir, exist_ok=True)
        refined_csv_files = convert_to_csv(refined_results, refined_csv_dir)

        pipeline["steps"]["refinement"] = {
            "status": "completed",
            "groups_found": refinement_report["groups_found"],
            "files_with_changes": refinement_report["files_with_changes"],
            "total_changes": refinement_report["total_changes"],
            "refined_csv_files": list(refined_csv_files.keys()),
        }
        logger.info(
            f"Refinement: {refinement_report['total_changes']} field(s) corrected across "
            f"{refinement_report['files_with_changes']} file(s)"
        )
    else:
        logger.info("Step 6: Skipping refinement (disabled or no analysis results)")
        pipeline["steps"]["refinement"] = {"status": "skipped"}

    # Step 7: Summary
    logger.info("Step 7: Generating summary...")
    summary = {
        "pipeline_execution": {
            "start_time": pipeline["start_time"],
            "end_time": datetime.now().isoformat(),
            "total_files": len(file_index)
        },
        "file_statistics": {
            "total_images": len(file_index),
            "successful_ocr": sum(1 for e in extraction_results.values() if not e.get("error")),
            "successful_analyses": sum(1 for a in analysis_results.values() if "error" not in a),
            "avg_ocr_confidence": round(
                sum(e.get("ocr_confidence", 0.0) for e in extraction_results.values()) / max(len(extraction_results), 1), 2
            ),
            "ocr_cache_hits": cached_extraction_hits,
            "analysis_cache_hits": cached_analysis_hits,
        },
        "knowledge_base": {
            "path": kb_path if kb is not None else None,
            "known_patients": kb.known_values("patient_names") if kb is not None else [],
            "known_report_types": kb.known_values("report_types") if kb is not None else [],
            "known_metrics": kb.known_values("metric_vocabulary") if kb is not None else [],
            "total_runs": kb.data["stats"]["total_runs"] if kb is not None else None,
        },
        "outputs": {
            "workspace": workspace,
            "index_file": index_path,
            "extractions": extraction_dir,
            "analysis": os.path.join(workspace, "analysis") if analysis_results else None,
            "analysis_refined": os.path.join(workspace, "analysis_refined") if config["enable_refinement"] else None,
            "csv_files": csv_dir,
            "csv_files_refined": os.path.join(workspace, "csv_output_refined") if config["enable_refinement"] else None,
        }
    }
    summary_path = os.path.join(workspace, "pipeline_summary.json")
    atomic_write_json(summary_path, summary)

    human_summary = f"""
    IMAGE PROCESSING PIPELINE SUMMARY
    =================================
    Time: {summary['pipeline_execution']['start_time']} - {summary['pipeline_execution']['end_time']}
    Images: {summary['file_statistics']['total_images']}
    Successful OCR: {summary['file_statistics']['successful_ocr']}  (avg confidence: {summary['file_statistics']['avg_ocr_confidence']})
    Successful Analyses: {summary['file_statistics']['successful_analyses']}
    Cache hits: OCR={summary['file_statistics']['ocr_cache_hits']}  Analysis={summary['file_statistics']['analysis_cache_hits']}
    Refinement: {pipeline['steps']['refinement']}
    Known patients: {summary['knowledge_base']['known_patients']}
    Known report types: {summary['knowledge_base']['known_report_types']}
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
    parser = argparse.ArgumentParser(description="Image-Based Report Processing Pipeline (Learning Edition)")
    parser.add_argument("--input", "-i", default="./IBSCO")
    parser.add_argument("--output", "-o", default="./pdf_processed_results")
    parser.add_argument("--llm-provider", choices=["deepseek", "ollama", "openai", "none"])
    parser.add_argument("--llm-model", help="LLM model name (e.g., llama3.1, deepseek-v4)")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max tokens for LLM output")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--config", "-c", help="JSON config file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--kb-path", help="Override knowledge base filename (relative to output root)")
    parser.add_argument("--no-learning", action="store_true", help="Disable the persistent knowledge base")
    parser.add_argument("--no-cache", action="store_true", help="Disable the file hash cache")
    parser.add_argument("--no-preprocessing", action="store_true", help="Disable image preprocessing before OCR")
    parser.add_argument("--no-refinement", action="store_true", help="Disable the cross-file refinement pass")
    parser.add_argument("--force-reprocess", action="store_true", help="Ignore cache, reprocess every file")
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
    if args.kb_path:
        config["knowledge_base_file"] = args.kb_path
    if args.no_learning:
        config["enable_learning"] = False
    if args.no_cache:
        config["enable_cache"] = False
    if args.no_preprocessing:
        config["enable_preprocessing"] = False
    if args.no_refinement:
        config["enable_refinement"] = False
    if args.force_reprocess:
        config["force_reprocess"] = True

    results = run_pipeline(config)
    sys.exit(0 if results.get("status") == "completed" else 1)

if __name__ == "__main__":
    main()