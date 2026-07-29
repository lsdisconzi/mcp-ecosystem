# Enhanced OCR System with LLM Refinement

This project provides an OCR extraction system for WebAlmoxarife legacy system screenshots with added LLM (DeepSeek) refinement layer.

## Overview

The system processes screenshots in a directory, extracts text using OCR (Tesseract), then uses DeepSeek LLM to review, make sense, compare, and refine the results one by one.

## Recent Updates

Added the following features:

1. **Directory-based batch processing**: Process all screenshots in a specified directory
2. **LLM refinement layer**: Integration with DeepSeek API for result validation and enhancement
3. **Structured output**: Organized results in JSON format with comparisons
4. **Error handling**: Robust processing with logging and error recovery

## Project Structure

```
OCR/
├── extract_webalmoxarife.py     # Original OCR extraction (single file)
├── ocr_with_llm_enhancement.py  # NEW: Enhanced system with LLM refinement
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
├── screenshots/                 # Directory for input screenshots
├── result.json                  # Example OCR output
└── README.md                    # This file
```

## Installation

1. Install Python dependencies:
```bash
uv pip install -r requirements.txt
```

2. Install Tesseract OCR:
```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-por

# Windows (via Chocolatey)
choco install tesseract
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your DeepSeek API key
```

## Usage

### Basic OCR (single file)
```bash
python extract_webalmoxarife.py screenshots/example.png --output result.json
```

### Enhanced OCR with LLM refinement (batch processing)
```bash
# Process all screenshots in a directory
python ocr_with_llm_enhancement.py --input-dir ./screenshots --output-dir ./results

# With custom API key
python ocr_with_llm_enhancement.py --input-dir ./screenshots --api-key your_key_here

# OCR only (skip LLM)
python ocr_with_llm_enhancement.py --input-dir ./screenshots --no-llm
```

### Command-line Options
```
--input-dir, -i     Directory containing screenshot images (default: ./screenshots)
--output-dir, -o    Directory for output results (default: ./llm_enhanced_results)
--config, -c        Path to custom configuration JSON file
--no-llm, -n        Skip LLM refinement (OCR only)
--api-key, -k       DeepSeek API key (overrides environment variable)
```

## Output Structure

After processing, the output directory will contain:
```
llm_enhanced_results/
├── raw_ocr/                    # Original OCR results (JSON)
├── llm_refined/               # LLM-enhanced results (JSON)
├── comparisons/               # Comparison between OCR and LLM results
├── logs/                      # Processing logs
├── processing_config.json     # Configuration used
└── processing_summary_*.json  # Processing summary
```

## Example Output Format

### Raw OCR Result
```json
{
  "page_title": "Web Almoxarife - Stock Report",
  "sections": [...],
  "footer": [...],
  "metadata": {...}
}
```

### LLM-Refined Result
```json
{
  "screen_type": "stock_position_report",
  "screen_title": "Web Almoxarife - Current Stock Position Report",
  "main_sections": [
    {
      "section_name": "Filters",
      "fields": [
        {"name": "Location", "value": "Main Warehouse"},
        {"name": "Report Type", "value": "Detailed"}
      ]
    }
  ],
  "actions": ["Confirm", "Print", "Export"],
  "llm_metadata": {...}
}
```

## LLM Refinement Process

The LLM performs the following tasks:

1. **Review**: Analyze OCR results for consistency and coherence
2. **Correct**: Fix obvious OCR errors (Portuguese business terms)
3. **Structure**: Organize information into logical sections
4. **Enhance**: Add context and meaning to extracted data
5. **Validate**: Compare with original OCR and identify improvements

## Configuration

Create a `config.json` file for advanced configuration:

```json
{
  "input_dir": "./screenshots",
  "output_dir": "./enhanced_results",
  "supported_extensions": [".png", ".jpg", ".jpeg"],
  "llm_model": "deepseek-chat",
  "llm_temperature": 0.1,
  "batch_size": 10,
  "review_prompt": "Custom prompt for LLM refinement..."
}
```

## Dependencies

- Python 3.8+
- pytesseract (OCR)
- opencv-python (image processing)
- openai (LLM client for DeepSeek)
- requests (HTTP client)
- python-dotenv (environment variables)

## Error Handling

The system includes:
- Automatic retry for API failures
- Comprehensive logging
- Error recovery for individual files
- Detailed error reports in output

## Performance Considerations

- Processing time: ~10-30 seconds per image (OCR + LLM)
- Batch size: Configurable (default: 10)
- Rate limiting: Built-in delays between API calls
- Parallel processing: Optional (not implemented by default)

## Troubleshooting

1. **No text detected**: Check image quality and Tesseract installation
2. **API errors**: Verify DeepSeek API key and internet connection
3. **Memory issues**: Reduce batch size for large directories
4. **Encoding problems**: Ensure UTF-8 encoding for Portuguese text

## License

This project is provided as-is for educational and development purposes.

## Support

For issues or questions, please check the error logs and ensure all dependencies are properly installed.