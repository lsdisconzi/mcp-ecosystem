#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo script to run the enhanced OCR system with configured directory.
Shows how to use the system with your specific screenshot folder.
"""

import os
import sys
import subprocess
from pathlib import Path

print("="*60)
print("Enhanced OCR System - Demo Configuration")
print("="*60)

# Show current configuration
project_dir = "/Users/leandrodisconzi/vps_ecosystem/OCR"
env_path = os.path.join(project_dir, ".env")

print("\nCurrent Configuration:")
print(f"Project directory: {project_dir}")
print(f".env file: {env_path}")

if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        env_content = f.read()
    print("\n.env file content:")
    print(env_content)
else:
    print("ERROR: .env file not found!")

# Check screenshots directory
screenshots_dir = "/Users/leandrodisconzi/vps_ecosystem/OCR/screenshots"
if os.path.exists(screenshots_dir):
    screenshot_files = [f for f in os.listdir(screenshots_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    print(f"\nScreenshots found: {len(screenshot_files)} files")
    if screenshot_files:
        print("First 5 files:")
        for i, f in enumerate(screenshot_files[:5]):
            print(f"  {i+1}. {f}")
else:
    print(f"\nWARNING: Screenshots directory not found: {screenshots_dir}")

# Show available commands
print("\n" + "="*60)
print("AVAILABLE COMMANDS")
print("="*60)

print("\n1. Test OCR extraction (single file):")
print(f"   python extract_webalmoxarife.py {screenshots_dir}/click_20260329_213345_0072.png --output test_ocr.json")

print("\n2. Run enhanced OCR with LLM (all files):")
print(f"   python ocr_with_llm_enhancement.py --input-dir {screenshots_dir} --output-dir ./results")

print("\n3. Run enhanced OCR without LLM (OCR only):")
print(f"   python ocr_with_llm_enhancement.py --input-dir {screenshots_dir} --output-dir ./ocr_results --no-llm")

print("\n4. Test system installation:")
print("   python test_enhancement.py")

# Show API key status
api_key = os.getenv("DEEPSEEK_API_KEY")
if api_key:
    print(f"\nDeepSeek API Key Status: FOUND ({api_key[:10]}...)")
    print("LLM refinement will be available.")
else:
    print("\nDeepSeek API Key Status: NOT FOUND in environment variables")
    print("NOTE: The .env file contains 'your_deepseek_api_key_here' as placeholder")
    print("To use LLM features, edit .env file and replace with your actual API key.")

print("\n" + "="*60)
print("QUICK START")
print("="*60)

print("\nTo get started immediately:")
print(f"1. Install dependencies: pip install -r requirements.txt")
print(f"2. Edit .env file with your DeepSeek API key")
print(f"3. Run test: python test_enhancement.py")
print(f"4. Process screenshots: python ocr_with_llm_enhancement.py")

print("\nExpected output structure:")
print("  ./llm_enhanced_results/")
print("  ├── raw_ocr/                    # Original OCR results")
print("  ├── llm_refined/               # LLM-enhanced results")
print("  ├── comparisons/               # Comparison files")
print("  ├── logs/                      # Processing logs")
print("  └── processing_summary_*.json  # Summary file")

print("\n" + "="*60)
print("READY TO USE")
print("="*60)
print("\nYour enhanced OCR system is configured to process:")
print(f"Input directory: {screenshots_dir}")
print(f"Output directory: {project_dir}/llm_enhanced_results")
print(f"Total screenshots: {len(screenshot_files) if 'screenshot_files' in locals() else 'unknown'}")

print("\nTo begin processing, run:")
print(f"cd {project_dir}")
print("python ocr_with_llm_enhancement.py")