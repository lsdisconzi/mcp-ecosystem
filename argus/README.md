# ARGUS - Legal Framework Analyzer Generator

## Overview
Argus is an AI-powered legal framework analyzer generator that creates specialized analysis tools from legal documents. It transforms PDFs and text documents into interactive JavaScript analyzers that can detect violations of legal frameworks in transcripts and conversations.

## Key Features
- **AI-Powered Config Generation**: Uses deepseek-reasoner to automatically create framework configurations
- **Multi-Language Support**: UI available in English, Spanish, Portuguese, Italian, and Hindi
- **PDF Extraction**: Extracts text from PDF documents using pdfminer.six/PyPDF2
- **Legal Precision**: Enhanced article extraction with context preservation
- **Quality Control**: SYSTEM_PROMPT fix eliminates metadata pollution
- **Deployment Ready**: Generates complete packages for pinocchio-multi integration

## Architecture
```
Argus/
├── app.py                               # Flask application (primary entrypoint)
├── ingestors/
│   └── integrated_legal_framework_parser.py  # Core parser (17 methods)
├── templates/
│   └── frameworks.html                  # Builder UI
├── docs/                                # Documentation
└── requirements.txt                     # Dependencies
```

## Quick Start

### 1. Installation
```bash
cd /Users/repos/mcp-ecosystem/argus
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start the Server
```bash
python app.py
```

### 3. Access the Interface
- **Dashboard**: http://localhost:8029/
- **Framework Builder**: http://localhost:8029/view?path=frameworks/frameworks.html

## Workflow

### Step 1: Upload Legal Document
- Upload PDF or text file containing legal framework
- System extracts text and displays it in the editor

### Step 2: Generate AI Configuration
- Click "Generate Config with AI"
- Watch real-time reasoning from deepseek-reasoner
- Review and edit generated JSON configuration

### Step 3: Generate JavaScript Analyzer
- Select output language
- Click "Generate JS Analyzer"
- System creates specialized analyzer with SYSTEM_PROMPT fix

### Step 4: Download Package
- Download complete ZIP package containing:
  - Generated JavaScript analyzer
  - Configuration file
  - AI prompt template
  - Original document

## Integration with pinocchio-multi

### Deployment Process
1. **Generate Framework** in Argus UI
2. **Download Package** as ZIP file
3. **Extract** to pinocchio-multi directory:
   ```
   pinocchio-multi/static/js/legal_frameworks/{Framework}Analyzer/
   ```
4. **Run watch script** to register framework:
   ```bash
   cd pinocchio-multi/scripts
   python watch_frameworks.py
   ```
5. **Framework appears** in pinocchio-multi UI checkbox list

### Generated Files Structure
```
{Framework}Analyzer/
├── {Framework}Analyzer.js          # Core analyzer with SYSTEM_PROMPT fix
├── config.json                     # Framework metadata and regex patterns
├── generated_prompt.txt            # Full AI prompt for reference
└── {Framework_Document}.txt/md     # Original legal document
```

## Integration with Awareness-Agents

### Connection Points
1. **Legal Framework Analysis**: Generated analyzers can be used by awareness-agents for legal compliance checking
2. **Transcript Processing**: Analyzers detect violations in conversation transcripts
3. **Multi-Agent Coordination**: Different frameworks can be applied by different specialized agents

### Usage Pattern
```javascript
// Example usage in awareness-agent context
const analyzer = require('./TokyoConventionAnalyzer.js');
const violations = analyzer.analyzeTranscript(transcriptText, 'Tokyo Convention');
```

## API Endpoints

### 1. PDF Text Extraction
```
POST /api/extract_pdf_text
Content-Type: multipart/form-data
Body: file (PDF file)
Response: { "text": "...", "filename": "..." }
```

### 2. AI Config Generation
```
POST /api/generate_config_from_text
Content-Type: application/json
Body: { "framework_text": "...", "model": "deepseek-reasoner", "stream": true }
Response: Server-Sent Events stream
```

### 3. Framework Analyzer Generation
```
POST /api/build_framework
Content-Type: application/json
Body: {
  "framework_text": "...",
  "config_json": "{...}",
  "output_filename": "...",
  "output_language": "en"
}
Response: { "generated_js": "...", "generated_prompt": "...", "filename": "..." }
```

## Quality Assurance

### SYSTEM_PROMPT Fix
Argus includes a critical fix that eliminates metadata pollution in generated analyzers. The new SYSTEM_PROMPT explicitly forbids:
- ❌ Metadata headers: "Framework:", "Jurisdiction:", "Analysis Date:"
- ❌ Standalone severity lines: "Severity: HIGH -"
- ❌ Introduction preambles: "Based on the analysis..."
- ❌ Negative findings as violations: "No Violation -"

### Forbidden Patterns Enforcement
Generated analyzers produce clean, professional output with severity integrated within analysis paragraphs.

## Supported Legal Frameworks

### Types Handled
- International Conventions (ICAO, Montreal, Tokyo)
- National Laws (Brazilian CDC, Chilean Aeronautical Law)
- Regulations and Resolutions
- Corporate Policies and Codes of Conduct

### Jurisdiction Detection
- Brazil (ANAC, CDC)
- Chile (DGAC)
- International (ICAO)
- European Union
- Custom jurisdictions

## Documentation

### Complete Analysis
See `docs/ARGUS_ANALYSIS_REPORT.md` for comprehensive system analysis.

### Quick Integration Guide
See `docs/INTEGRATION_GUIDE.md` for pinocchio-multi and awareness-agents integration.

## Dependencies
- Flask & Flask-CORS
- pdfminer.six / PyPDF2
- requests (for AI streaming)
- Python 3.8+

## Troubleshooting

### Common Issues
1. **PDF extraction fails**: Install pdfminer.six: `pip install pdfminer.six`
2. **AI streaming not working**: Ensure deepseek-stream-proxy is running on localhost:8019
3. **CORS errors**: Flask-CORS is configured; check browser console
4. **File upload size**: Limit is 32MB; compress large PDFs if needed

### Logs
Check Flask application logs for detailed error information.

## Development

### Adding New Languages
1. Edit `app-framework-builder.py` - add language to `ui_strings` dictionary
2. Update `integrated_legal_framework_parser.py` - add language-specific patterns if needed

### Extending Parser
The `IntegratedLegalFrameworkParser` class is modular. Add new methods for:
- Additional legal pattern detection
- Specialized jurisdiction handling
- Custom article classification

## License
Proprietary - Part of the SA Server ecosystem

## Support
For issues and feature requests, contact the development team.

---
**Last Updated**: $(date)
**Version**: 1.0.0
**Port**: 8029