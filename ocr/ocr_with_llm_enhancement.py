#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced OCR system with LLM refinement for WebAlmoxarife screenshots.
Processes all screenshots in a directory, extracts text using OCR, 
then refines results using DeepSeek LLM for better accuracy and coherence.

Features:
1. Batch processing of screenshot directory
2. OCR extraction using existing extract_webalmoxarife.py logic
3. LLM refinement using DeepSeek API
4. Result comparison and validation
5. Output in structured JSON format

Usage:
python ocr_with_llm_enhancement.py --input-dir /path/to/screenshots --output-dir /path/to/results
python ocr_with_llm_enhancement.py --input-dir CPSI --output-dir llm_enhanced_results

Configuration:
Create .env file with DEEPSEEK_API_KEY=your_api_key
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import time
from datetime import datetime

# Import existing OCR functionality
try:
    from extract_webalmoxarife import extract_structure
except ImportError:
    # Fallback: copy essential functions
    import cv2
    import numpy as np
    import pytesseract
    from collections import defaultdict

# LLM integration
try:
    import requests
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logging.warning("OpenAI package not available. LLM features disabled.")

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
    "input_dir": "./screenshots",
    "output_dir": "./llm_enhanced_results",
    "supported_extensions": [".png", ".jpg", ".jpeg", ".bmp", ".tiff"],
    "llm_model": "deepseek-v4-flash",
    "llm_temperature": 0.1,
    "llm_max_tokens": 2000,
    "batch_size": 10,
    "parallel_processing": False,
    "review_prompt": """
You are an expert at analyzing OCR results from legacy Brazilian ERP system screenshots.
The OCR has extracted text from a WebAlmoxarife system interface. Your task is to:

1. REVIEW: Analyze the OCR results for consistency and coherence
2. CORRECT: Fix obvious OCR errors (e.g., "wWebrrigo" -> "Web Almoxarife")
3. STRUCTURE: Organize the information into logical sections
4. ENHANCE: Add context and meaning to the extracted data

OCR Results:
{ocr_results}

Instructions:
- Identify the main purpose of this screen (e.g., "Stock Position Report", "Product Entry", etc.)
- Extract and structure all form fields, buttons, menus, and data tables
- Correct common OCR errors in Portuguese business terms
- If there are filter fields, identify their purpose and valid values
- If there are buttons, identify their functions
- Provide a clean, structured JSON output with:
  * screen_type: Type of screen/form
  * screen_title: Corrected title
  * main_sections: Array of sections with fields/options
  * actions: Available buttons/actions
  * metadata: Additional information

Return ONLY valid JSON, no other text.
"""
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
def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'ocr_llm_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )
    return logging.getLogger(__name__)

# ----------------------------------------------------------------------
# File management
# ----------------------------------------------------------------------
def get_image_files(directory: str, extensions: List[str]) -> List[str]:
    """Get all image files with specified extensions from directory."""
    image_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in extensions):
                image_files.append(os.path.join(root, file))
    return sorted(image_files)

def create_output_structure(output_dir: str) -> Dict[str, str]:
    """Create directory structure for output files."""
    paths = {
        "raw_ocr": os.path.join(output_dir, "raw_ocr"),
        "llm_refined": os.path.join(output_dir, "llm_refined"),
        "comparisons": os.path.join(output_dir, "comparisons"),
        "logs": os.path.join(output_dir, "logs"),
    }
    
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
    
    return paths

# ----------------------------------------------------------------------
# OCR Processing
# ----------------------------------------------------------------------
def process_image_with_ocr(image_path: str) -> Dict[str, Any]:
    """
    Process a single image using the existing OCR extraction.
    Returns structured OCR results.
    """
    try:
        # Use the existing extract_structure function
        result = extract_structure(image_path)
        
        # Add metadata
        result['metadata'] = {
            'filename': os.path.basename(image_path),
            'filepath': image_path,
            'processing_time': datetime.now().isoformat(),
            'ocr_engine': 'Tesseract (Portuguese)'
        }
        
        return result
    except Exception as e:
        logging.error(f"OCR processing failed for {image_path}: {e}")
        return {
            'error': str(e),
            'filename': os.path.basename(image_path),
            'raw_text': ''
        }

# ----------------------------------------------------------------------
# LLM Integration
# ----------------------------------------------------------------------
class DeepSeekClient:
    """Client for DeepSeek LLM API."""
    
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
    
    def refine_ocr_results(self, ocr_results: Dict[str, Any], prompt_template: str) -> Dict[str, Any]:
        """
        Send OCR results to DeepSeek LLM for refinement and structuring.
        """
        try:
            # Format the prompt with OCR results
            ocr_json = json.dumps(ocr_results, ensure_ascii=False, indent=2)
            prompt = prompt_template.format(ocr_results=ocr_json)
            
            if HAS_OPENAI and self.client:
                # Use OpenAI-compatible client
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an expert OCR analyzer for Brazilian business systems."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=2000,
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
                        {"role": "system", "content": "You are an expert OCR analyzer for Brazilian business systems."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
                
                response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                result_text = response.json()["choices"][0]["message"]["content"]
            
            # Parse the JSON response
            refined_result = json.loads(result_text)
            
            # Add metadata
            refined_result['llm_metadata'] = {
                'model': self.model,
                'refinement_time': datetime.now().isoformat(),
                'original_filename': ocr_results.get('metadata', {}).get('filename', 'unknown')
            }
            
            return refined_result
            
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse LLM response as JSON: {e}")
            # Try to extract JSON from text if it's wrapped
            import re
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            return {"error": "Invalid JSON response from LLM", "raw_response": result_text[:500]}
        except Exception as e:
            logging.error(f"LLM refinement failed: {e}")
            return {"error": str(e), "original_ocr": ocr_results}
    
    def compare_and_validate(self, original_ocr: Dict[str, Any], refined_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare original OCR with LLM-refined results and validate improvements.
        """
        comparison = {
            'filename': original_ocr.get('metadata', {}).get('filename', 'unknown'),
            'comparison_time': datetime.now().isoformat(),
            'original_sections_count': len(original_ocr.get('sections', [])),
            'refined_sections_count': len(refined_result.get('main_sections', [])),
            'improvements': []
        }
        
        # Calculate text length difference
        original_text = json.dumps(original_ocr, ensure_ascii=False)
        refined_text = json.dumps(refined_result, ensure_ascii=False)
        comparison['text_length_original'] = len(original_text)
        comparison['text_length_refined'] = len(refined_text)
        
        # Check for obvious improvements
        if 'error' not in refined_result:
            comparison['status'] = 'success'
            
            # Look for structured data improvements
            if 'main_sections' in refined_result and refined_result['main_sections']:
                comparison['improvements'].append('structured_sections_added')
            
            if 'screen_title' in refined_result and refined_result['screen_title']:
                comparison['improvements'].append('title_corrected')
            
            if 'actions' in refined_result and refined_result['actions']:
                comparison['improvements'].append('actions_identified')
        else:
            comparison['status'] = 'failed'
            comparison['error'] = refined_result.get('error', 'Unknown error')
        
        return comparison

# ----------------------------------------------------------------------
# Batch Processing
# ----------------------------------------------------------------------
def process_batch(
    input_dir: str,
    output_dir: str,
    config: Dict[str, Any],
    deepseek_client: Optional[DeepSeekClient] = None
) -> Dict[str, Any]:
    """
    Process all images in input directory with OCR and LLM refinement.
    """
    logger = logging.getLogger(__name__)
    
    # Get image files
    image_files = get_image_files(input_dir, config['supported_extensions'])

    results = {
        'status': 'ok',
        'total_files': len(image_files),
        'processed_files': 0,
        'successful': 0,
        'failed': 0,
        'details': []
    }

    # Create output structure
    output_paths = create_output_structure(output_dir)
    
    if not image_files:
        message = f"No image files found in {input_dir} with extensions {config['supported_extensions']}"
        logger.warning(message)
        results['status'] = 'no_files'
        results['message'] = message

        summary_path = os.path.join(output_dir, f"processing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        return results
    
    logger.info(f"Found {len(image_files)} image files to process")
    
    # Process each file
    for i, image_file in enumerate(image_files, 1):
        try:
            logger.info(f"Processing file {i}/{len(image_files)}: {os.path.basename(image_file)}")
            
            # Step 1: OCR extraction
            ocr_result = process_image_with_ocr(image_file)
            
            # Save raw OCR results
            ocr_filename = os.path.basename(image_file).split('.')[0] + '_ocr.json'
            ocr_output_path = os.path.join(output_paths['raw_ocr'], ocr_filename)
            
            with open(ocr_output_path, 'w', encoding='utf-8') as f:
                json.dump(ocr_result, f, ensure_ascii=False, indent=2)
            
            # Step 2: LLM refinement (if client available)
            refined_result = None
            if deepseek_client and 'error' not in ocr_result:
                try:
                    refined_result = deepseek_client.refine_ocr_results(
                        ocr_result,
                        config['review_prompt']
                    )
                    
                    # Save refined results
                    refined_filename = os.path.basename(image_file).split('.')[0] + '_refined.json'
                    refined_output_path = os.path.join(output_paths['llm_refined'], refined_filename)
                    
                    with open(refined_output_path, 'w', encoding='utf-8') as f:
                        json.dump(refined_result, f, ensure_ascii=False, indent=2)
                    
                    # Step 3: Comparison and validation
                    comparison = deepseek_client.compare_and_validate(ocr_result, refined_result)
                    
                    # Save comparison
                    comp_filename = os.path.basename(image_file).split('.')[0] + '_comparison.json'
                    comp_output_path = os.path.join(output_paths['comparisons'], comp_filename)
                    
                    with open(comp_output_path, 'w', encoding='utf-8') as f:
                        json.dump(comparison, f, ensure_ascii=False, indent=2)
                    
                    results['successful'] += 1
                    results['details'].append({
                        'filename': os.path.basename(image_file),
                        'ocr_success': True,
                        'llm_success': 'error' not in refined_result,
                        'comparison': comparison.get('status', 'unknown')
                    })
                    
                except Exception as e:
                    logger.error(f"LLM refinement failed for {image_file}: {e}")
                    refined_result = {'error': str(e)}
                    results['failed'] += 1
                    results['details'].append({
                        'filename': os.path.basename(image_file),
                        'ocr_success': True,
                        'llm_success': False,
                        'error': str(e)
                    })
            else:
                # No LLM refinement
                logger.info(f"Skipping LLM refinement for {image_file} (no client or OCR error)")
                results['details'].append({
                    'filename': os.path.basename(image_file),
                    'ocr_success': 'error' not in ocr_result,
                    'llm_success': False,
                    'note': 'skipped'
                })
                if 'error' in ocr_result:
                    results['failed'] += 1
                else:
                    results['successful'] += 1
            
            results['processed_files'] += 1
            
            # Rate limiting (optional)
            if i < len(image_files):
                time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Failed to process {image_file}: {e}")
            results['failed'] += 1
            results['details'].append({
                'filename': os.path.basename(image_file),
                'error': str(e)
            })
            continue
    
    # Save summary
    summary_path = os.path.join(output_dir, f"processing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Processing complete. Summary: {results['successful']} successful, {results['failed']} failed")
    
    return results

# ----------------------------------------------------------------------
# Main execution
# ----------------------------------------------------------------------
def main():
    """Main entry point for the enhanced OCR system."""
    parser = argparse.ArgumentParser(
        description='Enhanced OCR with LLM refinement for WebAlmoxarife screenshots'
    )
    parser.add_argument(
        '--input-dir', '-i',
        default=DEFAULT_CONFIG['input_dir'],
        help='Directory containing screenshot images'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default=DEFAULT_CONFIG['output_dir'],
        help='Directory for output results'
    )
    parser.add_argument(
        '--config', '-c',
        help='Path to custom configuration JSON file'
    )
    parser.add_argument(
        '--no-llm', '-n',
        action='store_true',
        help='Skip LLM refinement (OCR only)'
    )
    parser.add_argument(
        '--api-key', '-k',
        help='DeepSeek API key (overrides environment variable)'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging()
    
    # Load configuration
    config = DEFAULT_CONFIG.copy()
    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                custom_config = json.load(f)
            config.update(custom_config)
            logger.info(f"Loaded custom configuration from {args.config}")
        except Exception as e:
            logger.error(f"Failed to load config file {args.config}: {e}")
    
    # Update config with command line args
    config['input_dir'] = args.input_dir
    config['output_dir'] = args.output_dir
    
    # Initialize DeepSeek client
    deepseek_client = None
    if not args.no_llm:
        try:
            api_key = args.api_key or DEEPSEEK_API_KEY
            if not api_key:
                logger.warning("No DeepSeek API key provided. LLM features disabled.")
            else:
                deepseek_client = DeepSeekClient(api_key, model=config.get("llm_model"))
                logger.info("DeepSeek client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DeepSeek client: {e}")
            logger.warning("Continuing without LLM refinement")
    
    # Create output directory
    os.makedirs(config['output_dir'], exist_ok=True)
    
    # Save configuration used
    config_path = os.path.join(config['output_dir'], 'processing_config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    # Process batch
    logger.info(f"Starting batch processing from {config['input_dir']}")
    logger.info(f"Output directory: {config['output_dir']}")
    logger.info(f"LLM refinement: {'enabled' if deepseek_client else 'disabled'}")
    
    results = process_batch(
        config['input_dir'],
        config['output_dir'],
        config,
        deepseek_client
    )
    
    # Print summary
    print("\n" + "="*60)
    print("PROCESSING SUMMARY")
    print("="*60)
    print(f"Total files: {results.get('total_files', 0)}")
    print(f"Processed: {results.get('processed_files', 0)}")
    print(f"Successful: {results.get('successful', 0)}")
    print(f"Failed: {results.get('failed', 0)}")
    print(f"Output directory: {config['output_dir']}")

    if results.get('status') == 'no_files' and results.get('message'):
        print(f"Note: {results['message']}")
    
    if results.get('details'):
        print("\nDetailed results:")
        for detail in results['details'][:5]:  # Show first 5
            status = "✓" if detail.get('llm_success') or detail.get('ocr_success') else "✗"
            print(f"  {status} {detail.get('filename', 'unknown')}")
        
        if len(results['details']) > 5:
            print(f"  ... and {len(results['details']) - 5} more files")
    
    print("\nProcessing complete!")

if __name__ == '__main__':
    main()