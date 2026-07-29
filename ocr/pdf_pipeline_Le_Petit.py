#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Le Petit Handwritten Sales OCR Pipeline

This pipeline:
1. Scans all image files from the screenshots directory
2. Creates an index with file metadata
3. Runs OCR tuned for handwritten Brazilian Portuguese notes
4. Performs per-image DeepSeek analysis to extract structured sales lines
5. Maintains iterative product memory to improve canonical naming over time
6. Produces CSV/JSON structured outputs
7. Runs one final global reconciliation review across all analyzed scans

The pipeline is conservative: it never edits originals and keeps raw OCR +
raw extracted item text for auditability.
"""

import os
import sys
import json
import argparse
import logging
import hashlib
import re
import time
import unicodedata
import shutil
import tempfile
import subprocess
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from PIL import Image, ImageOps, ImageFilter, ImageEnhance

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

try:
    import pytesseract

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

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
    "input_root": "./screenshots/Lê Pétit",
    "output_root": "./llm_enhanced_results",
    "working_dir": "./kate_prioritarios_pipeline",
    "supported_extensions": [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".tif",
        ".tiff",
        ".bmp",
        ".heic",
        ".heif",
    ],
    "llm_model": "deepseek-v4-pro",
    "llm_temperature": 0.1,
    "llm_max_tokens": 4000,
    "ocr_language": "por+eng",
    "ocr_psm": 6,
    "ocr_oem": 1,
    "ocr_fallback_psm": 11,
    "min_product_similarity": 0.84,
    "known_products_limit": 40,
    "api_call_delay_seconds": 1.5,
    "csv_encoding": "utf-8-sig",
    "enable_final_review": True,
    "dry_run": False,
    "log_level": "INFO",
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
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    return logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def calculate_file_hash(filepath: str, algorithm: str = "sha256") -> str:
    """Calculate file hash for uniqueness checking."""
    hash_func = hashlib.new(algorithm)
    with open(filepath, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def save_json(payload: Any, output_path: str) -> None:
    """Save JSON payload with UTF-8 encoding."""
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def sanitize_filename(value: str) -> str:
    """Create filesystem-safe file stem for generated artifacts."""
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    normalized = normalized.strip("._")
    return normalized or "unnamed"


def normalize_whitespace(text: str) -> str:
    """Normalize OCR text without destroying original line-level semantics."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def product_key(name: str) -> str:
    """Create a normalized comparison key for product matching."""
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9 ]+", " ", ascii_text)
    ascii_text = re.sub(r"\s+", " ", ascii_text)
    return ascii_text.strip()


def resolve_unicode_path(path: str) -> str:
    """Resolve path variants that differ only by Unicode normalization."""
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        return expanded

    parent = os.path.dirname(expanded) or "."
    leaf = os.path.basename(expanded)
    if not os.path.isdir(parent):
        return expanded

    leaf_nfd = unicodedata.normalize("NFD", leaf)
    for entry in os.listdir(parent):
        if unicodedata.normalize("NFD", entry) == leaf_nfd:
            return os.path.join(parent, entry)

    return expanded


def _is_heic_path(image_path: str) -> bool:
    return os.path.splitext(image_path)[1].lower() in {".heic", ".heif"}


def _convert_heic_with_sips(image_path: str) -> Optional[str]:
    """Convert HEIC/HEIF into a temporary PNG using macOS sips."""
    if shutil.which("sips") is None:
        return None

    fd, temp_path = tempfile.mkstemp(prefix="heic_", suffix=".png")
    os.close(fd)

    try:
        process = subprocess.run(
            ["sips", "-s", "format", "png", image_path, "--out", temp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None

    return temp_path


def open_image_with_fallback(image_path: str) -> Tuple[Image.Image, Optional[str], str]:
    """Open image directly; for HEIC fallback to temporary PNG conversion on macOS."""
    try:
        image = Image.open(image_path)
        image.load()
        return image, None, "native"
    except Exception as direct_error:
        if _is_heic_path(image_path):
            temp_path = _convert_heic_with_sips(image_path)
            if temp_path:
                image = Image.open(temp_path)
                image.load()
                return image, temp_path, "sips"
        raise direct_error


def best_product_match(candidate: str, known_products: List[str]) -> Tuple[Optional[str], float]:
    """Find the best fuzzy match candidate among canonical product names."""
    best_name = None
    best_ratio = 0.0
    candidate_key = product_key(candidate)
    if not candidate_key:
        return None, 0.0

    for known in known_products:
        ratio = SequenceMatcher(None, candidate_key, product_key(known)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = known

    return best_name, best_ratio


# ----------------------------------------------------------------------
# File scanning and indexing
# ----------------------------------------------------------------------
def scan_image_files(root_dir: str, extensions: List[str]) -> List[Dict[str, Any]]:
    """
    Recursively scan for image files and create index with metadata.
    """
    file_index: List[Dict[str, Any]] = []
    normalized_extensions = tuple(ext.lower() for ext in extensions)

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if not filename.lower().endswith(normalized_extensions):
                continue

            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)

            try:
                stat = os.stat(full_path)
                file_hash = calculate_file_hash(full_path)
                width = None
                height = None
                image_format = "unknown"

                image_handle = None
                temp_path = None
                image_loader = "native"
                try:
                    image_handle, temp_path, image_loader = open_image_with_fallback(full_path)
                    width, height = image_handle.size
                    image_format = image_handle.format or "unknown"
                finally:
                    if image_handle is not None:
                        image_handle.close()
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)

                file_info = {
                    "full_path": full_path,
                    "relative_path": rel_path,
                    "filename": filename,
                    "directory": dirpath,
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_hash": file_hash,
                    "file_type": "IMAGE",
                    "image_format": image_format,
                    "image_loader": image_loader,
                    "width": width,
                    "height": height,
                    "status": "pending",
                }
                file_index.append(file_info)
            except Exception as error:
                logging.error("Error indexing file %s: %s", full_path, error)

    return sorted(file_index, key=lambda item: item["relative_path"])


# ----------------------------------------------------------------------
# OCR extraction
# ----------------------------------------------------------------------
def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """Apply simple preprocessing to improve handwritten OCR robustness."""
    image_handle, temp_path, _ = open_image_with_fallback(image_path)
    try:
        image = image_handle.convert("L")
    finally:
        image_handle.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = ImageEnhance.Contrast(image).enhance(1.6)

    # Keep threshold conservative to avoid erasing faint handwriting strokes.
    image = image.point(lambda pixel: 255 if pixel > 160 else 0)
    return image


def run_ocr(image: Image.Image, language: str, psm: int, oem: int) -> Tuple[str, Optional[float]]:
    """Run Tesseract OCR and return extracted text and mean confidence."""
    config = f"--oem {oem} --psm {psm}"
    text = pytesseract.image_to_string(image, lang=language, config=config)

    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    confidences: List[float] = []
    for value in data.get("conf", []):
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            confidences.append(confidence)

    mean_confidence = None
    if confidences:
        mean_confidence = round(sum(confidences) / len(confidences), 2)

    return text, mean_confidence


def extract_text_from_image(image_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract text from image using Tesseract OCR configured for Brazilian Portuguese handwriting.
    """
    result: Dict[str, Any] = {
        "filename": os.path.basename(image_path),
        "filepath": image_path,
        "extraction_time": datetime.now().isoformat(),
        "ocr_engine": "tesseract",
        "ocr_language": config["ocr_language"],
        "text_raw": "",
        "text_normalized": "",
        "line_count": 0,
        "token_count": 0,
        "average_confidence": None,
        "ocr_attempts": [],
        "error": None,
    }

    if not HAS_TESSERACT:
        result["error"] = (
            "pytesseract is not available. Install dependencies and ensure tesseract binary is installed."
        )
        return result

    try:
        processed = preprocess_image_for_ocr(image_path)

        primary_psm = int(config.get("ocr_psm", 6))
        fallback_psm = int(config.get("ocr_fallback_psm", 11))
        oem = int(config.get("ocr_oem", 1))
        language = config.get("ocr_language", "por+eng")

        text, confidence = run_ocr(processed, language=language, psm=primary_psm, oem=oem)
        result["ocr_attempts"].append(
            {
                "psm": primary_psm,
                "oem": oem,
                "text_length": len(text or ""),
                "average_confidence": confidence,
            }
        )

        # If OCR is sparse, retry with a more line-fragment tolerant segmentation mode.
        if len((text or "").strip()) < 20 and fallback_psm != primary_psm:
            fallback_text, fallback_confidence = run_ocr(
                processed,
                language=language,
                psm=fallback_psm,
                oem=oem,
            )
            result["ocr_attempts"].append(
                {
                    "psm": fallback_psm,
                    "oem": oem,
                    "text_length": len(fallback_text or ""),
                    "average_confidence": fallback_confidence,
                }
            )

            if len((fallback_text or "").strip()) > len((text or "").strip()):
                text = fallback_text
                confidence = fallback_confidence

        normalized_text = normalize_whitespace(text or "")
        line_count = len([line for line in normalized_text.split("\n") if line.strip()])
        token_count = len(re.findall(r"\S+", normalized_text))

        result.update(
            {
                "text_raw": text or "",
                "text_normalized": normalized_text,
                "line_count": line_count,
                "token_count": token_count,
                "average_confidence": confidence,
            }
        )
    except Exception as error:
        result["error"] = str(error)
        logging.error("Error extracting text from image %s: %s", image_path, error)

    return result


# ----------------------------------------------------------------------
# LLM integration
# ----------------------------------------------------------------------
class DeepSeekSalesAnalyzer:
    """Client for DeepSeek LLM API specialized for handwritten sales-note extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ):
        self.api_key = api_key or DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError("DeepSeek API key not found. Set DEEPSEEK_API_KEY environment variable.")

        preferred_model = model or DEEPSEEK_MODEL or DEFAULT_CONFIG["llm_model"]
        self.model = resolve_deepseek_model(preferred_model)
        self.temperature = temperature
        self.max_tokens = max_tokens

        if HAS_OPENAI:
            self.client = OpenAI(api_key=self.api_key, base_url=DEEPSEEK_BASE_URL)
        else:
            self.client = None

    def _chat_json(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Call DeepSeek and parse response as JSON with resilient fallback."""
        result_text = ""
        max_tokens = max_tokens or self.max_tokens

        if HAS_OPENAI and self.client:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            result_text = response.choices[0].message.content or "{}"
        else:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result_text = response.json()["choices"][0]["message"]["content"]

        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", result_text, flags=re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            raise ValueError("DeepSeek response was not valid JSON")

    def analyze_sales_scan(
        self,
        extraction: Dict[str, Any],
        known_products: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze one OCR extraction into structured sales data."""
        system_prompt = (
            "You are an expert at extracting handwritten Brazilian Portuguese sales notes. "
            "You must be conservative and avoid hallucinations. Return only valid JSON."
        )

        user_prompt = f"""
Analyze this OCR text from a small Brazilian business handwritten sales scan.

RULES:
- Keep original evidence: preserve raw line snippets for each item.
- Do not invent values.
- If uncertain, set needs_review=true and explain in notes.
- Use known recurring products only when similarity is clear.
- Never silently overwrite uncertain names with confident-looking guesses.

KNOWN RECURRING PRODUCTS (from earlier scans):
{json.dumps(known_products, ensure_ascii=False, indent=2)}

SOURCE FILE: {extraction.get("filename", "unknown")}
OCR CONFIDENCE: {extraction.get("average_confidence")}

OCR TEXT:
{extraction.get("text_normalized", "")[:12000]}

Return JSON exactly in this schema:
{{
  "document_metadata": {{
    "document_type": "sales_note|receipt|inventory_note|unknown",
    "document_date": "string",
    "merchant": "string",
    "confidence_score": 0.0
  }},
  "items": [
    {{
      "line_id": 1,
      "raw_item_text": "string",
      "product_name_raw": "string",
      "product_name_canonical": "string",
      "quantity": "string",
      "unit": "string",
      "unit_price": "string",
      "line_total": "string",
      "confidence": 0.0,
      "needs_review": false,
      "notes": "string"
    }}
  ],
  "totals": {{
    "subtotal": "string",
    "discount": "string",
    "grand_total": "string",
    "currency": "BRL"
  }},
  "observed_product_candidates": ["string"],
  "quality_flags": ["string"],
  "content_summary": "string"
}}
"""

        analysis_result = self._chat_json(system_prompt, user_prompt)
        analysis_result["llm_analysis_metadata"] = {
            "model": self.model,
            "analysis_time": datetime.now().isoformat(),
            "original_filename": extraction.get("filename", "unknown"),
            "source_confidence": extraction.get("average_confidence"),
        }
        return analysis_result

    def run_final_reconciliation(
        self,
        analysis_results: Dict[str, Dict[str, Any]],
        product_memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run one final cross-file consistency review after all scans are processed."""
        system_prompt = (
            "You are a strict QA auditor for OCR+LLM extracted sales data in Brazilian Portuguese. "
            "Be conservative and prefer review flags over speculative correction. Return only JSON."
        )

        compact_docs = []
        for filepath, analysis in analysis_results.items():
            compact_docs.append(
                {
                    "file": os.path.basename(filepath),
                    "items": [
                        {
                            "raw": item.get("product_name_raw", ""),
                            "canonical": item.get("product_name_canonical", ""),
                            "quantity": item.get("quantity", ""),
                            "unit_price": item.get("unit_price", ""),
                            "line_total": item.get("line_total", ""),
                            "needs_review": item.get("needs_review", False),
                        }
                        for item in analysis.get("items", [])
                    ],
                    "totals": analysis.get("totals", {}),
                    "quality_flags": analysis.get("quality_flags", []),
                }
            )

        user_prompt = f"""
Review all extracted documents and produce a single final QA report.

CONSTRAINTS:
- Keep this as audit/reconciliation, not automatic destructive correction.
- Prefer conservative suggestions with confidence labels.
- Highlight risks where OCR+LLM may have forced wrong product normalization.

ITERATIVE PRODUCT MEMORY:
{json.dumps(product_memory, ensure_ascii=False, indent=2)[:15000]}

DOCUMENT EXTRACTIONS:
{json.dumps(compact_docs, ensure_ascii=False, indent=2)[:25000]}

Return JSON in this schema:
{{
  "catalog_reconciliation": [
    {{
      "canonical_name": "string",
      "aliases": ["string"],
      "confidence": 0.0,
      "justification": "string"
    }}
  ],
  "cross_file_anomalies": [
    {{
      "type": "string",
      "description": "string",
      "affected_files": ["string"]
    }}
  ],
  "documents_to_review": [
    {{
      "filename": "string",
      "reason": "string",
      "priority": "high|medium|low"
    }}
  ],
  "consistency_score": 0.0,
  "final_summary": "string"
}}
"""

        final_review = self._chat_json(system_prompt, user_prompt, max_tokens=3500)
        final_review["llm_final_review_metadata"] = {
            "model": self.model,
            "analysis_time": datetime.now().isoformat(),
            "documents_reviewed": len(analysis_results),
        }
        return final_review


# ----------------------------------------------------------------------
# Product memory and CSV conversion
# ----------------------------------------------------------------------
def init_product_memory() -> Dict[str, Any]:
    """Initialize structure for iterative product memory across scans."""
    return {
        "catalog": {},
        "alias_to_canonical": {},
        "events": [],
    }


def top_known_products(product_memory: Dict[str, Any], limit: int = 40) -> List[Dict[str, Any]]:
    """Expose the top canonical products for in-context prompt guidance."""
    catalog = product_memory.get("catalog", {})
    ranked = sorted(catalog.items(), key=lambda item: item[1].get("count", 0), reverse=True)
    payload = []

    for canonical, info in ranked[:limit]:
        aliases_sorted = sorted(
            info.get("aliases", {}).items(),
            key=lambda alias_item: alias_item[1],
            reverse=True,
        )
        payload.append(
            {
                "canonical_name": canonical,
                "count": info.get("count", 0),
                "aliases": [alias for alias, _ in aliases_sorted[:8]],
            }
        )

    return payload


def update_product_memory(
    product_memory: Dict[str, Any],
    analysis: Dict[str, Any],
    source_file: str,
    similarity_threshold: float,
) -> Dict[str, Any]:
    """Update recurring product memory from one analysis result."""
    catalog = product_memory.setdefault("catalog", {})
    alias_map = product_memory.setdefault("alias_to_canonical", {})
    events = product_memory.setdefault("events", [])

    known_canonicals = list(catalog.keys())
    for item in analysis.get("items", []):
        raw_name = (item.get("product_name_raw") or "").strip()
        candidate_canonical = (item.get("product_name_canonical") or raw_name).strip()
        if not candidate_canonical:
            continue

        candidate_key = product_key(candidate_canonical)
        if not candidate_key:
            continue

        chosen_canonical = alias_map.get(candidate_key)

        if not chosen_canonical:
            matched_name, ratio = best_product_match(candidate_canonical, known_canonicals)
            if matched_name and ratio >= similarity_threshold:
                chosen_canonical = matched_name
            else:
                chosen_canonical = candidate_canonical

        canonical_entry = catalog.setdefault(
            chosen_canonical,
            {
                "count": 0,
                "aliases": {},
                "source_files": [],
                "last_seen": None,
            },
        )

        canonical_entry["count"] += 1
        canonical_entry["last_seen"] = datetime.now().isoformat()

        if source_file not in canonical_entry["source_files"]:
            canonical_entry["source_files"].append(source_file)

        alias_candidates = [candidate_canonical]
        if raw_name:
            alias_candidates.append(raw_name)

        for alias in alias_candidates:
            alias_clean = alias.strip()
            if not alias_clean:
                continue
            alias_count = canonical_entry["aliases"].get(alias_clean, 0)
            canonical_entry["aliases"][alias_clean] = alias_count + 1
            alias_map[product_key(alias_clean)] = chosen_canonical

        # Keep item canonical field synchronized with accumulated memory.
        item["product_name_canonical"] = chosen_canonical

        events.append(
            {
                "time": datetime.now().isoformat(),
                "source_file": source_file,
                "raw_name": raw_name,
                "candidate_canonical": candidate_canonical,
                "chosen_canonical": chosen_canonical,
            }
        )

    return product_memory


def convert_to_csv(
    analysis_results: Dict[str, Dict[str, Any]],
    product_memory: Dict[str, Any],
    output_dir: str,
    csv_encoding: str,
) -> Dict[str, str]:
    """
    Convert analyzed sales results and product memory to CSV files.
    """
    csv_files: Dict[str, str] = {}

    # Documents-level CSV
    document_rows = []
    for filepath, analysis in analysis_results.items():
        metadata = analysis.get("document_metadata", {})
        items = analysis.get("items", [])
        review_count = sum(1 for item in items if item.get("needs_review"))

        row = {
            "filename": os.path.basename(filepath),
            "filepath": filepath,
            "document_type": metadata.get("document_type", "unknown"),
            "document_date": metadata.get("document_date", ""),
            "merchant": metadata.get("merchant", ""),
            "document_confidence": metadata.get("confidence_score", 0),
            "items_detected": len(items),
            "items_needing_review": review_count,
            "quality_flags": "; ".join(analysis.get("quality_flags", [])),
            "grand_total": analysis.get("totals", {}).get("grand_total", ""),
            "analysis_timestamp": analysis.get("llm_analysis_metadata", {}).get("analysis_time", ""),
        }
        document_rows.append(row)

    if document_rows:
        documents_csv = os.path.join(output_dir, "documents.csv")
        pd.DataFrame(document_rows).to_csv(documents_csv, index=False, encoding=csv_encoding)
        csv_files["documents"] = documents_csv

    # Line-items CSV
    line_item_rows = []
    for filepath, analysis in analysis_results.items():
        filename = os.path.basename(filepath)
        for item in analysis.get("items", []):
            row = {
                "filename": filename,
                "filepath": filepath,
                "line_id": item.get("line_id", ""),
                "raw_item_text": item.get("raw_item_text", ""),
                "product_name_raw": item.get("product_name_raw", ""),
                "product_name_canonical": item.get("product_name_canonical", ""),
                "quantity": item.get("quantity", ""),
                "unit": item.get("unit", ""),
                "unit_price": item.get("unit_price", ""),
                "line_total": item.get("line_total", ""),
                "confidence": item.get("confidence", ""),
                "needs_review": item.get("needs_review", False),
                "notes": item.get("notes", ""),
            }
            line_item_rows.append(row)

    if line_item_rows:
        line_items_csv = os.path.join(output_dir, "line_items.csv")
        pd.DataFrame(line_item_rows).to_csv(line_items_csv, index=False, encoding=csv_encoding)
        csv_files["line_items"] = line_items_csv

    # Product catalog CSV
    product_rows = []
    for canonical, info in product_memory.get("catalog", {}).items():
        aliases = sorted(info.get("aliases", {}).items(), key=lambda item: item[1], reverse=True)
        row = {
            "canonical_name": canonical,
            "occurrences": info.get("count", 0),
            "aliases": "; ".join(alias for alias, _ in aliases),
            "source_files": "; ".join(info.get("source_files", [])),
            "last_seen": info.get("last_seen", ""),
        }
        product_rows.append(row)

    if product_rows:
        catalog_csv = os.path.join(output_dir, "product_catalog.csv")
        pd.DataFrame(product_rows).to_csv(catalog_csv, index=False, encoding=csv_encoding)
        csv_files["product_catalog"] = catalog_csv

    return csv_files


def build_review_queue_rows(analysis_results: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a review queue from item-level review flags and quality flags."""
    queue_rows: List[Dict[str, Any]] = []
    for filepath, analysis in analysis_results.items():
        filename = os.path.basename(filepath)
        for item in analysis.get("items", []):
            if item.get("needs_review"):
                queue_rows.append(
                    {
                        "filename": filename,
                        "filepath": filepath,
                        "line_id": item.get("line_id", ""),
                        "raw_item_text": item.get("raw_item_text", ""),
                        "reason": item.get("notes", "Item flagged by LLM as uncertain"),
                        "priority": "high" if (item.get("confidence", 1.0) or 0) < 0.5 else "medium",
                    }
                )

        for flag in analysis.get("quality_flags", []):
            queue_rows.append(
                {
                    "filename": filename,
                    "filepath": filepath,
                    "line_id": "",
                    "raw_item_text": "",
                    "reason": f"Document quality flag: {flag}",
                    "priority": "medium",
                }
            )

    return queue_rows


# ----------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------
def run_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main pipeline execution function.
    """
    logger = setup_logging(config["output_root"], config["log_level"])

    workspace_dir = os.path.join(config["output_root"], config["working_dir"])
    index_dir = os.path.join(workspace_dir, "index")
    raw_ocr_dir = os.path.join(workspace_dir, "raw_ocr")
    llm_refined_dir = os.path.join(workspace_dir, "llm_refined")
    review_queue_dir = os.path.join(workspace_dir, "review_queue")
    structured_dir = os.path.join(workspace_dir, "structured")

    for path in [workspace_dir, index_dir, raw_ocr_dir, llm_refined_dir, review_queue_dir, structured_dir]:
        os.makedirs(path, exist_ok=True)

    config["input_root"] = resolve_unicode_path(config["input_root"])

    config_path = os.path.join(workspace_dir, "processing_config.json")
    save_json(config, config_path)

    logger.info("=" * 80)
    logger.info("Le Petit Handwritten OCR Pipeline")
    logger.info("Input root: %s", config["input_root"])
    logger.info("Output root: %s", config["output_root"])
    logger.info("Workspace: %s", workspace_dir)
    logger.info("=" * 80)

    pipeline_results: Dict[str, Any] = {
        "start_time": datetime.now().isoformat(),
        "config": config,
        "steps": {},
        "summary": {},
        "status": "running",
    }

    analysis_results: Dict[str, Dict[str, Any]] = {}
    product_memory = init_product_memory()
    final_review: Optional[Dict[str, Any]] = None

    try:
        # Step 1: Scan image files
        logger.info("Step 1: Scanning image files...")
        if not os.path.isdir(config["input_root"]):
            logger.error("Input directory does not exist: %s", config["input_root"])
            pipeline_results["status"] = "failed"
            pipeline_results["error"] = f"Input directory does not exist: {config['input_root']}"
            pipeline_results["end_time"] = datetime.now().isoformat()
            return pipeline_results

        file_index = scan_image_files(config["input_root"], config["supported_extensions"])
        index_path = os.path.join(index_dir, "file_index.json")
        save_json(file_index, index_path)

        pipeline_results["steps"]["scanning"] = {
            "status": "completed",
            "files_found": len(file_index),
            "index_path": index_path,
        }
        logger.info("Found %d image files", len(file_index))

        if not file_index:
            logger.warning("No image files found. Exiting pipeline.")
            pipeline_results["status"] = "completed"
            pipeline_results["end_time"] = datetime.now().isoformat()
            return pipeline_results

        # Step 2: OCR extraction
        logger.info("Step 2: Running OCR over handwritten images...")
        extraction_results: Dict[str, Dict[str, Any]] = {}

        for index, file_info in enumerate(file_index, start=1):
            filepath = file_info["full_path"]
            logger.info("OCR [%d/%d]: %s", index, len(file_index), file_info["filename"])

            extraction = extract_text_from_image(filepath, config)
            extraction_results[filepath] = extraction

            extract_filename = f"{sanitize_filename(file_info['relative_path'])}_ocr.json"
            extract_path = os.path.join(raw_ocr_dir, extract_filename)
            save_json(extraction, extract_path)

            file_info["ocr_path"] = extract_path
            file_info["ocr_status"] = "error" if extraction.get("error") else "completed"
            file_info["ocr_confidence"] = extraction.get("average_confidence")

        save_json(file_index, index_path)

        successful_ocr = sum(1 for extraction in extraction_results.values() if not extraction.get("error"))
        pipeline_results["steps"]["ocr_extraction"] = {
            "status": "completed",
            "files_processed": len(extraction_results),
            "successful_ocr": successful_ocr,
            "raw_ocr_dir": raw_ocr_dir,
        }

        # Step 3: Iterative LLM analysis with product memory
        if DEEPSEEK_API_KEY:
            logger.info("Step 3: Running iterative LLM extraction and product memory updates...")
            analyzer = DeepSeekSalesAnalyzer(
                DEEPSEEK_API_KEY,
                model=config.get("llm_model"),
                temperature=float(config.get("llm_temperature", 0.1)),
                max_tokens=int(config.get("llm_max_tokens", 4000)),
            )

            for index, file_info in enumerate(file_index, start=1):
                filepath = file_info["full_path"]
                extraction = extraction_results.get(filepath, {})
                if extraction.get("error"):
                    logger.warning("Skipping LLM analysis for %s due to OCR error", file_info["filename"])
                    continue

                known_products = top_known_products(
                    product_memory,
                    limit=int(config.get("known_products_limit", 40)),
                )
                logger.info("LLM [%d/%d]: %s", index, len(file_index), file_info["filename"])

                try:
                    analysis = analyzer.analyze_sales_scan(extraction, known_products=known_products)
                except Exception as error:
                    logger.error("LLM analysis failed for %s: %s", file_info["filename"], error)
                    analysis = {
                        "error": str(error),
                        "items": [],
                        "quality_flags": ["llm_analysis_failed"],
                    }

                analysis_results[filepath] = analysis

                if "error" not in analysis:
                    product_memory = update_product_memory(
                        product_memory,
                        analysis,
                        source_file=file_info["relative_path"],
                        similarity_threshold=float(config.get("min_product_similarity", 0.84)),
                    )

                analysis_filename = f"{sanitize_filename(file_info['relative_path'])}_analysis.json"
                analysis_path = os.path.join(llm_refined_dir, analysis_filename)
                save_json(analysis, analysis_path)

                delay_seconds = float(config.get("api_call_delay_seconds", 1.5))
                if index < len(file_index):
                    time.sleep(delay_seconds)

            product_memory_path = os.path.join(llm_refined_dir, "iterative_product_memory.json")
            save_json(product_memory, product_memory_path)

            successful_analysis = sum(1 for analysis in analysis_results.values() if "error" not in analysis)
            pipeline_results["steps"]["llm_analysis"] = {
                "status": "completed",
                "files_analyzed": len(analysis_results),
                "successful_analyses": successful_analysis,
                "analysis_dir": llm_refined_dir,
                "product_memory_path": product_memory_path,
            }
        else:
            logger.warning("Step 3: Skipping LLM analysis (no DeepSeek API key).")
            pipeline_results["steps"]["llm_analysis"] = {
                "status": "skipped",
                "reason": "No DeepSeek API key",
            }

        # Step 4: Structured outputs and review queue
        logger.info("Step 4: Writing structured outputs (CSV + review queue)...")
        csv_files = convert_to_csv(
            analysis_results=analysis_results,
            product_memory=product_memory,
            output_dir=structured_dir,
            csv_encoding=config.get("csv_encoding", "utf-8-sig"),
        )

        review_queue_rows = build_review_queue_rows(analysis_results)
        review_queue_csv = os.path.join(review_queue_dir, "review_queue.csv")
        if review_queue_rows:
            pd.DataFrame(review_queue_rows).to_csv(
                review_queue_csv,
                index=False,
                encoding=config.get("csv_encoding", "utf-8-sig"),
            )

        pipeline_results["steps"]["structured_outputs"] = {
            "status": "completed",
            "csv_files": csv_files,
            "review_queue_file": review_queue_csv if review_queue_rows else None,
            "review_queue_items": len(review_queue_rows),
        }

        # Step 5: Final global reconciliation
        if config.get("enable_final_review", True) and DEEPSEEK_API_KEY and analysis_results:
            logger.info("Step 5: Running final global reconciliation review...")
            analyzer = DeepSeekSalesAnalyzer(
                DEEPSEEK_API_KEY,
                model=config.get("llm_model"),
                temperature=float(config.get("llm_temperature", 0.1)),
                max_tokens=int(config.get("llm_max_tokens", 4000)),
            )

            try:
                final_review = analyzer.run_final_reconciliation(analysis_results, product_memory)
            except Exception as error:
                logger.error("Final review failed: %s", error)
                final_review = {
                    "error": str(error),
                    "documents_to_review": [],
                    "cross_file_anomalies": [],
                    "catalog_reconciliation": [],
                    "consistency_score": 0,
                    "final_summary": "Final review failed.",
                }

            final_review_path = os.path.join(structured_dir, "final_global_review.json")
            save_json(final_review, final_review_path)

            # Merge final review documents_to_review into review queue.
            extra_rows = []
            for entry in final_review.get("documents_to_review", []):
                extra_rows.append(
                    {
                        "filename": entry.get("filename", ""),
                        "filepath": "",
                        "line_id": "",
                        "raw_item_text": "",
                        "reason": f"Final review: {entry.get('reason', '')}",
                        "priority": entry.get("priority", "medium"),
                    }
                )

            if extra_rows:
                merged_queue = review_queue_rows + extra_rows
                pd.DataFrame(merged_queue).to_csv(
                    review_queue_csv,
                    index=False,
                    encoding=config.get("csv_encoding", "utf-8-sig"),
                )

            pipeline_results["steps"]["final_review"] = {
                "status": "completed",
                "final_review_path": final_review_path,
                "documents_to_review": len(final_review.get("documents_to_review", [])),
                "consistency_score": final_review.get("consistency_score"),
            }
        else:
            logger.info("Step 5: Skipping final review (disabled, no API key, or no analyses).")
            pipeline_results["steps"]["final_review"] = {
                "status": "skipped",
                "reason": "disabled, no API key, or no analyses",
            }

        # Step 6: Summary
        logger.info("Step 6: Writing summary files...")
        summary = {
            "pipeline_execution": {
                "start_time": pipeline_results["start_time"],
                "end_time": datetime.now().isoformat(),
                "total_files": len(file_index),
            },
            "file_statistics": {
                "total_images": len(file_index),
                "successful_ocr": successful_ocr,
                "successful_analyses": sum(1 for analysis in analysis_results.values() if "error" not in analysis),
            },
            "outputs": {
                "workspace": workspace_dir,
                "index_file": index_path,
                "raw_ocr_dir": raw_ocr_dir,
                "analysis_dir": llm_refined_dir,
                "structured_dir": structured_dir,
                "review_queue_dir": review_queue_dir,
            },
            "final_review": final_review,
        }

        summary_path = os.path.join(workspace_dir, "processing_summary.json")
        save_json(summary, summary_path)

        text_summary = f"""
LE PETIT HANDWRITTEN OCR PIPELINE SUMMARY
========================================

Execution Time: {summary['pipeline_execution']['start_time']} to {summary['pipeline_execution']['end_time']}

FILE STATISTICS:
- Total image files: {summary['file_statistics']['total_images']}
- Successful OCR extractions: {summary['file_statistics']['successful_ocr']}
- Successful LLM analyses: {summary['file_statistics']['successful_analyses']}

OUTPUTS:
- Workspace directory: {summary['outputs']['workspace']}
- Index file: {summary['outputs']['index_file']}
- Raw OCR: {summary['outputs']['raw_ocr_dir']}
- LLM refined: {summary['outputs']['analysis_dir']}
- Structured data: {summary['outputs']['structured_dir']}
- Review queue: {summary['outputs']['review_queue_dir']}

NOTES:
- Product names are normalized iteratively using recurring-scan memory.
- Raw OCR text and raw item lines are preserved for manual audit.
- Final global review is conservative and non-destructive.
"""

        human_summary_path = os.path.join(workspace_dir, "SUMMARY.txt")
        with open(human_summary_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(text_summary.strip() + "\n")

        pipeline_results["summary"] = summary
        pipeline_results["summary_path"] = summary_path
        pipeline_results["human_summary_path"] = human_summary_path
        pipeline_results["status"] = "completed"

        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("Summary saved to: %s", summary_path)
        logger.info("Human-readable summary: %s", human_summary_path)
        logger.info("=" * 80)

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        pipeline_results["error"] = "Interrupted by user"
        pipeline_results["status"] = "interrupted"
        interrupted_path = os.path.join(workspace_dir, "processing_interrupted.json")
        save_json(pipeline_results, interrupted_path)
    except Exception as error:
        logger.error("Pipeline failed: %s", error, exc_info=True)
        pipeline_results["error"] = str(error)
        pipeline_results["status"] = "failed"
        error_path = os.path.join(workspace_dir, "processing_error.json")
        save_json(pipeline_results, error_path)

    pipeline_results["end_time"] = datetime.now().isoformat()
    return pipeline_results


# ----------------------------------------------------------------------
# Command-line interface
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Le Petit handwritten OCR processing pipeline")
    parser.add_argument(
        "--input",
        "-i",
        default="./screenshots/Lê Pétit",
        help="Input root directory with screenshots (default: ./screenshots/Lê Pétit)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./llm_enhanced_results",
        help="Output root directory (default: ./llm_enhanced_results)",
    )
    parser.add_argument(
        "--workspace-name",
        default="./kate_prioritarios_pipeline",
        help="Pipeline workspace folder inside output root",
    )
    parser.add_argument("--api-key", "-k", help="DeepSeek API key (overrides environment variable)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Dry run mode (reserved for future file mutation steps)")
    parser.add_argument("--disable-final-review", action="store_true", help="Skip final global LLM reconciliation")
    parser.add_argument("--config", "-c", help="Path to configuration JSON file")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.config and os.path.exists(args.config):
        with open(args.config, "r", encoding="utf-8") as file_handle:
            user_config = json.load(file_handle)
        config.update(user_config)

    config["input_root"] = args.input
    config["output_root"] = args.output
    config["working_dir"] = args.workspace_name
    config["dry_run"] = args.dry_run
    config["enable_final_review"] = not args.disable_final_review
    config["log_level"] = args.log_level

    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key
        global DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = args.api_key

    results = run_pipeline(config)
    if results.get("status") == "completed":
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
